# Ward: Protocol Blueprint

**Student:** Atlas Middleton  
**Course:** CS457  
**Date:** 10/24/2026

---

# 1. Game Overview

Ward (War-Word) is a two-player turn-based word guessing game. The server selects a hidden word of a predetermined length before the match begins. Players take turns attempting to guess the hidden word.

After each guess, the server evaluates every letter in the submitted word and returns feedback indicating whether each letter:

| Guess Feedback | Meaning |
| --- | --- |
| `GREEN` | Letter is present in the hidden word and is in the correct position. |
| `YELLOW` | Letter is present in the hidden word but is in an incorrect position. |
| `RED` | Letter is not present in the hidden word. |

## Example

```text
Hidden Word: GRAPE

Player Guess: GUARD
```

| G | U | A | R | D |
| --- | --- | --- | --- | --- |
| GREEN | RED | YELLOW | YELLOW | RED |

The player who correctly guesses the hidden word immediately wins the game.

Players alternate turns throughout the game. `Player_1` always takes the first turn. Only the active player may submit a guess during their turn.

A player wins by forfeit if the opponent disconnects or loses their connection during the game.

The game supports a maximum of two players. Additional connection attempts are rejected.

After a match ends, the server closes the client connections. Players must open a new connection and send `CONNECT` to play again.

---

# 2. Transport and Framing

Ward uses TCP to transmit JSON messages encoded in UTF-8. Messages use Newline-Delimited JSON (NDJSON) framing. Every JSON object is serialized into a single UTF-8 encoded line terminated by a newline character: `\n`

## Coalescing

Two messages arrive in one piece. A player connects then disconnects. The newlines allow messages to be processed independently.

```text
{"msg_type":"CONNECT","player_id":null,"payload":{"alias":"Atlas"},"timestamp":1790787600}\n{"msg_type":"DISCONNECT","player_id":null,"payload":{"reason":"QUIT"},"timestamp":1790787601}\n
```

## Fragmentation

A message is sent in two parts. The receiver waits for a newline and doesn't parse until it gets the full message.

```text
recv() #1:
{"msg_type":"MOVE","player_id":"Player_1","payload":{"turn":1,"guess":"GU

recv() #2:
ARD"},"timestamp":1790787610}\n
```

## Protocol Constants

| Constant | Value | Meaning |
| --- | --- | --- |
| `WORD_LENGTH` | `5` | Length of the hidden word and of every valid guess |
| `MAX_MESSAGE_BYTES` | `1024` | Maximum size of one message, including the trailing `\n` |
| `MAX_ALIAS_LENGTH` | `20` | Maximum length of `alias` |
| `IDLE_TIMEOUT_SECONDS` | `300` | A client that sends nothing for this long is treated as disconnected |

The server enforces `MAX_MESSAGE_BYTES` on the receive buffer. If the buffer grows past the limit without a newline arriving, the message is too large.

---

# 3. Shared Message Fields

Every protocol message contains the following required fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `msg_type` | String | Message type |
| `player_id` | String or null | Sender id |
| `payload` | Object | Message's info |
| `timestamp` | Integer | Unix time in seconds, used for logging only |

Unknown or missing fields, incorrect types, and other bad values are rejected with `INVALID_MESSAGE`.

Messages sent by the server use `"SERVER"` as `player_id`.

## Message Types

| Message Type | Direction | Purpose |
| --- | --- | --- |
| `CONNECT` | Client → Server | Request to join with an alias |
| `LOBBY_WAIT` | Server → Client | Assign `Player_1` and wait for an opponent |
| `GAME_START` | Server → Clients | Start game and assign turn order |
| `MOVE` | Client → Server | Submit a word guess |
| `STATE_UPDATE` | Server → Clients | Send feedback and updated game state |
| `ERROR` | Server → Client | Explain an action was rejected |
| `DISCONNECT` | Client → Server | Notify the server of an intentional quit |
| `GAME_OVER` | Server → Clients | Announce winner or forfeit |

Clients send only `CONNECT`, `MOVE`, and `DISCONNECT`. Any other `msg_type` received by the server is rejected with `INVALID_MESSAGE`.

---

