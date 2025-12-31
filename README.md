# Real-Time Multiplayer Chess

A real-time, browser-based multiplayer chess app built with **FastAPI**, **WebSockets**, and a lightweight vanilla JavaScript frontend. Players can create accounts, pick preferred colors, challenge active users, and have their games and ratings tracked in an SQLite database.

## Features

- Real-time chess over WebSockets using `python-chess` for rules and validation
- Automatic color assignment **or** user-selected preferred color (White / Black / Auto)
- Online player list with one-click "Play" challenge into a shared room
- Turn enforcement and server-side legality checks
- Game-over detection (checkmate, stalemate, draws) with clear UI messaging
- SQLite-backed user system:
  - Signup / login (hashed passwords)
  - Rating (simple Elo), wins, losses, draws updated after each finished game
  - Games table storing result, reason, move list, and players
- Dark, cinematic UI with board + move log + active player list

## Requirements

- Python 3.10+ recommended
- Pip packages (install in your preferred virtualenv):

```powershell
pip install fastapi "uvicorn[standard]" python-chess
```

SQLite is included with Python; the database file `chess.db` is created automatically in the `backend` folder on first run.

## Project structure

```text
backend/
  main.py        # FastAPI app, WebSocket server, auth, ratings, game storage
frontend/
  index.html     # Main board UI
  login.html     # Login / signup + preferred color selector
  app.js         # WebSocket client, board rendering, move log, matchmaking
  style.css      # Global styles and background image
  image/back.jpg # Background image
```

## Running the app (local dev)

Open two PowerShell terminals: one for the backend, one for the frontend.

### 1. Start the backend API + WebSocket server

```powershell
cd C:\Users\Anushree\Desktop\coder_X\chess_trial\backend
python -m uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000` and WebSockets at `ws://127.0.0.1:8000/ws/{room_id}`.

### 2. Start the frontend static server

```powershell
cd C:\Users\Anushree\Desktop\coder_X\chess_trial\frontend
python -m http.server 8001
```

Open the app in your browser:

- Login / signup page: `http://localhost:8001/login.html`

On first run, `backend/chess.db` will be created and the `users` / `games` tables initialized.

## Playing a game

1. **Create or log into an account**
   - Go to `http://localhost:8001/login.html`.
   - Choose **Login** or switch to **Sign up**.
   - Optionally select your **preferred color** (Auto / White / Black).
   - On successful login you are redirected to `index.html`.

2. **Join the main board**
   - `index.html` loads the board and connects a WebSocket using your saved user ID and preferred color.
   - Status text at the bottom shows your side and whose turn it is.

3. **Challenge another player**
   - In the right-hand sidebar, under **Active players**, you see a list of currently online users.
   - Click **Play** next to someone to jump into a shared room. The room ID is deterministic based on both user IDs, so if they also click **Play** on you, you’ll meet in the same game.

4. **Make moves**
   - Click a piece’s square, then its destination square (or drag & drop).
   - The server validates moves with `python-chess`, enforces turns, and broadcasts the new board to both players.
   - The **Moves** list on the right shows all moves in UCI format (`e2e4`, `e7e5`, ...).

5. **Game over & stats**
   - When checkmate or a draw condition occurs, the server:
     - Marks the game as over and sends a `game_over` message with result + reason.
     - Records the game in the `games` table with full move list and players.
     - Updates both players’ ratings and win/loss/draw counters in `users`.
   - The UI shows a message like `Game over · White wins (checkmate)` and prevents further moves.

## Notes & tips

- To reset all accounts and games, stop the backend, delete `backend/chess.db`, and restart `uvicorn`.
- Room selection is URL-based: `index.html?room=room_1_5` will connect both users 1 and 5 into that specific room.
- The online player list is based on active WebSocket connections; closing the game tab or losing connection will remove a user from the list within a few seconds.

## Next steps / ideas

- Add a profile page showing rating history and recent games.
- Support multiple concurrent games per user and friend lists.
- Add time controls and clocks.
- Deploy the backend to a cloud host (Render, Fly.io, etc.) and serve the frontend from static hosting.
