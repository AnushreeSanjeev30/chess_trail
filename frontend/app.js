const statusEl = document.getElementById("status");
const boardEl = document.getElementById("board");
const movesListEl = document.getElementById("moves-list");
const playersListEl = document.getElementById("players-list");

const storedUser = window.localStorage.getItem("chessUser");
let currentUser = null;

if (storedUser) {
  try {
    currentUser = JSON.parse(storedUser);
  } catch (e) {
    currentUser = null;
  }
}

if (!currentUser) {
  window.location.href = "login.html";
}

let selectedSquare = null;
let draggedSource = null;
let currentFen = null;
let myColor = null; // 'w', 'b', or 'spectator'
let gameOver = false;

console.log("App starting...");

const urlParams = new URLSearchParams(window.location.search);
const roomId = urlParams.get("room") || "room1";

const preferredColor = window.localStorage.getItem("preferredColor") || "any";
const userIdParam = encodeURIComponent(currentUser.user_id);
const usernameParam = encodeURIComponent(currentUser.username);

const ws = new WebSocket(
  `ws://127.0.0.1:8000/ws/${roomId}?user_id=${userIdParam}&username=${usernameParam}&preferred=${encodeURIComponent(preferredColor)}`
);

console.log("WebSocket created, waiting for connection...");

const pieces = {
  // black pieces
  p: "\u265F", // pawn
  n: "\u265E", // knight
  b: "\u265D", // bishop
  r: "\u265C", // rook
  q: "\u265B", // queen
  k: "\u265A", // king
  // white pieces
  P: "\u2659", // pawn
  N: "\u2658", // knight
  B: "\u2657", // bishop
  R: "\u2656", // rook
  Q: "\u2655", // queen
  K: "\u2654"  // king
};

function parseRank(rankStr) {
  const row = [];
  for (const ch of rankStr) {
    if (/\d/.test(ch)) {
      const empty = parseInt(ch, 10);
      for (let i = 0; i < empty; i += 1) {
        row.push(null);
      }
    } else {
      row.push(ch);
    }
  }
  return row;
}

function renderBoardFromFen(fen) {
  if (!fen) {
    return;
  }

  boardEl.innerHTML = '';

  const piecePlacement = fen.split(' ')[0];
  const ranks = piecePlacement.split('/');

  const isBlackView = myColor === 'b';

  // rankVisual/fileVisual = indices for how we draw on screen
  for (let rankVisual = 0; rankVisual < 8; rankVisual += 1) {
    const rankDiv = document.createElement('div');
    rankDiv.className = 'rank';

    const rankIdx = isBlackView ? 7 - rankVisual : rankVisual; // logical rank index
    const rowPieces = parseRank(ranks[rankIdx]);

    for (let fileVisual = 0; fileVisual < 8; fileVisual += 1) {
      const fileDiv = document.createElement('div');
      fileDiv.className = 'file';
      // Use visual indices for color pattern; 180° rotation keeps pattern
      fileDiv.classList.add((rankVisual + fileVisual) % 2 === 0 ? 'light' : 'dark');

      const fileIdx = isBlackView ? 7 - fileVisual : fileVisual; // logical file index

      const fileChar = String.fromCharCode('a'.charCodeAt(0) + fileIdx);
      const rankNum = 8 - rankIdx;
      const square = `${fileChar}${rankNum}`;
      fileDiv.dataset.square = square;

      const pieceChar = rowPieces[fileIdx];
      if (pieceChar) {
        fileDiv.textContent = pieces[pieceChar];

        const isWhitePiece = pieceChar === pieceChar.toUpperCase();
        fileDiv.classList.add(isWhitePiece ? 'piece-white' : 'piece-black');
      }

      fileDiv.addEventListener('click', () => handleSquareClick(square));
      fileDiv.addEventListener('dragstart', (e) => handleDragStart(e, square, pieceChar));
      fileDiv.addEventListener('dragover', (e) => e.preventDefault());
      fileDiv.addEventListener('drop', (e) => handleDrop(e, square));

      rankDiv.appendChild(fileDiv);
    }

    boardEl.appendChild(rankDiv);
  }
}

function handleSquareClick(square) {
  if (ws.readyState !== WebSocket.OPEN) {
    alert('Not connected to server yet');
    return;
  }

  if (gameOver) {
    alert('Game is over. Start a new game to play again.');
    return;
  }

  if (!canMoveNow()) {
    return;
  }

  if (!selectedSquare) {
    selectedSquare = square;
    return;
  }

  const source = selectedSquare;
  const target = square;
  selectedSquare = null;

  sendMove(source, target);
}