# 4. Message Definitions

## CONNECT

**Direction:** Client → Server

**Purpose:** Request to join the game.

### Payload Fields

| Field | Type |
| --- | --- |
| `alias` | String |

`alias` is a display name used for server logging only. It is not sent to the opponent and does not affect the game. It must be a non-empty string of at most `MAX_ALIAS_LENGTH` characters. An invalid alias is rejected with `INVALID_MESSAGE`. Aliases do not need to be unique.

A `CONNECT` from a client that has already joined is rejected with `INVALID_PHASE`.

### Example

```json
{
  "msg_type": "CONNECT",
  "player_id": null,
  "payload": {
    "alias": "Atlas"
  },
  "timestamp": 1790787600
}
```

---

## LOBBY_WAIT

**Direction:** Server → Client

**Purpose:** Assign `Player_1` and wait for `Player_2`.

### Payload Fields

| Field | Type |
| --- | --- |
| `assigned_player_id` | String |
| `message` | String |

### Example

```json
{
  "msg_type": "LOBBY_WAIT",
  "player_id": "SERVER",
  "payload": {
    "assigned_player_id": "Player_1",
    "message": "Waiting for second player."
  },
  "timestamp": 1790787601
}
```

---

## GAME_START

**Direction:** Server → Both Clients

**Purpose:** Start the game and distribute the initial game state.

### Payload Fields

| Field | Type |
| --- | --- |
| `assigned_player_id` | String |
| `word_length` | Integer |
| `starting_player` | String |
| `turn` | Integer |

`starting_player` is always `Player_1`, and `turn` always starts at `1`.

### Example

```json
{
  "msg_type": "GAME_START",
  "player_id": "SERVER",
  "payload": {
    "assigned_player_id": "Player_1",
    "word_length": 5,
    "starting_player": "Player_1",
    "turn": 1
  },
  "timestamp": 1790787605
}
```

The second player receives the same information with their assigned player ID.

---

## MOVE

**Direction:** Client → Server

**Purpose:** Submit a word guess.

### Payload Fields

| Field | Type |
| --- | --- |
| `turn` | Integer |
| `guess` | String |

`turn` must equal the server's current turn number (see Section 5).

`guess` is case-insensitive. The server converts it to uppercase before evaluating it, and all guesses echoed back by the server are uppercase.

### Example

```json
{
  "msg_type": "MOVE",
  "player_id": "Player_1",
  "payload": {
    "turn": 1,
    "guess": "GUARD"
  },
  "timestamp": 1790787610
}
```

Only the active player may submit a `MOVE`.

---

## STATE_UPDATE

**Direction:** Server → Both Clients

**Purpose:** Provide guess evaluation and update the game state.

### Payload Fields

| Field | Type |
| --- | --- |
| `completed_turn` | Integer |
| `guess` | String |
| `feedback` | Array[String] |
| `next_player` | String or null |
| `game_status` | String |

### `game_status` Values

| Value | Meaning | `next_player` |
| --- | --- | --- |
| `ACTIVE` | The guess was wrong and the game continues. | The player whose turn is next |
| `COMPLETE` | The guess was correct and the game is over. A `GAME_OVER` message follows. | `null` |

### Example (Game Continues)

```json
{
  "msg_type": "STATE_UPDATE",
  "player_id": "SERVER",
  "payload": {
    "completed_turn": 1,
    "guess": "GUARD",
    "feedback": [
      "GREEN",
      "RED",
      "YELLOW",
      "YELLOW",
      "RED"
    ],
    "next_player": "Player_2",
    "game_status": "ACTIVE"
  },
  "timestamp": 1790787615
}
```

### Example (Correct Guess)

```json
{
  "msg_type": "STATE_UPDATE",
  "player_id": "SERVER",
  "payload": {
    "completed_turn": 2,
    "guess": "GRAPE",
    "feedback": [
      "GREEN",
      "GREEN",
      "GREEN",
      "GREEN",
      "GREEN"
    ],
    "next_player": null,
    "game_status": "COMPLETE"
  },
  "timestamp": 1790787624
}
```

Clients should update their displays using only server-provided state.

---

## ERROR

**Direction:** Server → Client

