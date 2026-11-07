// The board renderer, ported from the demo's renderBoard (CLAUDE.md §11).
// It draws a position from a FEN: the API sends the FEN for every move, so there's no
// move logic here and no chess library. Drawing the next position into the same board
// slides the pieces there.
//
// Squares are numbered 0..63: a1 = 0, b1 = 1, ... h8 = 63.

const NAME = { k: "king", q: "queen", r: "rook", b: "bishop", n: "knight", p: "pawn" };
const SVG = "http://www.w3.org/2000/svg";
const ARROW = { red: "rgba(184,50,39,.85)", green: "rgba(29,122,82,.9)" };

/** "e4" -> 28 */
export const sqIdx = (name) => (name.charCodeAt(0) - 97) + (Number(name[1]) - 1) * 8;
/** 28 -> "e4" */
export const sqName = (i) => String.fromCharCode(97 + (i % 8)) + (Math.floor(i / 8) + 1);
/** "c3d5" -> [18, 35] */
export const uciSquares = (uci) => [sqIdx(uci.slice(0, 2)), sqIdx(uci.slice(2, 4))];

const isWhite = (piece) => piece === piece.toUpperCase();

/** The pieces of a FEN as 64 entries: "P", "k", ... or null. */
export function fenToBoard(fen) {
  const board = new Array(64).fill(null);
  fen.split(" ")[0].split("/").forEach((row, ri) => {
    let file = 0;
    const rank = 7 - ri;
    for (const ch of row) {
      if (/\d/.test(ch)) file += Number(ch);
      else { board[rank * 8 + file] = ch; file++; }
    }
  });
  return board;
}

/** "e4 white pawn", "d5 empty" */
export function squareLabel(board, i) {
  const piece = board[i];
  if (!piece) return sqName(i) + " empty";
  return sqName(i) + " " + (isWhite(piece) ? "white " : "black ") + NAME[piece.toLowerCase()];
}

/**
 * Draw `fen` into `el`, from `orient`'s side ("white" or "black").
 *
 * opts.hl      {square: "played" | "best" | "sel" | "ok" | "bad"} highlights
 * opts.arrows  [{from, to, color: "red" | "green"}]
 * opts.onClick (square) => ...; squares become buttons labelled like "e4 white pawn"
 * opts.targets squares the selected piece can go to: a dot, or a ring around a capture
 * opts.label   text for screen readers when the board isn't interactive
 *
 * Drawing into the same element again updates it in place: the squares stay (so a focused
 * square keeps focus), and pieces slide from where they were to where they are now.
 */
export function renderBoard(el, fen, orient, opts = {}) {
  const board = fenToBoard(fen);
  const hl = opts.hl || {}, arrows = opts.arrows || [], click = opts.onClick;
  const targets = new Set(click ? opts.targets || [] : []);
  let st = el._board;
  const fresh = !st || st.orient !== orient || !el.contains(st.layer);
  if (fresh) {
    el.replaceChildren();
    const layer = document.createElement("div");
    layer.className = "pieces";
    layer.setAttribute("aria-hidden", "true");
    el.appendChild(layer);
    st = el._board = { orient, mode: "", grid: null, squares: [], layer, pieces: [], arrows: null, click: null };
  }
  st.click = click;
  const mode = click ? "button" : "div";
  if (st.mode !== mode) buildSquares(el, st, mode);

  st.squares.forEach((sq, i) => {
    const f = i % 8, r = Math.floor(i / 8);
    let cls = "sq " + ((f + r) % 2 === 0 ? "d" : "l");
    if (hl[i]) cls += " hl-" + hl[i];
    if (targets.has(i)) cls += board[i] ? " tg cap" : " tg";
    sq.className = cls;
    if (click) sq.setAttribute("aria-label", squareLabel(board, i) + (targets.has(i) ? ", you can move here" : ""));
  });
  if (click || !opts.label) {
    st.grid.removeAttribute("role");
    st.grid.removeAttribute("aria-label");
  } else {
    st.grid.setAttribute("role", "img");
    st.grid.setAttribute("aria-label", opts.label);
  }

  const animate = !fresh && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const moved = placePieces(st, board, animate);

  if (st.arrows) st.arrows.remove();
  st.arrows = null;
  if (arrows.length) {
    st.arrows = drawArrows(arrows, orient);
    // After a move, the arrows come in once the pieces have arrived.
    if (moved) st.arrows.classList.add("late");
    el.appendChild(st.arrows);
  }
}

/** The 64 squares, as buttons (interactive) or plain boxes, with their coordinates. */
function buildSquares(el, st, mode) {
  const grid = document.createElement("div");
  grid.className = "squares";
  const squares = new Array(64);
  const order = [];
  for (let r = 7; r >= 0; r--) for (let f = 0; f < 8; f++) order.push(r * 8 + f);
  if (st.orient === "black") order.reverse();
  order.forEach((i, pos) => {
    const sq = document.createElement(mode);
    if (mode === "button") {
      sq.type = "button";
      sq.addEventListener("click", () => st.click && st.click(i));
    }
    if (pos % 8 === 0) sq.appendChild(coord("r", String(Math.floor(i / 8) + 1)));
    if (pos >= 56) sq.appendChild(coord("f", "abcdefgh"[i % 8]));
    squares[i] = sq;
    grid.appendChild(sq);
  });
  if (st.grid) st.grid.replaceWith(grid);
  else el.insertBefore(grid, st.layer);
  st.grid = grid;
  st.squares = squares;
  st.mode = mode;
}

// ---------------------------------------------------------------- pieces

const SLIDE_MS = 180; // keep in step with .pieces .pc in app.css

