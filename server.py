#!/usr/bin/env python3
"""Ward game server.

Implements the Sprint 1 FSM (fsm_specification.md) on top of the Sprint 2
concurrency design (concurrency_design.md): the main thread only accepts
connections, every client gets its own worker thread, and all shared game
state is guarded by a single reentrant lock, ``game_lock``.

Usage:
    python3 server.py -h
    python3 server.py -p 8080
"""

import argparse
import json
import logging
import os
import random
import re
import socket
import sys
import threading
import time
from collections import Counter

log = logging.getLogger("ward.server")

# ==========================================================================
# Wire protocol (protocol_blueprint.md): constants, NDJSON framing,
# serialization and schema validation. client.py carries its own copy of the
# parts it needs so each file runs on its own.
# ==========================================================================
WORD_LENGTH = 5
MAX_MESSAGE_BYTES = 1024      # includes the trailing newline
MAX_ALIAS_LENGTH = 20
IDLE_TIMEOUT_SECONDS = 300
MIN_PORT = 1024
MAX_PORT = 65535

SERVER_ID = "SERVER"
PLAYER_IDS = ("Player_1", "Player_2")

# The server only accepts these message types from clients.
CLIENT_TYPES = frozenset({"CONNECT", "MOVE", "DISCONNECT"})

# Every message carries exactly these four top-level fields.
ENVELOPE_FIELDS = frozenset({"msg_type", "player_id", "payload", "timestamp"})

