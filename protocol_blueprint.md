# Ward: Protocol Blueprint

**Student:** Atlas Middleton
**Course:** CS457
**Date:** 10/4/2026

## 1. Game Overview

Ward (War-Word) is a two-player turn-based word guessing game. The server selects a hidden word of a predetermined length before the match begins. Players take turns attempting to guess the hidden word.

After each guess, the server evaluates every letter in the submitted word and returns feedback indicating whether each letter:

| Guess Feedback | Meaning |
| --- | --- |
|`GREEN`| Letter is present in the hidden word, and is in the correct position. |
|`YELLOW`| Letter is present in the hidden word, but is in an incorrect position. |
|`RED`| Letter is not present in the hidden word. |

**Example:**
```text
Hidden Word: GRAPE

Player 1 Guess: GUARD

Example
Hidden Word: GRAPE

Player Guess: GUARD
| G     | U   | A      | R      | D   |
| Green | Red | Yellow | Yellow | Red |
```

The player who correctly guesses the hidden word immediately wins the game.

Players alternate turns throughout the game. Only the active player may submit a guess during their turn.

A player wins by forfeit if the opponent disconnects or loses their connection during the game.

The game supports a maximum of two players. Additional connection attempts are rejected.

2. Transport and Framing

Ward uses TCP to transmit JSON messages encoded in UTF-8.

Messages use Newline-Delimited JSON (NDJSON) framing (Option A). Every JSON object is serialized into a single UTF-8 encoded line terminated by a newline character:

\n


(byte value 0x0A).

Framing Rule

The receiver maintains a byte buffer for each connection.

When bytes arrive:

Incoming bytes are appended to the buffer.
The receiver checks for the newline delimiter.
Each complete newline-terminated message is extracted.
The JSON is parsed and validated.
Remaining partial data stays in the buffer until additional bytes arrive.

This framing mechanism correctly handles:

TCP fragmentation
TCP coalescing
Multiple messages arriving in a single recv()
Single messages arriving in multiple recv() calls
Maximum Message Size

Each message may contain a maximum of:

16,384 bytes


including the newline delimiter.

Messages exceeding this size generate an ERROR response when possible and the connection is closed.

Wire Examples

In all examples below, \n represents an actual newline byte.

Example 1: Coalescing

Two messages arrive in a single receive call.

{"msg_type":"CONNECT","player_id":null,"payload":{"alias":"Atlas"},"timestamp":1790787600}\n{"msg_type":"DISCONNECT","player_id":null,"payload":{"reason":"QUIT"},"timestamp":1790787601}\n


The receiver identifies both messages using the newline delimiters.

Example 2: Fragmentation

A single message arrives in two pieces.

