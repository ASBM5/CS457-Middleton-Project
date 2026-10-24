# Ward: AI Prompting & Constraint Strategy

**Student:** Atlas Middleton  
**Course:** CS457  
**Date:** 10/24/2026

---

# Overview

The purpose of these prompts is to constrain AI coding tools so they generate code that strictly follows the protocol defined in `protocol_blueprint.md`, the state transitions defined in `fsm_specification.md`, and the threading and locking rules defined in `concurrency_design.md`.

The AI is instructed to use the exact message schemas, message types, framing rules, error handling requirements, and locking rules defined by the project documentation.

Generic socket code that invents new message formats, ignores the FSM, changes field names, or shares state between threads without `game_lock` is considered invalid.

---

# System Prompt

The following system prompt is used when requesting implementation help from an AI coding assistant.

```text
You are assisting with implementation of a TCP client-server game called Ward.

You must strictly follow the protocol specification defined in protocol_blueprint.md, the state machine defined in fsm_specification.md, and the concurrency rules defined in concurrency_design.md.

Do not invent new message types.

Do not rename any fields.

Do not modify payload structures.

Do not change framing rules.

Use only newline-delimited JSON (NDJSON) framing.

All messages must contain:

- msg_type
- player_id
- payload
- timestamp

Only the following message types are valid:

CONNECT
LOBBY_WAIT
GAME_START
MOVE
STATE_UPDATE
ERROR
DISCONNECT
GAME_OVER

Clients send only CONNECT, MOVE, and DISCONNECT.

Use the constants WORD_LENGTH, MAX_MESSAGE_BYTES, MAX_ALIAS_LENGTH, and IDLE_TIMEOUT_SECONDS with the values defined in protocol_blueprint.md.

All JSON messages must match the schemas defined in protocol_blueprint.md.

If a requested implementation conflicts with the protocol specification, follow the protocol specification.

The server is authoritative and clients must not determine game outcomes.

All game state transitions must match fsm_specification.md.

Use the player identifiers Player_1 and Player_2 exactly, and use SERVER as the player_id of server messages.
```

---

# Prompt: Message Serialization Functions

Used when generating code to send protocol messages.

```text
Generate Python serialization functions for Ward.

Requirements:

- Use JSON serialization.
- Use UTF-8 encoding.
- Use newline-delimited JSON framing.
- End every message with '\n'.
- Use exact protocol field names.
- Do not add extra fields.
- Support CONNECT, LOBBY_WAIT, GAME_START, MOVE, STATE_UPDATE, ERROR, DISCONNECT, and GAME_OVER messages.
- Ensure all messages contain msg_type, player_id, payload, and timestamp.
- timestamp is an integer Unix time in seconds.
- Use SERVER as the player_id of every server message.
- STATE_UPDATE game_status is ACTIVE or COMPLETE. next_player is null when game_status is COMPLETE.
- Output only the required Python implementation.
```

### Purpose

This prompt forces AI to generate serialization logic that matches the protocol blueprint exactly.

---

# Prompt: Message Parser

Used when generating code to receive and decode messages.

```text
Generate a Python message parser for Ward.

Requirements:

- Input is a TCP byte stream.
- Messages use newline-delimited JSON framing.
- Maintain a receive buffer.
- Process complete messages only after '\n' is received.
- Handle TCP fragmentation.
- Handle TCP coalescing.
- If the receive buffer exceeds MAX_MESSAGE_BYTES without a newline, report MESSAGE_TOO_LARGE.
- Parse only the message types defined in protocol_blueprint.md.
- Reject malformed JSON and invalid UTF-8.
- Reject invalid message schemas.
- Return ERROR messages for invalid protocol data.
- Do not invent additional protocol behavior.
```

### Purpose

This prompt ensures AI-generated parsing logic follows the protocol framing requirements instead of assuming a single recv() call contains one complete message.

---

# Prompt: Server FSM Implementation

Used when generating server-side game logic.