/** A pawn and the piece it promotes to (or back again, stepping backwards). */
function promotes(a, from, b, to) {
  if (isWhite(a) !== isWhite(b)) return false;
  const pa = a.toLowerCase() === "p", pb = b.toLowerCase() === "p";
  if (pa === pb) return false;
  const [pawnSq, otherSq] = pa ? [from, to] : [to, from];
  const lastRank = isWhite(a) ? 7 : 0;
  return Math.floor(otherSq / 8) === lastRank
    && Math.abs(Math.floor(otherSq / 8) - Math.floor(pawnSq / 8)) === 1
    && Math.abs((otherSq % 8) - (pawnSq % 8)) <= 1;
}

const distance = (a, b) => Math.hypot((a % 8) - (b % 8), Math.floor(a / 8) - Math.floor(b / 8));

/**
 * Move the piece images to `board`. Pieces that stayed put stay; each new square takes the
 * nearest piece of the same kind that left its square (so a move, castling or a jump of
 * several moves slides), a promotion takes its pawn, captured pieces fade out and anything
 * left over fades in. Returns whether a piece slid.
 */
function placePieces(st, board, animate) {
  const keep = [], leaving = [], arriving = [];
  const held = new Set();
  for (const p of st.pieces) {
    if (board[p.sq] === p.piece && !held.has(p.sq)) { keep.push(p); held.add(p.sq); }
    else leaving.push(p);
  }
  for (let i = 0; i < 64; i++) if (board[i] && !held.has(i)) arriving.push(i);

  const pairs = [];
  for (const to of arriving) {
    for (const p of leaving) {
      if (p.piece === board[to]) pairs.push([distance(p.sq, to), p, to]);
      else if (promotes(p.piece, p.sq, board[to], to)) pairs.push([100 + distance(p.sq, to), p, to]);
    }
  }
  pairs.sort((a, b) => a[0] - b[0]);
  const used = new Set(), filled = new Set();
  let moved = false;
  for (const [, p, to] of pairs) {
    if (used.has(p) || filled.has(to)) continue;
    used.add(p);
    filled.add(to);
    moved = true;
    p.sq = to;
    if (animate) {
      p.el.classList.add("moving");
      clearTimeout(p.timer);
      p.timer = setTimeout(() => p.el.classList.remove("moving"), SLIDE_MS);
    }
    position(p.el, to, st.orient);
    if (p.piece !== board[to]) {
      p.piece = board[to];
      // A promotion turns into the new piece once it has arrived.
      if (animate) setTimeout(() => { p.el.src = pieceUrl(p.piece); }, SLIDE_MS);
      else p.el.src = pieceUrl(p.piece);
    }
    keep.push(p);
  }

  for (const p of leaving) {
    if (used.has(p)) continue;
    clearTimeout(p.timer);
    if (animate) {
      p.el.classList.add("gone");
      setTimeout(() => p.el.remove(), SLIDE_MS);
    } else {
      p.el.remove();
    }
  }
  for (const to of arriving) {
    if (filled.has(to)) continue;
    const img = document.createElement("img");
    img.className = "pc" + (animate ? " enter" : "");
    img.src = pieceUrl(board[to]);
    img.alt = ""; // the square's label (or the board's) says what's there
    img.draggable = false;
    position(img, to, st.orient);
    st.layer.appendChild(img);
    keep.push({ el: img, piece: board[to], sq: to, timer: 0 });
  }
  st.pieces = keep;
  return moved && animate;
}

/** Put a piece image on square `i`; the stylesheet's transition makes it slide. */
function position(img, i, orient) {
  let f = i % 8, r = Math.floor(i / 8);
  if (orient === "black") { f = 7 - f; r = 7 - r; }
  img.style.transform = `translate(${f * 100}%, ${(7 - r) * 100}%)`;
}

/** "N" -> "/pieces/wN.svg", "p" -> "/pieces/bP.svg" (drawn by the server). */
export const pieceUrl = (piece) => `/pieces/${isWhite(piece) ? "w" : "b"}${piece.toUpperCase()}.svg`;

function coord(kind, text) {
  const c = document.createElement("span");
  c.className = "coord " + kind;
  c.textContent = text;
  c.setAttribute("aria-hidden", "true");
  return c;
}

function drawArrows(arrows, orient) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 8 8");
  svg.setAttribute("class", "arrows");
  svg.setAttribute("aria-hidden", "true");
  const xy = (i) => {
    let f = i % 8, r = Math.floor(i / 8);
    if (orient === "black") { f = 7 - f; r = 7 - r; }
    return [f + 0.5, 7 - r + 0.5];
  };
  for (const a of arrows) {
    const col = ARROW[a.color] || ARROW.red;
    const [x1, y1] = xy(a.from), [x2, y2] = xy(a.to);
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len, px = -uy, py = ux;
    const tx = x2 - ux * 0.12, ty = y2 - uy * 0.12, bx = tx - ux * 0.42, by = ty - uy * 0.42;
    const line = document.createElementNS(SVG, "line");
    line.setAttribute("x1", x1 + ux * 0.08); line.setAttribute("y1", y1 + uy * 0.08);
    line.setAttribute("x2", bx); line.setAttribute("y2", by);
    line.setAttribute("stroke", col); line.setAttribute("stroke-width", "0.17"); line.setAttribute("stroke-linecap", "round");
    const head = document.createElementNS(SVG, "polygon");
    head.setAttribute("points", [tx, ty, bx + px * 0.24, by + py * 0.24, bx - px * 0.24, by - py * 0.24].map((n) => n.toFixed(3)).join(" "));
    head.setAttribute("fill", col);
    svg.appendChild(line);
    svg.appendChild(head);
  }
  return svg;
}
