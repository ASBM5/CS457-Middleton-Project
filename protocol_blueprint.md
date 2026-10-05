# Ward: Protocol Blueprint

**Student:** Atlas Middleton  
**Course:** CS457  
**Date:** 10/4/2026

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

Players alternate turns throughout the game. Only the active player may submit a guess during their turn.

A player wins by forfeit if the opponent disconnects or loses their connection during the game.

The game supports a maximum of two players. Additional connection attempts are rejected.

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

---

# 3. Shared Message Fields

Every protocol message contains the following required fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `msg_type` | String | Message type |
| `player_id` | String or null | Sender id |
| `payload` | Object | Message's info |
| `timestamp` | Integer | Timestamp for logging |

Unknown or missing fields, incorrect types, and other bad values are rejected.

## Message Types

| Message Type | Direction | Purpose |
| --- | --- | --- |
| `CONNECT` | Client → Server | Request to join with an alias |
| `LOBBY_WAIT` | Server → Client | Assign Player 1 and wait for an opponent |
| `GAME_START` | Server → Clients | Start game and assign turn order |
| `MOVE` | Client → Server | Submit a word guess |
| `STATE_UPDATE` | Server → Clients | Send feedback and updated game state |
| `ERROR` | Server → Client | Explain an action was rejected |
| `DISCONNECT` | Client → Server | Notify the server of an intentional quit |
| `GAME_OVER` | Server → Clients | Announce winner or forfeit |

---

# 4. Message Definitions

## CONNECT

**Direction:** Client → Server

**Purpose:** Request to join the game.

### Payload Fields

| Field | Type |
| --- | --- |
| `alias` | String |

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

**Purpose:** Assign Player 1 and wait for Player 2.

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
| `next_player` | String |
| `game_status` | String |

### Example

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
| `winner` | String or null |
| `reason` | String |
| `hidden_word` | String |

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

The first player is assigned:

```text
Player_1
```

and enters the lobby wait state until a second player joins.

A third connection attempt receives:

```text
ROOM_FULL
```

and is disconnected.

## MOVE Validation

The server verifies:

- Player is connected
- Player ID matches the connection
- Guess occurs during the active turn
- Guess length matches the configured word length
- Guess contains only alphabetic characters
- Message schema is valid

Invalid requests generate an `ERROR` response and do not change the game state.

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
3. A `GAME_OVER` message is broadcast.

## Error Codes

| Error Code | Meaning |
| --- | --- |
| `INVALID_MESSAGE` | Invalid JSON, missing fields, or malformed payload |
| `INVALID_PLAYER` | Unknown player or connection mismatch |
| `INVALID_GUESS` | Invalid word length or invalid characters |
| `INVALID_TURN` | Guess submitted out of turn |
| `INVALID_PHASE` | Message not allowed in the current state |
| `ROOM_FULL` | Maximum players already connected |
| `MESSAGE_TOO_LARGE` | Message exceeds maximum size |

Ordinary protocol violations do not terminate the connection.

`ROOM_FULL` and `MESSAGE_TOO_LARGE` may result in immediate connection closure.

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

## Disconnect During Lobby

If a player disconnects before the game begins:

- Their slot is released
- The remaining player stays in the lobby
- The server waits for a replacement player

## Disconnect During Match

If a player disconnects during an active game:

1. The opponent immediately wins by forfeit.
2. The server sends `GAME_OVER`.
3. Match data is finalized.
4. Resources are released.

## Cleanup

During cleanup the server:

- Closes all sockets
- Clears receive buffers
- Removes stored game data
- Clears turn history
- Resets lobby state

Disconnect events are processed only once.

After cleanup the server becomes available for a new match.