```text
Generate Python server-side FSM code for Ward.

Requirements:

- Use only the states defined in fsm_specification.md:

  INIT
  WAITING_FOR_PLAYERS
  GAME_START
  PLAYER_TURN
  EVALUATE_MOVE
  GAME_OVER
  CLEANUP

- Implement state transitions exactly as documented.
- Do not create additional game states.
- Process only the approved protocol messages.
- Invalid messages must generate ERROR responses.
- Out-of-turn MOVE messages must generate INVALID_TURN.
- A MOVE outside PLAYER_TURN must generate INVALID_PHASE.
- Player_1 always takes the first turn, and turn starts at 1.
- Increment the turn number after each valid guess that does not win.
- Compute GREEN, YELLOW, and RED feedback with the two-pass rule from protocol_blueprint.md: greens first, then yellows limited by remaining unmatched letters.
- Convert guesses to uppercase before evaluating them.
- Do not check guesses against a dictionary.
- A third CONNECT while two players are assigned must generate ERROR with code ROOM_FULL and close that connection.
- A CONNECT from an already-joined client must generate INVALID_PHASE.
- Disconnects must trigger forfeit logic.
- GAME_OVER must occur immediately after a correct guess.
- A correct guess sends a final STATE_UPDATE with game_status COMPLETE, then GAME_OVER.
- CLEANUP must close client sockets only, keep the listening socket open, reset resources, and prepare for future matches.
```

### Purpose

This prompt prevents AI from creating alternative game flows that violate the FSM design.

---

# Prompt: Concurrency and Thread Safety

Used when generating the threaded server code.

```text
Generate the Python threading code for the Ward server.

Requirements:

- Use threading.Thread with one worker thread per client connection.
- The main thread only calls accept() and starts worker threads.
- Do not use asyncio, selectors, or select.select.
- Use a single threading.RLock named game_lock.
- Protect all shared state with game_lock:
  the FSM state, active_player, current_turn, the hidden word,
  the connected client list and player assignments,
  match_result, and the per-player disconnected flags.
- recv(), receive-buffer handling, JSON parsing, and schema validation happen outside game_lock.
- State validation, state changes, and broadcasts happen inside one with game_lock: block.
- Broadcasts to both players must happen while game_lock is held, in the same order for both players.
- Set a socket timeout of IDLE_TIMEOUT_SECONDS on every client socket.
- Use a single handle_disconnect() routine for every disconnect path.
- handle_disconnect() must acquire game_lock and check the player's disconnected flag so each disconnect is handled once.
- Record match_result only once per match, inside game_lock.
- Send GAME_OVER completely before closing client sockets.
- Do not terminate the server process because of a client disconnect.
```

### Purpose

This prompt keeps AI-generated threading code consistent with `concurrency_design.md` and prevents race conditions, duplicate forfeits, and deadlocks.

---

# Prompt: Disconnect Handling

Used when generating networking code.

```text
Generate Python disconnect handling for Ward.

Requirements:

- Handle DISCONNECT messages.
- Detect recv() returning b"" as EOF.
- Treat EOF as a CLIENT_DISCONNECTED event.
- Catch:

  ConnectionResetError
  BrokenPipeError
  ConnectionAbortedError
  TimeoutError

- Treat a socket timeout (IDLE_TIMEOUT_SECONDS) as a disconnect.
- Treat a connection closed for MESSAGE_TOO_LARGE as a disconnect when the player is in an active match.
- Trigger forfeit logic when a disconnect occurs during an active match.
- Release player resources.
- Transition to GAME_OVER and CLEANUP according to fsm_specification.md.
- If both players disconnect before a winner exists, go to CLEANUP without sending GAME_OVER.
- Do not terminate the server process because of a client disconnect.
```

### Purpose

This prompt ensures AI-generated code follows the protocol's connection termination requirements and does not ignore network failures.

---

# Prompt: Input Validation

Used when generating validation logic.

```text
Generate validation functions for Ward.

Requirements:

- Validate message schemas.
- Validate that alias is a non-empty string of at most MAX_ALIAS_LENGTH characters.
- Validate player identity.
- Validate active-player turn ownership.
- Validate that the MOVE turn value matches the current turn.
- Validate word length against WORD_LENGTH.
- Validate alphabetic input only (A to Z, case-insensitive).

Check every message in exactly this order and return the first error that applies:

1. MESSAGE_TOO_LARGE
2. INVALID_MESSAGE
3. INVALID_PHASE
4. INVALID_PLAYER
5. INVALID_TURN
6. INVALID_GUESS

Checks 5 and 6 apply only to MOVE.

Generate the following protocol errors when appropriate:

INVALID_MESSAGE
INVALID_PLAYER
INVALID_GUESS
INVALID_TURN
INVALID_PHASE
MESSAGE_TOO_LARGE

Also generate ROOM_FULL, but only when a CONNECT arrives while two players are already assigned. It is a capacity error, not a message validation error.

Use only these error codes.
Do not invent additional error codes.
```