**Purpose:** Explain why a request was rejected.

### Payload Fields

| Field | Type |
| --- | --- |
| `code` | String |
| `message` | String |

### Example

```json
{
  "msg_type": "ERROR",
  "player_id": "SERVER",
  "payload": {
    "code": "INVALID_TURN",
    "message": "It is not your turn."
  },
  "timestamp": 1790787616
}
```

### Example (Room Full)

```json
{
  "msg_type": "ERROR",
  "player_id": "SERVER",
  "payload": {
    "code": "ROOM_FULL",
    "message": "Two players are already connected."
  },
  "timestamp": 1790787617
}
```

`ROOM_FULL` is an error code carried by an `ERROR` message. It is not a separate message type.

---

## DISCONNECT

**Direction:** Client → Server

**Purpose:** Notify the server of an intentional quit.

### Payload Fields

| Field | Type |
| --- | --- |
| `reason` | String |

### Example

```json
{
  "msg_type": "DISCONNECT",
  "player_id": "Player_1",
  "payload": {
    "reason": "QUIT"
  },
  "timestamp": 1790787620
}
```

Clients that disconnect before receiving a player ID use:

```json
{
  "player_id": null
}
```

---

## GAME_OVER

**Direction:** Server → Both Connected Clients

**Purpose:** Announce the final game result.

### Payload Fields

| Field | Type |
| --- | --- |
| `winner` | String |
| `reason` | String |
| `hidden_word` | String |

`winner` is always `Player_1` or `Player_2`. If both players disconnect before a winner exists, no `GAME_OVER` is sent because no client is left to receive it.

`reason` is `CORRECT_GUESS` or `FORFEIT`.

### Example (Correct Guess)

```json
{
  "msg_type": "GAME_OVER",
  "player_id": "SERVER",
  "payload": {
    "winner": "Player_1",
    "reason": "CORRECT_GUESS",
    "hidden_word": "GRAPE"
  },
  "timestamp": 1790787625
}
```

### Example (Forfeit)

```json
{
  "msg_type": "GAME_OVER",
  "player_id": "SERVER",
  "payload": {
    "winner": "Player_2",
    "reason": "FORFEIT",
    "hidden_word": "GRAPE"
  },
  "timestamp": 1790787625
}
```

---

# 5. Validation and Turn Handling

The server assigns available player slots in connection order.

The first client to send `CONNECT` is assigned:

```text
Player_1
```

and enters the lobby wait state until a second player joins. The second client to send `CONNECT` is assigned `Player_2`.

If a `CONNECT` arrives while two players are already assigned, the server sends `ERROR` with code `ROOM_FULL` and closes that connection. This applies in every server state. Only assigned players count toward the limit, so a connection that has not yet sent `CONNECT` does not use up a slot.

## Validation Order

The server checks every incoming message in this order and rejects it with the first error that applies. A rejected message never changes game state.

| Order | Check | Error Code |
| --- | --- | --- |
| 1 | Message size is within `MAX_MESSAGE_BYTES` | `MESSAGE_TOO_LARGE` |
| 2 | Valid UTF-8 and JSON, known `msg_type`, required fields present with correct types | `INVALID_MESSAGE` |
| 3 | Message is allowed in the current server state | `INVALID_PHASE` |
| 4 | `player_id` matches the connection and the player has joined | `INVALID_PLAYER` |
| 5 | Sender is the active player and `turn` matches the current turn | `INVALID_TURN` |
| 6 | Guess has `WORD_LENGTH` letters and contains only letters `A` to `Z` (case-insensitive) | `INVALID_GUESS` |

Checks 5 and 6 apply only to `MOVE`. A `MOVE` is allowed only in `PLAYER_TURN`, so a `MOVE` sent before `GAME_START`, or after `GAME_OVER`, receives `INVALID_PHASE`. A `MOVE` from the non-active player during `PLAYER_TURN` receives `INVALID_TURN`.

Guesses are not checked against a dictionary. Any string of `WORD_LENGTH` letters is a valid guess.

## Turn Numbering

