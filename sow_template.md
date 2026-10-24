# CS 457 Project Statement of Work (SOW) & Protocol Specification Template

**Student Name:** Atlas  
**Date:** 2026-9-20 
**Course:** CS 457 - Computer Networks  
**Target Server Domain:** `server.middleton.edu`  

---

## 1. Game Selection & Scope (Sprint 0)

> - The game will be a word guessing game (think Wordle), where players take turns guessing a secret word of a certain length. 
> - Whichever player starts the game/connects first will be the first to take a guess, and then the second player will guess. 
> - There will be blank spaces "_ _ _ _ _" that denote how long a word is, whatever player is first can type in a word and then
> - the game will tell the player which letters are either in the word, in the correct spot, or if they're not used.
> - EX. "G U A R D"
> -     "green red yellow yellow red" 
> - Green means the right letter in the right spot, yellow means the right letter in the wrong spot, and red means the letter is not in the word. And then the next player will have a turn. 
> - Whoever guesses the word first wins. 
> - There aren't any tie mechanics, as players are taking turns and wouldn't be able to guess at the same time. 

### 1.1 Game Overview
- **Chosen Game:** Ward (Wordle)
- **Player Capacity:** 2 Players
- **Game Summary:** A Word guessing game where players take turns guessing a secret word. First one to guess correctly wins.

### 1.2 Core Game Rules & Win/Draw Conditions
- **Turn Mechanics:** Whichever player starts the game or connects first will take the first turn. After that each player takes turns guessing the word.
- **Victory Condition:** Whoever guesses the secret word first wins.
- **Draw/Tie Condition:** There are no draws. The game continues until a player guesses the word. If a player quits, loses their connection, or sits idle past the timeout (5 minutes), the other player wins by forfeit.

---

## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable)

### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** JSON, encoded as UTF-8. Every message has the fields `msg_type`, `player_id`, `payload`, and `timestamp`.
- **Framing Mechanism:** Newline-delimited JSON (NDJSON). Each message is one line ending in `\n`, at most 1024 bytes. The receiver buffers incoming bytes and parses only after a newline arrives, which handles TCP fragmentation and coalescing. See `protocol_blueprint.md` for the full schemas.

### 2.2 Message Schema Definitions

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game with an alias.
2. `LOBBY_WAIT` (Server -> Client): Assigns `Player_1` and notifies the client that the server is waiting for `Player_2`.
3. `GAME_START` (Server -> Clients): Game initiated. Assigns each client its `Player_1` or `Player_2` identifier and gives the word length, starting player (`Player_1`), and turn number.
4. `MOVE` (Client -> Server): Submit a word guess for the current turn.
5. `STATE_UPDATE` (Server -> Clients): Broadcast the feedback (`GREEN`, `YELLOW`, `RED`) for the guess, the next active player, and the game status (`ACTIVE` or `COMPLETE`).
6. `ERROR` (Server -> Client): Rejected request, with a code such as `INVALID_TURN` or `ROOM_FULL`.
7. `DISCONNECT` (Client -> Server): Notifies the server of an intentional quit. The opponent wins by forfeit.
8. `GAME_OVER` (Server -> Clients): Announces the winner (`Player_1` or `Player_2`), the reason (`CORRECT_GUESS` or `FORFEIT`), and the hidden word.

#### Example JSON Protocol Schema:
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

---

### 2.3 Game State Machine (FSM) Design (Sprint 1 Deliverable)
- **State Transitions:** `INIT` -> `WAITING_FOR_PLAYERS` -> `GAME_START` -> `PLAYER_TURN` -> `EVALUATE_MOVE` -> `GAME_OVER` -> `CLEANUP` -> `WAITING_FOR_PLAYERS`.
  - Win checking happens inside `EVALUATE_MOVE`: a wrong guess returns to `PLAYER_TURN` with the other player active, and a correct guess moves to `GAME_OVER`.
  - Invalid or out-of-turn moves send an `ERROR` and stay in `PLAYER_TURN`.
  - A disconnect during `GAME_START` or `PLAYER_TURN` awards a forfeit victory to the remaining player and moves to `GAME_OVER`. A disconnect in `WAITING_FOR_PLAYERS` just releases the player's slot.
  - After `CLEANUP`, players must open a new connection and send `CONNECT` to play again.
  - See `fsm_specification.md` for the full state diagram and transition table.

---

## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

