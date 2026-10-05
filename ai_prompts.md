# Ward: AI Prompting & Constraint Strategy

**Student:** Atlas Middleton  
**Course:** CS457  
**Date:** 10/4/2026

---

# Overview

The purpose of these prompts is to constrain AI coding tools so they generate code that strictly follows the protocol defined in `protocol_blueprint.md` and the state transitions defined in `fsm_specification.md`.

The AI is instructed to use the exact message schemas, message types, framing rules, and error handling requirements defined by the project documentation.

Generic socket code that invents new message formats, ignores the FSM, or changes field names is considered invalid.

---

# System Prompt

The following system prompt is used when requesting implementation help from an AI coding assistant.

```text
You are assisting with implementation of a TCP client-server game called Ward.

You must strictly follow the protocol specification defined in protocol_blueprint.md and the state machine defined in fsm_specification.md.

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

All JSON messages must match the schemas defined in protocol_blueprint.md.

If a requested implementation conflicts with the protocol specification, follow the protocol specification.

The server is authoritative and clients must not determine game outcomes.

All game state transitions must match fsm_specification.md.
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
- Parse only the message types defined in protocol_blueprint.md.
- Reject malformed JSON.
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
- Disconnects must trigger forfeit logic.
- GAME_OVER must occur immediately after a correct guess.
- CLEANUP must reset resources and prepare for future matches.
```

### Purpose

This prompt prevents AI from creating alternative game flows that violate the FSM design.

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

- Trigger forfeit logic when a disconnect occurs during an active match.
- Release player resources.
- Transition to GAME_OVER and CLEANUP according to fsm_specification.md.
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
- Validate player identity.
- Validate active-player turn ownership.
- Validate word length.
- Validate alphabetic input only.

Generate the following protocol errors when appropriate:

INVALID_MESSAGE
INVALID_PLAYER
INVALID_GUESS
INVALID_TURN
INVALID_PHASE
ROOM_FULL
MESSAGE_TOO_LARGE

Use only these error codes.
Do not invent additional error codes.
```

### Purpose

This prompt forces AI-generated validation logic to match the protocol blueprint and prevents inconsistent error handling.

---

# Constraint Strategy Summary

The following rules are enforced in every AI interaction:

1. AI must follow `protocol_blueprint.md`.
2. AI must follow `fsm_specification.md`.
3. AI may not create new message types.
4. AI may not rename fields.
5. AI may not alter payload structures.
6. AI must use newline-delimited JSON framing.
7. AI must use the documented error codes.
8. AI must implement documented disconnect handling.
9. AI must preserve all FSM state transitions.
10. The server remains authoritative for all game state decisions.

These constraints ensure that AI-generated code remains consistent with the project's networking protocol and finite state machine design.