The server keeps a turn counter that starts at `1` in `GAME_START`. A `MOVE` must carry the current value in its `turn` field. After each valid guess that does not win the game, the server increments the counter. A `STATE_UPDATE` reports the turn that was just played in `completed_turn`. A `MOVE` with the wrong `turn` value receives `INVALID_TURN`.

## Feedback Rules

Feedback has one entry per letter, in guess order. The server computes it in two passes so repeated letters are handled consistently:

1. **Greens:** mark every position where the guess letter equals the hidden word letter at that position as `GREEN`, and set those hidden letters aside.
2. **Yellows:** for each remaining guess letter, from left to right, mark it `YELLOW` if the same letter is still unused among the hidden word's remaining letters, and use that letter up. Otherwise mark it `RED`.

Example:

```text
Hidden Word: GRAPE

Player Guess: APPLE
```

| A | P | P | L | E |
| --- | --- | --- | --- | --- |
| YELLOW | YELLOW | RED | RED | GREEN |

The hidden word contains only one `P`, so the second `P` is `RED`.

## Turn Rules

Only the active player may submit a guess.

Out-of-turn guesses generate:

```text
INVALID_TURN
```

The server sends feedback after every valid guess and transfers control to the next player.

When a correct guess occurs:

1. The server records the winner.
2. The game ends immediately.
3. A final `STATE_UPDATE` with `game_status` `COMPLETE` is broadcast, followed by `GAME_OVER`.

## Error Codes

| Error Code | Meaning |
| --- | --- |
| `INVALID_MESSAGE` | Invalid JSON, missing fields, or malformed payload |
| `INVALID_PLAYER` | Unknown player or connection mismatch |
| `INVALID_GUESS` | Invalid word length or invalid characters |
| `INVALID_TURN` | Guess submitted out of turn, or `turn` value does not match |
| `INVALID_PHASE` | Message not allowed in the current state |
| `ROOM_FULL` | Maximum players already connected |
| `MESSAGE_TOO_LARGE` | Message exceeds `MAX_MESSAGE_BYTES` |

Ordinary protocol violations do not terminate the connection.

`ROOM_FULL` and `MESSAGE_TOO_LARGE` result in immediate connection closure. If the closed connection belongs to a player in an active match, the closure is handled as a disconnect (see Section 6).

---

# 6. Disconnects and Cleanup

## Intentional Quit

The client sends:

```text
DISCONNECT
```

before closing the socket.

The server awards a forfeit victory to the remaining player.

## Clean TCP Closure

TCP connection closure through the TCP FIN handshake is separate from the application-layer `DISCONNECT` message.

## EOF Detection

If:

```python
data = sock.recv(1024)
```

returns:

```python
b""
```

the remote peer has closed the connection.

Example:

```python
if not data:
    handle_disconnect(player_id)
```

The server must stop reading from the socket and begin disconnect handling.

## Unexpected Failures

The server catches:

```python
ConnectionResetError
BrokenPipeError
ConnectionAbortedError
TimeoutError
```

These conditions are treated as unexpected disconnects.

## Idle Timeout

Each client socket uses a receive timeout of `IDLE_TIMEOUT_SECONDS`. A client that sends nothing for that long raises `TimeoutError` and is treated as disconnected. The timeout is long enough that a player thinking about a guess is not disconnected.

## Disconnect During Lobby

If a player disconnects before the game begins:

- Their slot is released
- The remaining player stays in the lobby
- The server waits for a replacement player

## Disconnect During Match

If a player disconnects during an active game:

1. The opponent immediately wins by forfeit.
2. The server sends `GAME_OVER` with `reason` `FORFEIT`.
3. Match data is finalized.
4. Resources are released.

## Cleanup

During cleanup the server:

- Closes all client sockets (the listening socket stays open)
- Clears receive buffers
- Removes stored game data
- Clears turn history
- Resets lobby state

The server sends `GAME_OVER` completely (for example with `sendall()`) before it closes the client sockets, so the final message is not lost.

Disconnect events are processed only once.

After cleanup the server becomes available for a new match. Players must open new connections and send `CONNECT` again.

---

# 7. Concurrency

The server handles each client in its own thread. See `concurrency_design.md` for the threading model, the `game_lock` locking rules, and the message flow diagram.
