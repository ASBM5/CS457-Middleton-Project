#!/usr/bin/env python3
"""Ward game client.

Connects to a Ward server by DNS hostname, sends only CONNECT, MOVE and
DISCONNECT, and displays nothing but server-provided state.

Usage:
    python3 client.py -h
    python3 client.py -i server.middleton.edu -p 8080
"""

import argparse
import json
import os
import socket
import sys
import threading
import time

# ==========================================================================
# Wire protocol (protocol_blueprint.md): constants, NDJSON framing,
# serialization and schema validation. server.py carries its own copy of the
# parts it needs so each file runs on its own.
# ==========================================================================
WORD_LENGTH = 5
MAX_MESSAGE_BYTES = 1024      # includes the trailing newline
MAX_ALIAS_LENGTH = 20
MIN_PORT = 1024
MAX_PORT = 65535

# The client only accepts these message types from the server.
SERVER_TYPES = frozenset(
    {"LOBBY_WAIT", "GAME_START", "STATE_UPDATE", "ERROR", "GAME_OVER"})

# Every message carries exactly these four top-level fields.
ENVELOPE_FIELDS = frozenset({"msg_type", "player_id", "payload", "timestamp"})

# Exact payload schema per server message: field name -> expected type(s).
NoneType = type(None)
PAYLOAD_SCHEMAS = {
    "LOBBY_WAIT": {"assigned_player_id": str, "message": str},
    "GAME_START": {"assigned_player_id": str, "word_length": int,
                   "starting_player": str, "turn": int},
    "STATE_UPDATE": {"completed_turn": int, "guess": str, "feedback": list,
                     "next_player": (str, NoneType), "game_status": str},
    "ERROR": {"code": str, "message": str},
    "GAME_OVER": {"winner": str, "reason": str, "hidden_word": str},
}


def port_number(text):
    """argparse type: an integer port within MIN_PORT..MAX_PORT."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a valid port number") from None
    if not MIN_PORT <= value <= MAX_PORT:
        raise argparse.ArgumentTypeError(
            f"port must be between {MIN_PORT} and {MAX_PORT} (got {value})")
    return value


def encode_message(msg_type, player_id, payload):
    """Serialize one protocol message to a newline-terminated UTF-8 line."""
    message = {
        "msg_type": msg_type,
        "player_id": player_id,
        "payload": payload,
        "timestamp": int(time.time()),
    }
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("message exceeds MAX_MESSAGE_BYTES")
    return data


def _type_ok(value, expected):
    """isinstance check that does not let bool pass as int."""
    if isinstance(value, bool):
        return expected is bool
    return isinstance(value, expected)


def parse_message(raw, allowed_types):
    """Decode and schema-validate one framed line (without its newline).

    Returns (message, None) on success or (None, "INVALID_MESSAGE").
    """
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, "INVALID_MESSAGE"

    if not isinstance(msg, dict) or set(msg) != ENVELOPE_FIELDS:
        return None, "INVALID_MESSAGE"
    if not isinstance(msg["msg_type"], str) \
            or msg["msg_type"] not in allowed_types:
        return None, "INVALID_MESSAGE"
    if msg["player_id"] is not None and not isinstance(msg["player_id"], str):
        return None, "INVALID_MESSAGE"
    if not _type_ok(msg["timestamp"], int):
        return None, "INVALID_MESSAGE"

    payload = msg["payload"]
    schema = PAYLOAD_SCHEMAS[msg["msg_type"]]
    if not isinstance(payload, dict) or set(payload) != set(schema):
        return None, "INVALID_MESSAGE"
    for field, expected in schema.items():
        if not _type_ok(payload[field], expected):
            return None, "INVALID_MESSAGE"
    return msg, None


class LineBuffer:
    """Accumulates TCP bytes and yields complete newline-terminated lines.

    Handles fragmentation (a message split across recv() calls) and
    coalescing (several messages in one recv()). Enforces MAX_MESSAGE_BYTES.
    """

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        """Add bytes; return (complete_lines, too_large)."""
        self._buf.extend(data)
        lines = []
        while True:
            idx = self._buf.find(b"\n")
            if idx == -1:
                return lines, len(self._buf) >= MAX_MESSAGE_BYTES
            if idx + 1 > MAX_MESSAGE_BYTES:
                return lines, True
            lines.append(bytes(self._buf[:idx]))
            del self._buf[:idx + 1]

# ==========================================================================
# End of protocol section
# ==========================================================================

CONNECT_TIMEOUT_SECONDS = 10
RECV_SIZE = 4096

# ANSI colours used for tiles when stdout is a real terminal.
COLORS = {"GREEN": "\033[42;30m", "YELLOW": "\033[43;30m",
          "RED": "\033[41;97m"}
RESET = "\033[0m"


def alias_text(text):
    """argparse type: a non-empty alias of at most MAX_ALIAS_LENGTH chars."""
    if not 1 <= len(text) <= MAX_ALIAS_LENGTH:
        raise argparse.ArgumentTypeError(
            f"alias must be 1-{MAX_ALIAS_LENGTH} characters")
    return text


def parse_args(argv=None):
    """Client CLI: -i <host> and -p <port> are required, -h prints help."""
    parser = argparse.ArgumentParser(
        description="Ward two-player word guessing game client.",
        epilog="Example: python3 client.py -i server.middleton.edu -p 8080")
    parser.add_argument("-i", "--hostname", required=True,
                        metavar="HOSTNAME",
                        help="server DNS hostname (resolved at startup)")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        metavar="PORT",
                        help="server TCP port (1024-65535)")
    parser.add_argument("-a", "--alias", type=alias_text, default="Player",
                        metavar="NAME",
                        help="display name sent to the server (optional)")
    return parser.parse_args(argv)


def resolve_hostname(hostname):
    """Resolve a DNS name to an IPv4 address or exit cleanly with code 1."""
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, UnicodeError):
        print(f"[ERROR] Unable to resolve DNS hostname '{hostname}'.")
        print("Please check your Cisco router DNS configuration "
              "('ip dns server' / 'ip host') or verify domain spelling.")
        sys.exit(1)


def open_connection(server_ip, port):
    """Create the TCP socket and connect, or exit cleanly with code 1."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT_SECONDS)
    try:
        sock.connect((server_ip, port))
    except OSError as exc:      # refused, unreachable, timed out, ...
        print(f"[ERROR] Could not connect to {server_ip}:{port} ({exc}).")
        print("Check that the server is running and the port is correct.")
        sock.close()
        sys.exit(1)
    sock.settimeout(None)       # the server enforces the idle timeout
    return sock