function handleDragStart(e, square, pieceChar) {
  if (!pieceChar) {
    e.preventDefault();
    return;
  }

  if (ws.readyState !== WebSocket.OPEN) {
    e.preventDefault();
    return;
  }

  if (gameOver) {
    e.preventDefault();
    return;
  }

  if (!canMoveNow()) {
    e.preventDefault();
    return;
  }

  draggedSource = square;
  e.dataTransfer.effectAllowed = 'move';
}

function handleDrop(e, target) {
  e.preventDefault();

  if (!draggedSource) {
    return;
  }

  const source = draggedSource;
  draggedSource = null;

  sendMove(source, target);
}

function sendMove(source, target) {
  const move = `${source}${target}`;
  console.log('Sending move:', move);

  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'move', move }));
  } else {
    alert('WebSocket is not connected');
  }
}

function logMoveToList(uciMove, fenAfterMove) {
  if (!movesListEl || !uciMove || !fenAfterMove) {
    return;
  }

  const parts = fenAfterMove.split(' ');
  const active = parts[1];
  const fullMoveNum = parseInt(parts[5] || '1', 10);

  const mover = active === 'w' ? 'Black' : 'White';

  const li = document.createElement('li');
  li.textContent = `${fullMoveNum}. ${mover}: ${uciMove}`;
  movesListEl.appendChild(li);

  // keep the latest move visible
  movesListEl.scrollTop = movesListEl.scrollHeight;
}

const API_BASE = "http://127.0.0.1:8000";

async function refreshOnlinePlayers() {
  if (!playersListEl || !currentUser) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/online-users`);
    if (!res.ok) {
      return;
    }
    const data = await res.json();

    playersListEl.innerHTML = "";

    data.forEach((player) => {
      if (player.user_id === currentUser.user_id) {
        return;
      }

      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.textContent = player.username;

      const btn = document.createElement("button");
      btn.textContent = "Play";
      btn.addEventListener("click", () => {
        const a = Math.min(currentUser.user_id, player.user_id);
        const b = Math.max(currentUser.user_id, player.user_id);
        const targetRoom = `room_${a}_${b}`;
        window.location.href = `index.html?room=${encodeURIComponent(targetRoom)}`;
      });

      li.appendChild(nameSpan);
      li.appendChild(btn);
      playersListEl.appendChild(li);
    });
  } catch (err) {
    console.error("Failed to load online users", err);
  }
}

function canMoveNow() {
  if (!currentFen) {
    return false;
  }

  if (myColor !== 'w' && myColor !== 'b') {
    alert('You are a spectator and cannot move pieces.');
    return false;
  }

  const parts = currentFen.split(' ');
  const sideToMove = parts[1]; // 'w' or 'b'

  if (sideToMove !== myColor) {
    alert('Wait for your turn.');
    return false;
  }

  return true;
}

ws.onopen = () => {
  console.log('WebSocket connected');
  statusEl.innerText = 'Connected, waiting for board...';
};

ws.onmessage = (event) => {
  console.log('Message received:', event.data);
  const data = JSON.parse(event.data);

  if (data.type === 'state') {
    currentFen = data.fen;

    // Record assigned color once (server sends it with each state)
    if (data.color && !myColor) {
      myColor = data.color;
    }

    renderBoardFromFen(currentFen);

    if (data.last_move) {
      logMoveToList(data.last_move, currentFen);
    }

    if (data.game_over) {
      gameOver = true;

      let resultText = 'Game over';
      if (data.result === 'white') {
        resultText = 'Game over · White wins';
      } else if (data.result === 'black') {
        resultText = 'Game over · Black wins';
      } else if (data.result === 'draw') {
        resultText = 'Game over · Draw';
      }

      if (data.reason) {
        resultText += ` (${data.reason.replace(/_/g, ' ')})`;
      }

      statusEl.innerText = resultText;
      return;
    }

    const parts = currentFen.split(' ');
    const turnColor = parts[1] === 'w' ? 'White' : 'Black';

    let youText = '';
    if (myColor === 'w') {
      youText = 'You are White · ';
    } else if (myColor === 'b') {
      youText = 'You are Black · ';
    } else if (myColor === 'spectator') {
      youText = 'Spectator · ';
    }

    statusEl.innerText = `${youText}${turnColor} to move`;
  } else if (data.type === 'error') {
    alert(data.message);
  }
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
  statusEl.innerText = 'Error: WebSocket connection failed';
};

ws.onclose = () => {
  console.log('WebSocket closed');
  statusEl.innerText = 'Disconnected from server';
};

// Periodically refresh the list of online players
setInterval(refreshOnlinePlayers, 5000);
refreshOnlinePlayers();