### Purpose

This prompt forces AI-generated validation logic to match the protocol blueprint and prevents inconsistent error handling.

---

# Prompt: Client Implementation

Used when generating the client program.

```text
Generate the Python client for Ward.

Requirements:

- Send only CONNECT, MOVE, and DISCONNECT messages.
- Reuse the same serialization functions and message parser as the server.
- Use newline-delimited JSON framing and handle fragmentation and coalescing.
- Send CONNECT first with an alias of 1 to MAX_ALIAS_LENGTH characters.
- Use the player_id from LOBBY_WAIT or GAME_START in every later message.
- Send MOVE only after the server indicates it is this player's turn, and include the current turn number.
- Display only server-provided state: feedback from STATE_UPDATE, the winner and reason from GAME_OVER, and the text from ERROR.
- Do not determine winners, turn order, or feedback on the client.
- Handle ERROR messages without crashing, including ROOM_FULL.
- Send DISCONNECT before closing the socket on an intentional quit.
- After GAME_OVER, close the connection. To play again, open a new connection and send CONNECT.
- Do not terminate with a traceback if the server closes the connection.
```

### Purpose

This prompt keeps the client from inventing protocol behavior or computing game state that belongs to the server.

---

# Verifying AI-Generated Code

AI output is not accepted until it passes these checks against the documents:

1. **Fragmentation:** send one `MOVE` split across two `send()` calls. The server must wait for the newline and process it once.
2. **Coalescing:** send `CONNECT` and `DISCONNECT` in one `send()`. The server must process both.
3. **Out-of-turn move:** send a `MOVE` from the non-active player. The server must return `ERROR(INVALID_TURN)` to that player only and not change state.
4. **Wrong phase:** send a `MOVE` before the game starts. The server must return `ERROR(INVALID_PHASE)`.
5. **Duplicate letters:** guess `APPLE` against `GRAPE`. The feedback must be `YELLOW, YELLOW, RED, RED, GREEN`.
6. **Simultaneous moves:** send moves from both players at the same moment. Exactly one must be accepted.
7. **Third client:** connect a third client. It must receive `ERROR(ROOM_FULL)` and be closed, and the match must continue.
8. **Mid-game disconnect:** close one client during a match. The other must receive `GAME_OVER` with `reason` `FORFEIT`, exactly once.
9. **`DISCONNECT` followed by EOF:** only one forfeit may occur.
10. **Oversized message:** send more than `MAX_MESSAGE_BYTES` with no newline. The server must report `MESSAGE_TOO_LARGE` and close the connection.
11. **After the game:** both clients must be closed, the server must still accept new connections, and a fresh `CONNECT` must be assigned `Player_1`.
12. **Naming:** all message types, field names, error codes, states, and player identifiers must match the documents exactly.

---

# Constraint Strategy Summary

The following rules are enforced in every AI interaction:

1. AI must follow `protocol_blueprint.md`.
2. AI must follow `fsm_specification.md`.
3. AI must follow `concurrency_design.md`.
4. AI may not create new message types.
5. AI may not rename fields.
6. AI may not alter payload structures.
7. AI must use newline-delimited JSON framing.
8. AI must use the documented error codes and the documented validation order.
9. AI must implement documented disconnect handling, including the idle timeout.
10. AI must preserve all FSM state transitions.
11. AI must use one `RLock` named `game_lock` for all shared state, with `recv()` and parsing outside the lock.
12. AI must use the documented feedback rule for repeated letters and uppercase guesses.
13. The server remains authoritative for all game state decisions.
14. AI output must pass the verification checks above before it is accepted.

These constraints ensure that AI-generated code remains consistent with the project's networking protocol, finite state machine, and concurrency design.