class WardClient:
    """Receiver thread prints server updates; main thread reads guesses."""

    def __init__(self, sock, alias):
        self.sock = sock
        self.alias = alias
        self.player_id = None
        self.active_player = None
        self.current_turn = None
        self.history = []               # (turn, player, guess, feedback)
        self.use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self.turn_ready = threading.Event()   # set when a guess is needed
        self.done = threading.Event()         # set when the session ends
        self.prompting = False
        self._send_lock = threading.Lock()

    # --- Sending ---------------------------------------------------------
    def send(self, msg_type, payload):
        """Send one framed message; ends the session if the socket fails."""
        data = encode_message(msg_type, self.player_id, payload)
        try:
            with self._send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            print("[!] Lost connection to the server.")
            self.done.set()
            return False

    def quit(self):
        """Intentional quit: tell the server, then end the session."""
        if not self.done.is_set():
            self.send("DISCONNECT", {"reason": "QUIT"})
            print("You left the game.")
            self.done.set()

    # --- Receiving (runs in its own thread) --------------------------------
    def receive_loop(self):
        """Read the byte stream, split on newlines, dispatch each message."""
        buffer = LineBuffer()
        try:
            while not self.done.is_set():
                data = self.sock.recv(RECV_SIZE)
                if not data:
                    break
                lines, too_large = buffer.feed(data)
                for raw in lines:
                    msg, err = parse_message(raw, SERVER_TYPES)
                    if err:
                        print("[!] Ignoring malformed message from server.")
                    else:
                        self.handle_message(msg)
                if too_large:
                    print("[!] Server sent an oversized message.")
                    break
        except OSError:
            pass
        if not self.done.is_set():
            print("[!] The server closed the connection.")
            self.done.set()

    def handle_message(self, msg):
        """Update local display state from one server message."""
        kind, payload = msg["msg_type"], msg["payload"]
        if kind == "LOBBY_WAIT":
            self.player_id = payload["assigned_player_id"]
            print(f"Connected as {self.player_id}. Waiting for Player 2...")
        elif kind == "GAME_START":
            self.player_id = payload["assigned_player_id"]
            self.active_player = payload["starting_player"]
            self.current_turn = payload["turn"]
            self.print_banner(payload["word_length"])
            self.announce_turn()
        elif kind == "STATE_UPDATE":
            self.history.append((payload["completed_turn"],
                                 self.active_player, payload["guess"],
                                 payload["feedback"]))
            self.print_board()
            if payload["game_status"] == "ACTIVE":
                self.active_player = payload["next_player"]
                self.current_turn = payload["completed_turn"] + 1
                self.announce_turn()
        elif kind == "ERROR":
            print(f"[Server error] {payload['code']}: {payload['message']}")
            if payload["code"] == "ROOM_FULL":
                self.done.set()
            elif self.active_player == self.player_id:
                self.turn_ready.set()        # let the player try again
        elif kind == "GAME_OVER":
            self.print_game_over(payload)
            self.done.set()
            if self.prompting:
                print("(Press Enter to exit.)")

    # --- Display -----------------------------------------------------------
    def opponent(self):
        return "Player_2" if self.player_id == "Player_1" else "Player_1"

    def print_banner(self, word_length):
        print("\n" + "=" * 44)
        print(f" WARD - you are {self.player_id}")
        print(f" Guess the hidden {word_length}-letter word.")
        print(" Tiles: [X] right spot | (X) wrong spot |  X  not in word")
        print("=" * 44)

    def tile(self, letter, feedback):
        """Render one letter; brackets keep it readable without colour."""
        text = {"GREEN": f"[{letter}]", "YELLOW": f"({letter})",
                "RED": f" {letter} "}[feedback]
        if self.use_color:
            return f"{COLORS[feedback]}{text}{RESET}"
        return text

    def print_board(self):
        """Show every guess so far, with who made it, plus a summary."""
        print("\n--- Board ---")
        for turn, player, guess, feedback in self.history:
            tiles = " ".join(self.tile(ch, fb)
                             for ch, fb in zip(guess, feedback))
            owner = "You" if player == self.player_id else player
            print(f" Turn {turn:>2} | {owner:<9} | {tiles}")
        mine = sum(1 for h in self.history if h[1] == self.player_id)
        print(f" Guesses: you {mine} | {self.opponent()} "
              f"{len(self.history) - mine}")

    def announce_turn(self):
        if self.active_player == self.player_id:
            print(f"\n*** Your Turn (turn {self.current_turn}) ***")
            self.turn_ready.set()
        else:
            print(f"\nWaiting for {self.active_player}'s guess...")

    def print_game_over(self, payload):
        winner = payload["winner"]
        outcome = "YOU WIN!" if winner == self.player_id else "You lose."
        print("\n" + "=" * 44)
        print(f" GAME OVER - {outcome}")
        print(f" Winner: {winner} ({payload['reason']})")
        print(f" Hidden word: {payload['hidden_word']}")
        print("=" * 44)

    # --- Main thread: reading the player's guesses -------------------------
    def take_turn(self):
        """Prompt for one guess and send it as a MOVE."""
        self.prompting = True
        try:
            text = input("Your guess (or 'quit')> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.quit()
            return
        finally:
            self.prompting = False
        if self.done.is_set():
            return
        if text.lower() in ("quit", "exit"):
            self.quit()
        elif len(text) != WORD_LENGTH or not (text.isascii()
                                              and text.isalpha()):
            print(f"Please enter exactly {WORD_LENGTH} letters.")
            self.turn_ready.set()
        else:
            self.send("MOVE", {"turn": self.current_turn, "guess": text})

    def run(self):
        """Send CONNECT, start the receiver, and serve turn prompts."""
        if not self.send("CONNECT", {"alias": self.alias}):
            return
        threading.Thread(target=self.receive_loop, daemon=True).start()
        try:
            while not self.done.is_set():
                if self.turn_ready.wait(timeout=0.2):
                    self.turn_ready.clear()
                    self.take_turn()
        except KeyboardInterrupt:
            self.quit()
        finally:
            try:
                self.sock.close()
            except OSError:
                pass


def main(argv=None):
    args = parse_args(argv)
    server_ip = resolve_hostname(args.hostname)
    print(f"Resolved {args.hostname} -> {server_ip}")
    sock = open_connection(server_ip, args.port)
    WardClient(sock, args.alias).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