recv() #1:
{"msg_type":"MOVE","player_id":"Player_1","payload":{"turn":1,"guess":"GU

recv() #2:
ARD"},"timestamp":1790787610}\n


After the first receive operation, no newline exists so the receiver waits for additional data.

After the second receive operation, the newline is present and the complete JSON message is processed.

3. Shared Message Fields

Every protocol message contains the following required fields.

Field	Type	Meaningmsg_type	String	Protocol message type.
player_id	String or null	Sender identifier.
payload	Object	Message-specific information.
timestamp	Integer	Unix timestamp used for logging.
Player Identifiers
Value	MeaningPlayer_1	First connected player
Player_2	Second connected player
SERVER	Message originated from the server
null	Client has not yet received an assigned player ID

All fields are mandatory.

Unknown fields, missing fields, incorrect data types, and malformed values are rejected.

Player aliases must:

Be non-empty strings
Be unique within the match
Contain only alphanumeric characters and underscores
Message Summary
Message Type	Direction	PurposeCONNECT	Client → Server	Request to join with an alias
LOBBY_WAIT	Server → Client	Assign Player 1 and wait for opponent
GAME_START	Server → Clients	Start game and assign turn order
MOVE	Client → Server	Submit a word guess
STATE_UPDATE	Server → Clients	Send feedback and updated game state
ERROR	Server → Client	Explain why message/action was rejected
DISCONNECT	Client → Server	Notify server of intentional quit
GAME_OVER	Server → Clients	Announce winner or forfeit
4. Message Definitions
CONNECT

Direction: Client → Server

Purpose: Request to join the game.

Payload
alias (string)
Example
{
  "msg_type":"CONNECT",
  "player_id":null,
  "payload":{
    "alias":"Atlas"
  },
  "timestamp":1790787600
}

LOBBY_WAIT

Direction: Server → Waiting Client

Purpose: Assign Player 1 and wait for Player 2.

Payload
assigned_player_id (string)
message (string)
Example
{
  "msg_type":"LOBBY_WAIT",
  "player_id":"SERVER",
  "payload":{
    "assigned_player_id":"Player_1",
    "message":"Waiting for second player."
  },
  "timestamp":1790787601
}

GAME_START

Direction: Server → Both Clients

Purpose: Start the game and distribute initial game state.

Payload
assigned_player_id (string)
word_length (integer)
starting_player (string)
turn (integer)
Example
{
  "msg_type":"GAME_START",
  "player_id":"SERVER",
  "payload":{
    "assigned_player_id":"Player_1",
    "word_length":5,
    "starting_player":"Player_1",
    "turn":1
  },
  "timestamp":1790787605
}


The second player receives the same information with their assigned player ID.

MOVE

Direction: Client → Server

Purpose: Submit a word guess.

Payload
turn (integer)
guess (string)
Example
{
  "msg_type":"MOVE",
  "player_id":"Player_1",
  "payload":{
    "turn":1,
    "guess":"GUARD"
  },
  "timestamp":1790787610
}


Only the active player may submit a MOVE.

STATE_UPDATE

Direction: Server → Both Clients

Purpose: Provide guess evaluation and update game state.

Payload
completed_turn (integer)
guess (string)
feedback (array of strings)
next_player (string)
game_status (string)
Example
{
  "msg_type":"STATE_UPDATE",
  "player_id":"SERVER",
  "payload":{
    "completed_turn":1,
    "guess":"GUARD",
    "feedback":[
      "GREEN",
      "RED",
      "YELLOW",
      "YELLOW",
      "RED"
    ],
    "next_player":"Player_2",
    "game_status":"ACTIVE"
  },
  "timestamp":1790787615
}


Clients should update their displays using only server-provided state.

ERROR

Direction: Server → Client

Purpose: Explain why a request was rejected.

Payload
code (string)
message (string)
Example
{
  "msg_type":"ERROR",
  "player_id":"SERVER",
  "payload":{
    "code":"INVALID_TURN",
    "message":"It is not your turn."
  },
  "timestamp":1790787616
}

DISCONNECT

Direction: Client → Server

Purpose: Notify server of an intentional quit.

Payload
reason (string)
Example
{
  "msg_type":"DISCONNECT",
  "player_id":"Player_1",
  "payload":{
    "reason":"QUIT"
  },
  "timestamp":1790787620
}


Clients that disconnect before receiving a player ID use:

"player_id": null

GAME_OVER

Direction: Server → Both Connected Clients

Purpose: Announce final game result.

Payload
winner (string or null)
reason (string)
hidden_word (string)
Example (Correct Guess)
{
  "msg_type":"GAME_OVER",
  "player_id":"SERVER",
  "payload":{
    "winner":"Player_1",
    "reason":"CORRECT_GUESS",
    "hidden_word":"GRAPE"
  },
  "timestamp":1790787625
}

Example (Forfeit)
{
  "msg_type":"GAME_OVER",
  "player_id":"SERVER",
  "payload":{
    "winner":"Player_2",
    "reason":"FORFEIT",
    "hidden_word":"GRAPE"
  },
  "timestamp":1790787625
}

5. Validation and Turn Handling

The server assigns available player slots in connection order.

The first player is assigned:

Player_1


and enters the lobby wait state until a second player joins.

A third connection attempt receives:

ROOM_FULL


and is disconnected.

MOVE Validation

The server verifies:

Player is connected
Player ID matches the connection
Guess occurs during the active turn
Guess length matches the configured word length
Guess contains only alphabetic characters
Message schema is valid

Invalid requests generate an ERROR response and do not change game state.

Turn Rules

Only the active player may submit a guess.

Out-of-turn guesses generate:

INVALID_TURN


The server sends feedback after every valid guess and transfers control to the next player.

When a correct guess occurs:

The server records the winner.
The game ends immediately.
A GAME_OVER message is broadcast.
Error Codes
Error Code	MeaningINVALID_MESSAGE	Invalid JSON, missing fields, malformed payload
INVALID_PLAYER	Unknown player or connection mismatch
INVALID_GUESS	Invalid word length or invalid characters
INVALID_TURN	Guess submitted out of turn
INVALID_PHASE	Message not allowed in current state
ROOM_FULL	Maximum players already connected
MESSAGE_TOO_LARGE	Message exceeds maximum size

Ordinary protocol violations do not terminate the connection.

ROOM_FULL and MESSAGE_TOO_LARGE may result in immediate connection closure.

6. Disconnects and Cleanup
Intentional Quit

The client sends:

DISCONNECT


before closing the socket.

The server awards a forfeit win to the remaining player.

Clean TCP Closure

TCP connection closure through the TCP FIN handshake is separate from the application-layer DISCONNECT message.

EOF Detection

If:

data = sock.recv(1024)


returns:

b""


the remote peer has closed the connection.

Example:

if not data:
    handle_disconnect(player_id)


The server must stop reading from the socket and begin disconnect handling.

Unexpected Failures

The server catches:

ConnectionResetError
BrokenPipeError
ConnectionAbortedError
TimeoutError


These conditions are treated as unexpected disconnects.

Disconnect During Lobby

If a player disconnects before the game begins:

Their slot is released
Remaining player stays in lobby
Server waits for a replacement player
Disconnect During Match

If a player disconnects during an active game:

Opponent immediately wins by forfeit.
Server sends GAME_OVER.
Match data is finalized.
Resources are released.
Cleanup

During cleanup the server:

Closes all sockets
Clears receive buffers
Removes stored game data
Clears turn history
Resets lobby state

Disconnect events are processed only once.

After cleanup the server becomes available for a new match.

7. Remaining Game Decisions

The following gameplay values will be finalized during implementation:

hidden word source and dictionary
Allowed word lengths
Maximum number of turns before draw
Turn timeout duration
Case sensitivity rules
Dictionary validation requirements
Replay/rematch functionality
Word selection methodology (randomized or predefined)