# Exact payload schema per client message: field name -> expected type.
PAYLOAD_SCHEMAS = {
    "CONNECT": {"alias": str},
    "MOVE": {"turn": int, "guess": str},
    "DISCONNECT": {"reason": str},
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
    Size is checked by LineBuffer; phase, player, turn and guess checks
    belong to the FSM code below.
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

    if msg["msg_type"] == "CONNECT" \
            and not 1 <= len(payload["alias"]) <= MAX_ALIAS_LENGTH:
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
        """Add bytes; return (complete_lines, too_large).

        Lines are returned without their newline. If too_large is True the
        next message exceeded MAX_MESSAGE_BYTES; earlier lines are still valid.
        """
        self._buf.extend(data)
        lines = []
        while True:
            idx = self._buf.find(b"\n")
            if idx == -1:
                # A full limit's worth of bytes with no newline means the
                # finished message would be over the limit.
                return lines, len(self._buf) >= MAX_MESSAGE_BYTES
            if idx + 1 > MAX_MESSAGE_BYTES:
                return lines, True
            lines.append(bytes(self._buf[:idx]))
            del self._buf[:idx + 1]

    def clear(self):
        """Discard any partial data (used during cleanup)."""
        self._buf.clear()

# ==========================================================================
# End of protocol section
# ==========================================================================

# --- FSM states (fsm_specification.md, Section 2) ---------------------------
INIT = "INIT"
WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
GAME_START = "GAME_START"
PLAYER_TURN = "PLAYER_TURN"
EVALUATE_MOVE = "EVALUATE_MOVE"
GAME_OVER = "GAME_OVER"
CLEANUP = "CLEANUP"

MAX_PLAYERS = 2
RECV_SIZE = 1024
GUESS_PATTERN = re.compile(rf"[A-Za-z]{{{WORD_LENGTH}}}")

# The hidden word is picked from this list. Guesses are NOT checked
# against it (the protocol accepts any WORD_LENGTH letters).
WORD_LIST = [
    "GRAPE", "APPLE", "BRICK", "CRANE", "DREAM", "FLAME", "GHOST", "HOUSE",
    "JUMPY", "KNIFE", "LEMON", "MANGO", "NIGHT", "OCEAN", "PLANT", "QUIET",
    "RIVER", "STONE", "TIGER", "UNCLE", "VIVID", "WATER", "YOUTH", "ZEBRA",
    "BREAD", "CHAIR", "DANCE", "EAGLE", "FROST", "GLASS", "HEART", "IVORY",
    "LIGHT", "MUSIC", "NOBLE", "PIANO", "QUEEN", "ROBOT", "SUGAR", "TRAIN",
    "WORLD", "SMILE", "CLOUD", "BEACH", "STORM", "PEARL", "FLOOR", "SHEEP",
]


def evaluate_guess(guess, hidden):
    """Two-pass feedback from protocol_blueprint.md ("Feedback Rules").

    Pass 1 marks exact matches GREEN and sets those hidden letters aside.
    Pass 2 marks a remaining guess letter YELLOW only if an unused copy of
    that letter is left in the hidden word; otherwise it is RED.
    """
    feedback = ["RED"] * len(guess)
    unmatched = Counter()
    for i, letter in enumerate(hidden):
        if guess[i] == letter:
            feedback[i] = "GREEN"
        else:
            unmatched[letter] += 1
    for i, letter in enumerate(guess):
        if feedback[i] != "GREEN" and unmatched[letter] > 0:
            feedback[i] = "YELLOW"
            unmatched[letter] -= 1
    return feedback


def pick_hidden_word():
    """Choose the hidden word. WARD_SECRET_WORD overrides it for testing."""
    forced = os.environ.get("WARD_SECRET_WORD", "").upper()
    if GUESS_PATTERN.fullmatch(forced):
        return forced
    return random.choice(WORD_LIST)


class Connection:
    """Per-client record: socket, receive buffer, identity, and flags."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buffer = LineBuffer()      # owned by this client's worker only
        self.player_id = None           # set on a successful CONNECT
        self.alias = None
        self.disconnected = False       # guarded by game_lock
        self._send_lock = threading.Lock()   # keeps framed lines intact

    @property
    def label(self):
        """Short text used in log lines."""
        who = self.player_id or "unjoined"
        return f"{who}@{self.addr[0]}:{self.addr[1]}"

    def send(self, msg_type, payload):
        """Send one framed message. Returns False if the socket failed."""
        data = encode_message(msg_type, SERVER_ID, payload)
        try:
            with self._send_lock:
                self.sock.sendall(data)
            return True
        except OSError:      # BrokenPipe, ConnectionReset, timeout, ...
            return False

    def send_error(self, code, message):
        """Send an ERROR message to this client only."""
        log.info("ERROR %s -> %s", code, self.label)
        return self.send("ERROR", {"code": code, "message": message})

    def close(self):
        """Shut down then close; shutdown also wakes a blocked recv()."""
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class WardServer:
    """Listening socket, accept loop, and the shared game/FSM state."""

    def __init__(self, host="0.0.0.0", port=8080):
        self.host = host
        self.port = port
        self.listener = None
        self._stopping = False

        # --- Shared state: every access below happens under game_lock ---
        self.game_lock = threading.RLock()
        self.state = INIT
        self.players = {}           # "Player_1"/"Player_2" -> Connection
        self.active_player = None
        self.current_turn = 0
        self.hidden_word = None
        self.match_result = None    # {"winner": ..., "reason": ...}

    # ------------------------------------------------------------------
    # Startup / accept loop (main thread)
    # ------------------------------------------------------------------
    def start(self):
        """INIT: create, bind and listen on the TCP socket."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen()
        sock.settimeout(0.5)        # lets the accept loop notice stop()
        self.listener = sock
        self.port = sock.getsockname()[1]
        with self.game_lock:
            self._set_state(WAITING_FOR_PLAYERS)
        log.info("Listening on %s:%d", self.host, self.port)

    def serve_forever(self):
        """The main thread only accepts; workers do everything else."""
        while not self._stopping:
            try:
                sock, addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stopping:
                    break
                continue
            sock.settimeout(IDLE_TIMEOUT_SECONDS)
            conn = Connection(sock, addr)
            log.info("Accepted connection from %s:%d", *addr)
            threading.Thread(target=self.worker, args=(conn,),
                             daemon=True).start()

    def stop(self):
        """Close the listener and every client socket."""
        self._stopping = True
        with self.game_lock:
            for conn in list(self.players.values()):
                conn.disconnected = True
                conn.close()
        if self.listener:
            self.listener.close()

    # ------------------------------------------------------------------
    # Worker thread: one per client
    # ------------------------------------------------------------------
    def worker(self, conn):
        """Read, frame, and parse outside the lock; act on messages inside."""
        try:
            while not conn.disconnected:
                data = conn.sock.recv(RECV_SIZE)          # no lock held
                if not data:                              # EOF
                    self.handle_disconnect(conn, "connection closed (EOF)")
                    return
                lines, too_large = conn.buffer.feed(data)
                for raw in lines:
                    if conn.disconnected:
                        return
                    msg, err = parse_message(raw, CLIENT_TYPES)
                    if err:
                        conn.send_error(err, "Malformed or unknown message.")
                        continue
                    with self.game_lock:
                        self.process_message(conn, msg)
                if too_large and not conn.disconnected:
                    conn.send_error("MESSAGE_TOO_LARGE",
                                    "Message exceeds the size limit.")
                    self.handle_disconnect(conn, "oversized message")
                    return
        except (ConnectionResetError, BrokenPipeError,
                ConnectionAbortedError, TimeoutError, socket.timeout) as exc:
            self.handle_disconnect(conn, type(exc).__name__)
        except OSError as exc:       # e.g. socket closed under us
            self.handle_disconnect(conn, f"socket error: {exc}")
        except Exception:            # never let a bug kill the server
            log.exception("Unexpected error in worker for %s", conn.label)
            self.handle_disconnect(conn, "internal error")

    # ------------------------------------------------------------------
    # Message handling (game_lock is held by the caller)
    # ------------------------------------------------------------------
    def process_message(self, conn, msg):
        """Dispatch a schema-valid message according to the FSM."""
        kind = msg["msg_type"]
        if kind == "CONNECT":
            self._on_connect(conn, msg)
        elif kind == "MOVE":
            self._on_move(conn, msg)
        elif kind == "DISCONNECT":
            # null is legal: the client may quit before it learns its id.
            if msg["player_id"] not in (None, conn.player_id):
                conn.send_error("INVALID_PLAYER",
                                "player_id does not match this connection.")
            else:
                self.handle_disconnect(conn, "client sent DISCONNECT")

    def _on_connect(self, conn, msg):
        """WAITING_FOR_PLAYERS: assign a slot, or reject with an error."""
        if conn.player_id is not None:
            conn.send_error("INVALID_PHASE", "You have already joined.")
            return
        if msg["player_id"] is not None:
            conn.send_error("INVALID_PLAYER",
                            "player_id must be null in CONNECT.")
            return
        if len(self.players) >= MAX_PLAYERS:
            conn.send_error("ROOM_FULL",
                            "Two players are already connected.")
            conn.disconnected = True
            conn.close()
            return

        pid = next(p for p in PLAYER_IDS if p not in self.players)
        conn.player_id = pid
        conn.alias = msg["payload"]["alias"]
        self.players[pid] = conn
        log.info("%s joined as %s (alias %r)", conn.addr, pid, conn.alias)

        if len(self.players) < MAX_PLAYERS:
            if not conn.send("LOBBY_WAIT", {
                    "assigned_player_id": pid,
                    "message": "Waiting for second player."}):
                self.handle_disconnect(conn, "send failure")
        else:
            self._start_game()

    def _start_game(self):
        """GAME_START: pick the word, announce, then enter PLAYER_TURN."""
        self._set_state(GAME_START)
        self.hidden_word = pick_hidden_word()
        self.active_player = "Player_1"
        self.current_turn = 1
        log.info("Hidden word selected (%s). Player_1 starts.",
                 self.hidden_word)
        failed = self._broadcast("GAME_START", lambda pid: {
            "assigned_player_id": pid,
            "word_length": WORD_LENGTH,
            "starting_player": "Player_1",
            "turn": 1})
        if failed:      # a player vanished during GAME_START -> forfeit
            self.handle_disconnect(failed[0], "send failure")
            return
        self._set_state(PLAYER_TURN)

    def _on_move(self, conn, msg):
        """Validate a MOVE in the documented order, then evaluate it."""
        # Check 3: is MOVE allowed in the current state?
        if self.state != PLAYER_TURN:
            conn.send_error("INVALID_PHASE", "No game is in progress.")
            return
        # Check 4: does player_id match this connection?
        if conn.player_id is None or msg["player_id"] != conn.player_id:
            conn.send_error("INVALID_PLAYER",
                            "player_id does not match this connection.")
            return
        # Check 5: active player and turn number.
        payload = msg["payload"]
        if conn.player_id != self.active_player:
            conn.send_error("INVALID_TURN", "It is not your turn.")
            return
        if payload["turn"] != self.current_turn:
            conn.send_error("INVALID_TURN", "Wrong turn number.")
            return
        # Check 6: guess format.
        if not GUESS_PATTERN.fullmatch(payload["guess"]):
            conn.send_error(
                "INVALID_GUESS",
                f"Guess must be exactly {WORD_LENGTH} letters (A-Z).")
            return

        self._evaluate_move(conn, payload["guess"].upper())

    def _evaluate_move(self, conn, guess):
        """EVALUATE_MOVE: build feedback, then continue or end the game."""
        self._set_state(EVALUATE_MOVE)
        feedback = evaluate_guess(guess, self.hidden_word)
        completed_turn = self.current_turn
        log.info("%s guessed %s -> %s", conn.player_id, guess,
                 " ".join(f[0] for f in feedback))

        if guess == self.hidden_word:
            self._broadcast("STATE_UPDATE", {
                "completed_turn": completed_turn, "guess": guess,
                "feedback": feedback, "next_player": None,
                "game_status": "COMPLETE"})
            self._end_match(conn.player_id, "CORRECT_GUESS")
            return

        self.active_player = next(p for p in PLAYER_IDS
                                  if p != conn.player_id)
        self.current_turn += 1
        self._set_state(PLAYER_TURN)
        failed = self._broadcast("STATE_UPDATE", {
            "completed_turn": completed_turn, "guess": guess,
            "feedback": feedback, "next_player": self.active_player,
            "game_status": "ACTIVE"})
        for dead in failed:
            self.handle_disconnect(dead, "send failure")

    # ------------------------------------------------------------------
    # Disconnects, game end, cleanup
    # ------------------------------------------------------------------
    def handle_disconnect(self, conn, reason):
        """Single exit path for every disconnect; runs once per client."""
        with self.game_lock:            # RLock: safe if already held
            if conn.disconnected:
                return
            conn.disconnected = True
            log.info("%s disconnected: %s", conn.label, reason)

            # Not an assigned player (never joined, or from an old match).
            if conn.player_id is None \
                    or self.players.get(conn.player_id) is not conn:
                conn.close()
                return

            if self.state == WAITING_FOR_PLAYERS:
                del self.players[conn.player_id]     # release the slot
                conn.close()
                log.info("Slot released; lobby keeps waiting.")
            elif self.state in (GAME_START, PLAYER_TURN, EVALUATE_MOVE) \
                    and self.match_result is None:
                conn.close()
                other = self.players.get(next(
                    p for p in PLAYER_IDS if p != conn.player_id))
                if other is None or other.disconnected:
                    log.info("Both players gone; no winner.")
                    self._cleanup()
                else:
                    self._end_match(other.player_id, "FORFEIT")
            else:
                conn.close()

    def _end_match(self, winner, reason):
        """GAME_OVER: record the result once, notify players, clean up."""
        if self.match_result is not None:
            return
        self.match_result = {"winner": winner, "reason": reason}
        self._set_state(GAME_OVER)
        log.info("Match result: %s wins (%s)", winner, reason)
        # sendall() finishes before _cleanup() closes any socket.
        self._broadcast("GAME_OVER", {
            "winner": winner, "reason": reason,
            "hidden_word": self.hidden_word})
        self._cleanup()

    def _cleanup(self):
        """CLEANUP: close client sockets, reset state, keep listening."""
        self._set_state(CLEANUP)
        for conn in list(self.players.values()):
            conn.disconnected = True
            conn.buffer.clear()
            conn.close()
        self.players.clear()
        self.active_player = None
        self.current_turn = 0
        self.hidden_word = None
        self.match_result = None
        self._set_state(WAITING_FOR_PLAYERS)
        log.info("Cleanup complete; waiting for new players.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_state(self, new_state):
        """Change FSM state and log the transition (lock held)."""
        if new_state != self.state:
            log.info("FSM: %s -> %s", self.state, new_state)
        self.state = new_state

    def _broadcast(self, msg_type, payload):
        """Send to both players in a fixed order while game_lock is held.

        ``payload`` is a dict or a function of the player id. Returns the
        connections whose send failed so the caller can handle them.
        """
        failed = []
        for pid in PLAYER_IDS:
            conn = self.players.get(pid)
            if conn is None or conn.disconnected:
                continue
            body = payload(pid) if callable(payload) else payload
            if not conn.send(msg_type, body):
                failed.append(conn)
        return failed


def parse_args(argv=None):
    """Server CLI: -p <port> is required, -h prints help."""
    parser = argparse.ArgumentParser(
        description="Ward two-player word guessing game server.",
        epilog="Example: python3 server.py -p 8080")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        metavar="PORT",
                        help="TCP port to listen on (1024-65535); "
                             "binds to 0.0.0.0")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [SERVER] %(message)s",
                        datefmt="%H:%M:%S")
    server = WardServer("0.0.0.0", args.port)
    try:
        server.start()
    except OSError as exc:
        print(f"[ERROR] Could not listen on port {args.port}: {exc}")
        return 1
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