Full details are in `concurrency_design.md`, which also contains the Mermaid sequence diagram showing every protocol message.

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** Multi-Threading (`threading.Thread`). The main thread only calls `accept()`, and each connected client gets its own worker thread for the life of the match. A slow or silent client never blocks the main loop or the other player. Threading was chosen over `selectors` because Ward has only two players, and a blocking `recv()` loop per client keeps the newline-delimited JSON (NDJSON) receive buffer simple.
- **Synchronization Logic:** All shared state is protected by a single `threading.RLock` named `game_lock`. The shared state is the FSM state, `active_player`, `current_turn`, the hidden word, the connected client list and player assignments, `match_result`, and the per-player `disconnected` flags.
  - `recv()`, receive-buffer handling, and message parsing happen outside the lock.
  - Validation, state changes, and broadcasts happen together inside one `with game_lock:` block, so only one worker thread can change game state at a time.
  - Player assignment and the `ROOM_FULL` check also run under the lock, so two simultaneous `CONNECT` messages cannot both become `Player_1`.
  - Every disconnect goes through one `handle_disconnect()` routine that checks a per-player flag under the lock, so a `DISCONNECT` followed by EOF causes only one forfeit.
  - A reentrant lock is used so a disconnect detected during a broadcast does not deadlock.
  - Sockets use a timeout (`IDLE_TIMEOUT_SECONDS`) so a send inside the lock cannot block forever.

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:** The server validates every `MOVE` inside `game_lock`, in this order: server phase (`INVALID_PHASE`), that `player_id` matches the connection (`INVALID_PLAYER`), that the sender is the active player and the `turn` value matches the current turn (`INVALID_TURN`), and that the guess has the right length and only letters (`INVALID_GUESS`). A rejected move sends an `ERROR` to the sender only and leaves game state unchanged, so an out-of-turn move can never corrupt turn ownership. After a valid but incorrect guess, the server switches the active player and sends a `STATE_UPDATE` with `next_player` to both clients.
- **Score & Board Synchronization:** Ward has no board and no points system, so the "score" of a match is its result: the winner and the reason (`CORRECT_GUESS` or `FORFEIT`). The server stores this as `match_result` in memory, written once under `game_lock`. Each `STATE_UPDATE` carries the guess feedback (`GREEN`, `YELLOW`, `RED`) and is sent to both players while the lock is held, so both see updates in the same order. When the match ends, the server sends a final `STATE_UPDATE` with `game_status` `COMPLETE`, then `GAME_OVER` (`winner`, `reason`, `hidden_word`) to every connected player. Clients only display server-provided state. After `GAME_OVER` the server runs `CLEANUP`, and players must open a new connection and send `CONNECT` to play again.

---

## 4. Coding & AI Implementation Plan (Sprint 3)

- **Permitted AI Tools:** [e.g., GitHub Copilot, ChatGPT, Claude]
- **AI Prompting & Constraint Strategy:** Explain how you will constrain AI models to generate code (in Python or your chosen language) that adheres strictly to the protocol blueprint and FSM designed in Sprints 1 & 2.
- **Implementation Risk Management:** Detail your plan to leverage past programming experience and manage time to ensure code completion on schedule.

---

## 5. CML Multi-Subnet Topology & Wireshark Deployment Plan (Sprint 4 & 5 Deliverable)

> For now you can use the topology below. We may update this when we get to defining subnets.

### 5.1 Subnet & Router Design
- **Subnet A (Client 1):** `192.168.10.0/24` (Interface `Gi0/1` on Router R1)
- **Subnet B (Client 2):** `192.168.11.0/24` (Interface `Gi0/2` on Router R1)
- **Subnet C (Game Server):** `192.168.20.0/24` (Interface `Gi0/1` on Router R2)
- **Router Backbone:** `10.0.0.0/30` (Interface `Gi0/0` on R1 <-> `Gi0/0` on R2)

### 5.2 DHCP Pools & DNS Configuration Plan
- **Router R1 DHCP Pool 1 (`CLIENT1_POOL`):** Leases `192.168.10.10` - `192.168.10.50`, gateway `192.168.10.1`, DNS `10.0.0.2`.
- **Router R1 DHCP Pool 2 (`CLIENT2_POOL`):** Leases `192.168.11.10` - `192.168.11.50`, gateway `192.168.11.1`, DNS `10.0.0.2`.
- **Router R2 Authoritative DNS:** Configured with `ip dns server` and static host mapping `server.[yourlastname].edu` -> `192.168.20.100`.

### 5.3 Deployment Strategy & Wireshark Trace Capture
- **CML Deployment Strategy:** Deploy `server.py` onto Subnet C node (`192.168.20.100`) behind Router R2, and `client.py` onto Subnet A and Subnet B nodes behind Router R1.
- **Cisco Infrastructure Configuration:** Router R1 DHCP pools (`CLIENT1_POOL`, `CLIENT2_POOL`) and Router R2 authoritative DNS (`ip host server.[lastname].edu 192.168.20.100`).
- **Wireshark Trace Capture Plan:** Capture DHCP DORA exchange (`dhcp_negotiation.pcap`) and DNS query/response resolution (`dns_lookup.pcap`).
