from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chess
import sqlite3
from pathlib import Path
from datetime import datetime
import hashlib
import os
import base64
import hmac

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).with_name("chess.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 1200,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    white_id INTEGER,
                    black_id INTEGER,
                    result TEXT NOT NULL,
                    reason TEXT,
                    moves TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    FOREIGN KEY (white_id) REFERENCES users(id),
                    FOREIGN KEY (black_id) REFERENCES users(id)
                )
                """
            )
    finally:
        conn.close()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return (
        base64.b64encode(salt).decode("ascii")
        + "$"
        + base64.b64encode(digest).decode("ascii")
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False

    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(hash_b64)
    digest = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return hmac.compare_digest(digest, expected)


init_db()


games = {}        # room_id -> chess.Board
connections = {}  # room_id -> list of websockets
players = {}      # room_id -> { websocket: "w" | "b" | "spectator" }
ws_user_ids = {}  # websocket -> user_id (optional)
ws_usernames = {}  # websocket -> username (optional)

# room metadata used for recording completed games
room_meta = {}  # room_id -> { "white_id", "black_id", "moves" (list[str]), "created_at", "finished" }


class SignupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user_id: int
    username: str


@app.get("/")
async def read_root():
    return {"message": "Chess API is running"}


@app.get("/online-users")
async def online_users():
    # Unique set of users that currently have an open websocket
    by_user_id: dict[int, str] = {}
    for ws, uid in ws_user_ids.items():
        if uid is None:
            continue
        username = ws_usernames.get(ws)
        if username is None:
            continue
        by_user_id[uid] = username

    return [
        {"user_id": user_id, "username": username}
        for user_id, username in by_user_id.items()
    ]


@app.post("/signup")
async def signup(payload: SignupRequest):
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(payload.password), datetime.utcnow().isoformat()),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already taken")
    finally:
        conn.close()

    return {"message": "User created"}


@app.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    username = payload.username.strip()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return LoginResponse(user_id=row["id"], username=username)


def _update_ratings_and_stats(
    conn: sqlite3.Connection,
    white_id: int,
    black_id: int,
    result: str,
) -> None:
    cur = conn.execute(
        "SELECT id, rating, wins, losses, draws FROM users WHERE id IN (?, ?)",
        (white_id, black_id),
    )
    rows = {row["id"]: row for row in cur.fetchall()}
    if white_id not in rows or black_id not in rows:
        return

    white = rows[white_id]
    black = rows[black_id]

    rw = int(white["rating"])
    rb = int(black["rating"])
    k = 32

    # Expected scores
    exp_w = 1.0 / (1.0 + pow(10.0, (rb - rw) / 400.0))
    exp_b = 1.0 / (1.0 + pow(10.0, (rw - rb) / 400.0))

    if result == "white":
        sw, sb = 1.0, 0.0
        wins_w, wins_b = 1, 0
        losses_w, losses_b = 0, 1
        draws_delta = 0
    elif result == "black":
        sw, sb = 0.0, 1.0
        wins_w, wins_b = 0, 1
        losses_w, losses_b = 1, 0
        draws_delta = 0
    else:  # draw
        sw, sb = 0.5, 0.5
        wins_w = wins_b = 0
        losses_w = losses_b = 0
        draws_delta = 1

    new_rw = max(100, round(rw + k * (sw - exp_w)))
    new_rb = max(100, round(rb + k * (sb - exp_b)))

    conn.execute(
        """
        UPDATE users
        SET rating = ?, wins = wins + ?, losses = losses + ?, draws = draws + ?
        WHERE id = ?
        """,
        (new_rw, wins_w, losses_w, draws_delta, white_id),
    )
    conn.execute(
        """
        UPDATE users
        SET rating = ?, wins = wins + ?, losses = losses + ?, draws = draws + ?
        WHERE id = ?
        """,
        (new_rb, wins_b, losses_b, draws_delta, black_id),
    )


def record_completed_game(room_id: str, result: str, reason: str | None) -> None:
    meta = room_meta.get(room_id)
    if not meta or meta.get("finished"):
        return

    white_id = meta.get("white_id")
    black_id = meta.get("black_id")
    if not white_id or not black_id:
        # Without both players we don't record ratings, but we still mark finished
        meta["finished"] = True
        return

    moves_text = " ".join(meta.get("moves", []))
    now_iso = datetime.utcnow().isoformat()

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO games (room_id, white_id, black_id, result, reason, moves, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room_id,
                    white_id,
                    black_id,
                    result,
                    reason,
                    moves_text,
                    meta.get("created_at", now_iso),
                    now_iso,
                ),
            )

            _update_ratings_and_stats(conn, white_id, black_id, result)
    finally:
        conn.close()

    meta["finished"] = True


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    print(f"WebSocket connection attempt for room {room_id}")
    await websocket.accept()
    print(f"WebSocket connection accepted for room {room_id}")

    # Optional: associate a logged-in user with this websocket (for stats/online list)
    user_id_param = websocket.query_params.get("user_id")
    if user_id_param is not None:
        try:
            ws_user_ids[websocket] = int(user_id_param)
        except ValueError:
            ws_user_ids[websocket] = None

    username_param = websocket.query_params.get("username")
    if username_param is not None:
        ws_usernames[websocket] = username_param

    if room_id not in games:
        games[room_id] = chess.Board()
        connections[room_id] = []
        players[room_id] = {}
        room_meta[room_id] = {
            "white_id": None,
            "black_id": None,
            "moves": [],
            "created_at": datetime.utcnow().isoformat(),
            "finished": False,
        }

    board = games[room_id]
    connections[room_id].append(websocket)

    # Assign a color to this connection (first: white, second: black, others: spectator)
    existing_colors = set(players[room_id].values())

    preferred = websocket.query_params.get("preferred", "any")

    def pick_color() -> str:
        nonlocal preferred

        if preferred == "w" and "w" not in existing_colors:
            return "w"
        if preferred == "b" and "b" not in existing_colors:
            return "b"
        # Fallback to automatic assignment
        if "w" not in existing_colors:
            return "w"
        if "b" not in existing_colors:
            return "b"
        return "spectator"

    assigned_color = pick_color()

    players[room_id][websocket] = assigned_color

    # Remember which users played which color in this room
    meta = room_meta.get(room_id)
    user_id = ws_user_ids.get(websocket)
    if meta is not None and user_id is not None:
        if assigned_color == "w" and meta.get("white_id") is None:
            meta["white_id"] = user_id
        elif assigned_color == "b" and meta.get("black_id") is None:
            meta["black_id"] = user_id

    print(
        f"Total connections in {room_id}: {len(connections[room_id])}, "
        f"assigned color: {assigned_color}"
    )

    # Send initial board state to this connection, including its assigned color
    await websocket.send_json(
        {
            "type": "state",
            "fen": board.fen(),
            "color": assigned_color,
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            print(f"Received data: {data}")

            if data["type"] == "move":
                # Enforce player color and turn
                player_color = players[room_id].get(websocket)

                if player_color not in ("w", "b"):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Spectators cannot make moves",
                        }
                    )
                    continue

                side_to_move = "w" if board.turn == chess.WHITE else "b"
                if player_color != side_to_move:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "It is not your turn",
                        }
                    )
                    continue

                move = chess.Move.from_uci(data["move"])

                if move in board.legal_moves:
                    board.push(move)

                    last_move_uci = move.uci()

                    # Track moves for later storage
                    meta = room_meta.get(room_id)
                    if meta is not None:
                        meta.setdefault("moves", []).append(last_move_uci)

                    # Determine game-over state after the move
                    game_over = board.is_game_over()
                    result = None
                    reason = None

                    if game_over:
                        if board.is_checkmate():
                            # After push, board.turn is the side that LOST
                            loser = "w" if board.turn == chess.WHITE else "b"
                            winner = "b" if loser == "w" else "w"
                            result = "white" if winner == "w" else "black"
                            reason = "checkmate"
                        elif board.is_stalemate():
                            result = "draw"
                            reason = "stalemate"
                        elif board.is_insufficient_material():
                            result = "draw"
                            reason = "insufficient_material"
                        elif board.can_claim_threefold_repetition():
                            result = "draw"
                            reason = "threefold_repetition"
                        elif board.can_claim_fifty_moves():
                            result = "draw"
                            reason = "fifty_move_rule"
                        else:
                            result = "draw"
                            reason = "draw"

                        # Persist completed game and update ratings/stats
                        record_completed_game(room_id, result, reason)

                    # Broadcast updated board to all players, including
                    # each player's assigned color in their own message
                    for conn in connections[room_id]:
                        color = players[room_id].get(conn, "spectator")
                        payload = {
                            "type": "state",
                            "fen": board.fen(),
                            "color": color,
                            "last_move": last_move_uci,
                        }

                        if game_over:
                            payload["game_over"] = True
                            payload["result"] = result
                            payload["reason"] = reason

                        await conn.send_json(payload)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid move"
                    })

    except WebSocketDisconnect:
        print(f"WebSocket disconnected from room {room_id}")
        connections[room_id].remove(websocket)
        if room_id in players:
            players[room_id].pop(websocket, None)
        ws_user_ids.pop(websocket, None)
        ws_usernames.pop(websocket, None)
