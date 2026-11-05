// The board renderer, ported from the demo's renderBoard (CLAUDE.md §11).
// It draws a position from a FEN: the API sends the FEN for every move, so there's no
// move logic here and no chess library.
//
// Squares are numbered 0..63: a1 = 0, b1 = 1, ... h8 = 63.

const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
const NAME = { k: "king", q: "queen", r: "rook", b: "bishop", n: "knight", p: "pawn" };
const TEXT_STYLE = "︎"; // draw the glyph as text, never as an emoji
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
 * opts.label   text for screen readers when the board isn't interactive
 */
export function renderBoard(el, fen, orient, opts = {}) {
  const board = fenToBoard(fen);
  const hl = opts.hl || {}, arrows = opts.arrows || [], click = opts.onClick;
  el.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "squares";
  if (!click && opts.label) { grid.setAttribute("role", "img"); grid.setAttribute("aria-label", opts.label); }
  const order = [];
  for (let r = 7; r >= 0; r--) for (let f = 0; f < 8; f++) order.push(r * 8 + f);
  if (orient === "black") order.reverse();
  order.forEach((i, pos) => {
    const f = i % 8, r = Math.floor(i / 8), piece = board[i];
    const sq = document.createElement(click ? "button" : "div");
    sq.className = "sq " + ((f + r) % 2 === 0 ? "d" : "l") + (hl[i] ? " hl-" + hl[i] : "");
    if (click) {
      sq.type = "button";
      sq.setAttribute("aria-label", squareLabel(board, i));
      sq.addEventListener("click", () => click(i));
    }
    if (piece) {
      const s = document.createElement("span");
      s.className = "pc " + (isWhite(piece) ? "w" : "b");
      s.textContent = GLYPH[piece.toLowerCase()] + TEXT_STYLE;
      s.setAttribute("aria-hidden", "true");
      sq.appendChild(s);
    }
    if (pos % 8 === 0) sq.appendChild(coord("r", String(r + 1)));
    if (pos >= 56) sq.appendChild(coord("f", "abcdefgh"[f]));
    grid.appendChild(sq);
  });
  el.appendChild(grid);
  if (arrows.length) el.appendChild(drawArrows(arrows, orient));
}

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
