// Reading mode (ROADMAP 19.3): the note's tree, drawn with DOM calls (every text from the
// note goes in as textContent), and the board beside it that follows you. Click a move, in
// a game or in a sentence, and the board shows it; ← → go on in the line you're in, a
// variation included. A diagram or a Log link puts its own position on the board.
//
// Under the board (19.4): Copy FEN, Copy PGN up to here, Continue here (play on from the
// position shown, then copy your line or put it into the game as a variation) and Analyse
// (Stockfish, only when you press it).
//
// The server worked out every position (blunderbook_journal/doc.py): no chess logic here.

import { api } from "/js/api.js";
import { renderBoard, sqIdx, uciSquares } from "/js/board.js";
import { fmtDate, fmtEval, markPill, markText, outcome, statusPill, timeControl } from "/js/format.js";
import { bindSteps, stepsHtml } from "/js/steps.js";
import { toast } from "/js/ui.js";
import { player } from "./play.js";

const BOARD = "/api/ext/journal/board";
const ANALYSE = "/api/ext/journal/analyse";
const NOTES = "/api/ext/journal/notes";

// Lichess's colour letters ([%cal Gc3d5]) as the board's arrows and highlights.
const ARROWS = { R: "red", G: "green", B: "blue", Y: "amber" };
const SQUARES = { R: "bad", G: "ok", B: "sel", Y: "sel" };

let tree = null;
let byId = new Map(); // move id -> move
let refs = new Map(); // "log:12" -> the Log's answer
let startInfo = new Map(); // start -> {where, orient, arrows, squares}
let firstFrom = new Map(); // start -> the first move played from it
let gameOf = new Map(); // move id -> the name of the PGN block it's written in
let blockOf = new Map(); // move id -> the index of the PGN block it's written in
let startBlock = new Map(); // a PGN block's start -> its block index
let text = null; // the element the note is drawn in
let onTag = () => {};
let onChanged = () => {};
let noteId = null;

let line = []; // the positions the board steps through: [{fen, label, key, arrows, hl}]
let at = 0;
let natural = "white"; // the side the board faces for what's on it
let flipped = false;
let steps = null;
let lit = []; // the elements marked as on the board
let explorer = null; // "Continue here": {base, play} while you play on from a position
let analysis = null; // the last answer from Analyse, for the position it was asked about
let analysing = false;
let analysisError = null; // {fen, message} when Analyse didn't work
let bodyEl = null;
let panelEl = null;
let hooksRef = null;

const $ = (id) => document.getElementById(id);

function el(tag, cls, content) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (content !== undefined) node.textContent = content;
  return node;
}

function button(cls, content, act) {
  const b = el("button", cls, content);
  b.type = "button";
  b.addEventListener("click", act);
  return b;
}

/** Draw `note` into `body`, and its board into `panel`. Returns whether there's anything
 *  to put on a board (no chess and no Log links: no board). */
export function open(body, panel, note, hooks) {
  tree = note.doc;
  onTag = hooks.onTag;
  onChanged = hooks.onChanged;
  [bodyEl, panelEl, hooksRef] = [body, panel, hooks];
  noteId = note.id;
  explorer = null;
  analysis = null;
  analysisError = null;
  byId = new Map(tree.moves.map((m) => [m.id, m]));
  refs = new Map(note.refs.map((r) => [`${r.kind}:${r.id}`, r]));
  firstFrom = new Map();
  for (const m of tree.moves) if (m.prev === null && !firstFrom.has(m.start)) firstFrom.set(m.start, m.id);
  startInfo = new Map();
  gameOf = new Map();
  blockOf = new Map();
  startBlock = new Map();
  const written = (list, name, index) => {
    for (const item of list) {
      if ("move" in item) {
        gameOf.set(item.move, name);
        blockOf.set(item.move, index);
      } else if ("line" in item) written(item.line, name, index);
    }
  };
  tree.blocks.forEach((block, index) => {
    if (block.t === "pgn") {
      written(block.items, gameName(block.headers), index);
      startBlock.set(block.start, index);
    }
  });
  for (const block of tree.blocks) {
    if (block.t === "pgn") startInfo.set(block.start, { where: gameName(block.headers), orient: "white", arrows: [], squares: [] });
    if (block.t === "fen") startInfo.set(block.start, { where: "Diagram", orient: toMove(tree.starts[block.start]), arrows: block.arrows, squares: block.squares });
  }

  const article = el("article", "panel journal-read");
  const prose = el("div", "journal-prose");
  text = prose;
  for (const block of tree.blocks) prose.append(drawBlock(block));
  if (!tree.blocks.length) prose.append(el("p", "journal-blank", "This note is empty. Press Write to start it."));
  article.append(prose);
  body.replaceChildren(article);

  const found = note.refs.filter((r) => r.found);
  const chess = tree.starts.length > 0 || found.length > 0;
  panel.replaceChildren();
  lit = [];
  if (!chess) return false;
  panel.innerHTML = `<div class="journal-boardbox">
      <div class="board" id="jrBoard"></div>
      ${stepsHtml("jr", { first: "Start of the line", last: "End of the line" })}
      <p class="small journal-where" id="jrWhere"></p>
      <div class="journal-refinfo" id="jrRef" hidden></div>
      <div class="journal-explore" id="jrExplore" hidden>
        <p class="journal-exploreline" id="jrLine" aria-live="polite"></p>
        <div class="journal-tools">
          <button class="btn ghost" type="button" id="jrBack">Take back</button>
          <button class="btn ghost" type="button" id="jrCopyLine">Copy line</button>
          <button class="btn primary" type="button" id="jrInsert">Insert as a variation</button>
          <button class="btn ghost" type="button" id="jrDone">Back to the note</button>
        </div>
      </div>
      <div class="journal-tools">
        <button class="btn ghost" type="button" id="jrFen">Copy FEN</button>
        <button class="btn ghost" type="button" id="jrPgn">Copy PGN up to here</button>
        <button class="btn ghost" type="button" id="jrContinue">Continue here</button>
        <button class="btn ghost" type="button" id="jrAnalyse">Analyse</button>
        <button class="btn ghost" type="button" id="jrFlip">Flip the board</button>
      </div>
      <div class="journal-analysis" id="jrAnalysis" aria-live="polite" hidden></div>
    </div>`;
  steps = bindSteps("jr", {
    last: () => (explorer ? explorer.play.state.moves.length : line.length - 1),
    get: () => (explorer ? explorer.play.at : at),
    set: (to) => {
      if (explorer) explorer.play.go(to);
      else { at = to; draw(); }
    },
  });
  $("jrFlip").addEventListener("click", () => {
    flipped = !flipped;
    if (explorer) explorer.play.draw();
    else draw();
  });
  $("jrFen").addEventListener("click", () => copy(shownFen(), "FEN"));
  $("jrPgn").addEventListener("click", copyPgn);
  $("jrContinue").addEventListener("click", explore);
  $("jrAnalyse").addEventListener("click", analyse);
  $("jrBack").addEventListener("click", () => explorer && explorer.play.takeBack());
  $("jrCopyLine").addEventListener("click", () => explorer && copy(explorer.play.state.line, "Line"));
  $("jrInsert").addEventListener("click", insertLine);
  $("jrDone").addEventListener("click", () => stopExploring(true));
  if (tree.starts.length) pickStart(0, false);
  else pickRef(found[0], false);
  return true;
}

// ---------------------------------------------------------------- the board

const toMove = (fen) => (fen.split(" ")[1] === "b" ? "black" : "white");
const moveName = (m) => `${m.no}${m.white ? "." : "..."} ${m.san}${m.nag}`;

function position(m) {
  const hl = {};
  for (const sq of uciSquares(m.uci)) hl[sq] = "sel";
  for (const [sq, colour] of m.squares) hl[sqIdx(sq)] = SQUARES[colour] || "sel";
  return { fen: m.fen, label: "After " + moveName(m), key: "m" + m.id, arrows: arrows(m.arrows), hl, uci: m.uci, move: m.id };
}

const arrows = (list) => list.map(([from, to, colour]) => ({ from: sqIdx(from), to: sqIdx(to), color: ARROWS[colour] || "red" }));

function startPosition(start) {
  const info = startInfo.get(start);
  const hl = {};
  for (const [sq, colour] of info ? info.squares : []) hl[sqIdx(sq)] = SQUARES[colour] || "sel";
  const isDiagram = info && info.where === "Diagram";
  return {
    fen: tree.starts[start],
    label: isDiagram ? "The diagram" : "Start",
    key: isDiagram ? "s" + start : null,
    arrows: arrows(info ? info.arrows : []),
    hl,
    start,
  };
}

/** Show the line through move `id`: back to its start, then on along its own line. */
function pickMove(id) {
  const back = [];
  for (let m = byId.get(id); m; m = m.prev === null ? null : byId.get(m.prev)) back.unshift(m);
  const ahead = [];
  for (let n = byId.get(id).next; n !== null && n !== undefined; n = byId.get(n).next) ahead.push(byId.get(n));
  const start = back[0].start;
  const where = gameOf.get(id) || (startInfo.get(start)?.where === "Diagram" ? "From the diagram" : "Moves in the text");
  setLine([startPosition(start), ...back.map(position), ...ahead.map(position)], back.length, where, naturalOf(start));
}

/** Show a start (a diagram, or a game's first position), and the line played from it. */
function pickStart(start, focus = true) {
  const ahead = [];
  for (let n = firstFrom.get(start); n !== null && n !== undefined; n = byId.get(n).next) ahead.push(byId.get(n));
  setLine([startPosition(start), ...ahead.map(position)], 0, whereOf(start), naturalOf(start));
  if (focus) $("jrNext")?.focus();
}

const whereOf = (start) => startInfo.get(start)?.where || "Moves in the text";
const naturalOf = (start) => startInfo.get(start)?.orient || "white";

/** Show a Log entry (the position before your move, with your move in red) or one of your
 *  games (from its start, stepping through its moves). */
function pickRef(r, focus = true) {
  const key = `r${r.kind}${r.id}`;
  let positions;
  if (r.kind === "log") {
    const [from, to] = uciSquares(r.played_uci);
    positions = [{
      fen: r.fen,
      label: "Before " + r.move + markText(r.judgment),
      key,
      arrows: [{ from, to, color: "red" }],
      hl: { [from]: "played", [to]: "played" },
    }];
  } else {
    positions = [{ fen: r.fen, label: "Start", key, arrows: [], hl: {} }];
    let [side, number] = [toMove(r.fen), Number(r.fen.split(" ")[5]) || 1];
    for (const m of r.moves) {
      const name = `${number}${side === "white" ? "." : "..."} ${m.san}`;
      const hl = {};
      for (const sq of uciSquares(m.uci)) hl[sq] = "sel";
      positions.push({ fen: m.fen, label: "After " + name, key, arrows: [], hl, uci: m.uci });
      if (side === "black") number += 1;
      side = side === "white" ? "black" : "white";
    }
  }
  setLine(positions, 0, refWhere(r), r.my_color || "white");
  const info = $("jrRef");
  info.hidden = false;
  info.innerHTML = r.kind === "log" ? markPill(r.judgment) + " " + statusPill(r.status, r.due_on) : "";
  const open = el("a", "", r.kind === "log" ? "Open it in the Log →" : "Open the game →");
  open.href = r.kind === "log" ? `#log/${r.id}` : `#games/${r.game_id}`;
  info.append(open);
  if (focus) $("jrNext")?.focus();
}

function setLine(positions, index, where, side) {
  if (explorer) stopExploring(false);
  line = positions;
  at = index;
  natural = side;
  flipped = false;
  $("jrWhere").textContent = where;
  $("jrRef").hidden = true;
  $("jrRef").replaceChildren();
  draw();
}

const orientNow = () => (flipped ? (natural === "white" ? "black" : "white") : natural);
const shownFen = () => (explorer ? explorer.play.fen : line[at].fen);

function draw() {
  const p = line[at];
  const best = analysis && analysis.fen === p.fen && analysis.lines[0];
  const shown = best ? [...p.arrows, { from: sqIdx(best.uci.slice(0, 2)), to: sqIdx(best.uci.slice(2, 4)), color: "green" }] : p.arrows;
  renderBoard($("jrBoard"), p.fen, orientNow(), { arrows: shown, hl: p.hl, label: "Board: " + p.label });
  $("jrLabel").textContent = p.label;
  steps.sync();
  light(p.key);
  drawAnalysis();
}

// ---------------------------------------------------------------- under the board (19.4)

function copy(value, what) {
  navigator.clipboard.writeText(value).then(
    () => toast(`${what} copied.`),
    (err) => toast(`Couldn't copy the ${what}: ${err.message}`),
  );
}

/** The game up to the position shown, from the line's start, as PGN. */
async function copyPgn() {
  const upTo = explorer ? explorer.base : at;
  const played = line.slice(1, upTo + 1).map((p) => p.uci).filter(Boolean);
  const more = explorer ? explorer.play.played : [];
  try {
    const answer = await api(BOARD, { method: "POST", body: { fen: line[0].fen, moves: [...played, ...more] } });
    copy(answer.pgn, "PGN");
  } catch (err) {
    toast("Couldn't make the PGN: " + err.message);
  }
}

/** Where a line played from this position can go in the note: after a move written in a
 *  PGN block, or from a PGN block's start. null anywhere else (a diagram, a sentence that
 *  goes past its game, a Log link). */
function target(p) {
  if (p.move !== undefined && blockOf.has(p.move)) return { block: blockOf.get(p.move), after: p.move };
  if (p.start !== undefined && startBlock.has(p.start)) return { block: startBlock.get(p.start), after: null };
  return null;
}

/** "Continue here": play on from the position shown, on the same board. */
async function explore() {
  if (explorer) return;
  const play = player({
    board: $("jrBoard"),
    orient: orientNow,
    changed: explored,
    failed: (message) => toast("That move can't be played: " + message),
  });
  explorer = { base: at, play, to: target(line[at]) };
  $("jrExplore").hidden = false;
  $("jrContinue").disabled = true;
  $("jrInsert").hidden = !explorer.to;
  await play.reset(line[at].fen);
  $("jrBoard").querySelector("button")?.focus();
}

function explored() {
  if (!explorer) return;
  const { state, at: shown } = explorer.play;
  const last = state.moves[shown - 1];
  $("jrLine").textContent = state.moves.length
    ? "Your line: " + state.line + (state.over ? ` (${state.over.toLowerCase()})` : "")
    : "Play on from here: tap a piece, then a square.";
  $("jrLabel").textContent = last ? `After ${last.no}${last.white ? "." : "..."} ${last.san}` : line[explorer.base].label;
  $("jrBack").disabled = shown === 0;
  $("jrCopyLine").disabled = $("jrInsert").disabled = !state.moves.length;
  steps.sync();
  drawAnalysis();
}

function stopExploring(redraw) {
  explorer = null;
  $("jrExplore").hidden = true;
  $("jrContinue").disabled = false;
  if (redraw) {
    draw();
    $("jrContinue").focus();
  }
}

/** Put the line you played into its game, as a variation, and show it. */
async function insertLine() {
  const { to, play } = explorer;
  const moves = play.state.moves.map((m) => m.uci);
  const lastFen = play.state.fen;
  $("jrInsert").disabled = true;
  let note;
  try {
    note = await api(`${NOTES}/${noteId}/lines`, { method: "POST", body: { block: to.block, after: to.after, moves } });
  } catch (err) {
    toast("Not inserted: " + err.message);
    $("jrInsert").disabled = false;
    return;
  }
  onChanged(note);
  open(bodyEl, panelEl, note, hooksRef);
  const end = note.doc.moves.find((m) => m.fen === lastFen && blockOf.get(m.id) === to.block);
  if (end) pickMove(end.id);
  toast("Your line is in the game now.");
}

async function analyse() {
  if (analysing) return;
  const fen = shownFen();
  const button = $("jrAnalyse");
  analysing = true;
  button.disabled = true;
  button.textContent = "Analysing\u2026";
  const box = $("jrAnalysis");
  box.hidden = false;
  box.replaceChildren(el("p", "small", "Stockfish is looking at this position\u2026"));
  analysisError = null;
  try {
    analysis = await api(ANALYSE, { method: "POST", body: { fen } });
  } catch (err) {
    analysis = null;
    analysisError = { fen, message: err.message };
  } finally {
    analysing = false;
    button.disabled = false;
    button.textContent = "Analyse";
  }
  if (explorer) drawAnalysis();
  else draw();
}

/** Stockfish's lines, under the board while the position they're for is shown. */
function drawAnalysis() {
  if (analysing) return;
  const box = $("jrAnalysis");
  const fen = shownFen();
  box.replaceChildren();
  if (analysisError && analysisError.fen === fen) {
    box.hidden = false;
    box.append(el("p", "journal-error", analysisError.message));
    return;
  }
  if (!analysis || analysis.fen !== fen) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (analysis.over) {
    box.append(el("p", "small", `${analysis.over}: there's nothing to analyse.`));
    return;
  }
  box.append(el("p", "small", `${analysis.engine} \u00b7 depth ${analysis.depth} \u00b7 the green arrow is its best move`));
  const list = el("ol", "journal-lines");
  for (const engineLine of analysis.lines) {
    const li = el("li");
    li.append(el("strong", "journal-eval", fmtEval(engineLine.eval)), " " + engineLine.line);
    list.append(li);
  }
  box.append(list);
}

/** Mark what's on the board in the text: the move (in a game and in each sentence that
 *  plays it), the diagram or the Log link. */
function light(key) {
  for (const node of lit) {
    node.classList.remove("journal-on");
    node.removeAttribute("aria-current");
  }
  lit = key ? [...text.querySelectorAll(`[data-key="${key}"]`)] : [];
  for (const node of lit) {
    node.classList.add("journal-on");
    node.setAttribute("aria-current", "true");
  }
}

// ---------------------------------------------------------------- blocks

function drawBlock(block) {
  switch (block.t) {
    case "heading": {
      const h = el("h" + Math.min(Math.max(block.level, 1), 6));
      spans(h, block.spans);
      return h;
    }
    case "para": {
      const p = el("p");
      spans(p, block.spans);
      return p;
    }
    case "quote": {
      const quote = el("blockquote");
      const p = el("p");
      spans(p, block.spans);
      quote.append(p);
      return quote;
    }
    case "list":
      return list(block);
    case "rule":
      return el("hr");
    case "ref":
      return card(block);
    case "code":
      return code(block);
    case "pgn":
      return game(block);
    case "fen":
      return diagram(block);
    default:
      return document.createTextNode("");
  }
}

function list(block) {
  const tag = block.ordered ? "ol" : "ul";
  const top = el(tag);
  if (block.ordered && block.start !== 1) top.start = block.start;
  const open = [top];
  let last = null;
  for (const item of block.items) {
    while (open.length - 1 > item.depth) open.pop();
    if (item.depth > open.length - 1 && last) {
      const inner = el(tag);
      last.append(inner);
      open.push(inner);
    }
    const li = el("li");
    spans(li, item.spans);
    open[open.length - 1].append(li);
    last = li;
  }
  return top;
}

function code(block) {
  const box = el("div", "journal-codebox");
  if (block.error) box.append(el("p", "journal-error", block.error));
  const pre = el("pre", "journal-code");
  pre.append(el("code", "", block.text));
  box.append(pre);
  return box;
}

/** "Tal – Petrosian · Sicilian Defence", from a PGN block's headers. */
function gameName(headers) {
  const parts = [];
  if (headers.White || headers.Black) parts.push(`${headers.White || "?"} – ${headers.Black || "?"}`);
  const opening = headers.Opening ? headers.Opening + (headers.Variation ? ", " + headers.Variation : "") : headers.ECO;
  if (opening) parts.push(opening);
  else if (headers.Event) parts.push(headers.Event);
  return ["Game", ...parts].join(" · ");
}

function game(block) {
  const box = el("div", "journal-game");
  box.append(el("div", "journal-gamehead", gameName(block.headers)));
  if (block.note) box.append(el("p", "small journal-gamenote", block.note));
  const moves = el("div", "journal-moves");
  items(moves, block.items);
  if (block.result && block.result !== "*") {
    const rows = moves.querySelectorAll(":scope > .journal-row");
    const last = rows[rows.length - 1] || moves;
    last.append(el("span", "journal-result", block.result));
  }
  box.append(moves);
  if (!block.items.length) box.append(button("btn ghost", "Show the position", () => pickStart(block.start)));
  return box;
}

/** A PGN block's moves: the main line as rows of text, each variation indented on its own
 *  line under the move it replaces, comments in italics. */
function items(container, list) {
  let row = el("div", "journal-row");
  container.append(row);
  let number = true; // the next Black move shows its number ("6...")
  for (const item of list) {
    if ("move" in item) {
      const m = byId.get(item.move);
      const label = (m.white ? `${m.no}. ` : number ? `${m.no}... ` : "") + m.san + m.nag;
      row.append(moveButton(m, label, false), " ");
      number = false;
    } else if ("comment" in item) {
      row.append(el("span", "journal-comment", item.comment), " ");
      number = true;
    } else {
      const variation = el("div", "journal-line");
      items(variation, item.line);
      container.append(variation);
      row = el("div", "journal-row");
      container.append(row);
      number = true;
    }
  }
  for (const blank of container.querySelectorAll(":scope > .journal-row")) if (!blank.childNodes.length) blank.remove();
}

function moveButton(m, label, said) {
  const b = button("journal-move" + (said ? " journal-said" : ""), label, () => pickMove(m.id));
  b.dataset.key = "m" + m.id;
  b.setAttribute("aria-label", `Show ${moveName(m)} on the board`);
  return b;
}

function diagram(block) {
  const figure = el("figure", "journal-figure");
  const board = el("div", "board");
  const side = toMove(tree.starts[block.start]);
  renderBoard(board, tree.starts[block.start], side, {
    arrows: arrows(block.arrows),
    hl: Object.fromEntries(block.squares.map(([sq, colour]) => [sqIdx(sq), SQUARES[colour] || "sel"])),
    label: `Diagram, ${side === "white" ? "White" : "Black"} to move`,
  });
  const caption = el("figcaption");
  if (block.caption) caption.append(block.caption, " ");
  if (block.playable) {
    const pick = button("journal-diagram", undefined, () => pickStart(block.start));
    pick.dataset.key = "s" + block.start;
    pick.setAttribute("aria-label", "Put this diagram on the board");
    pick.append(board);
    figure.append(pick);
    caption.append(el("span", "small", "Click the diagram to put it on the board."));
  } else {
    const still = el("div", "journal-still");
    still.append(board);
    figure.append(still);
    caption.append(el("span", "small", "This isn't a legal position, so it can't be played."));
  }
  figure.append(caption);
  return figure;
}

// ---------------------------------------------------------------- Log links

const refName = (r) => (r.kind === "log" ? r.move + markText(r.judgment) : outcome(r.result, r.my_color) || "Your game");

function refWhere(r) {
  const vs = r.opponent ? ` vs ${r.opponent}` : "";
  return r.kind === "log" ? `Your Log · ${refName(r)}${vs}` : `Your game${vs}`;
}

function refDetails(r) {
  return [r.opponent ? `vs ${r.opponent}` : null, timeControl(r.speed, r.tc_label), fmtDate(r.played_on)]
    .filter(Boolean)
    .join(" · ");
}

const missing = (kind, id) => (kind === "log" ? `Entry ${id} isn't in your Log.` : `Game ${id} isn't in your games.`);

/** A [[log 12]] on its own line: a card with the move, the game and its re-test status. */
function card(block) {
  const r = refs.get(`${block.kind}:${block.id}`);
  const box = el("div", "journal-card");
  box.append(el("span", "journal-cardlabel", block.kind === "log" ? "From your Log" : "From your games"));
  if (!r || !r.found) {
    box.append(el("span", "journal-missing", missing(block.kind, block.id)));
    return box;
  }
  box.dataset.key = `r${r.kind}${r.id}`;
  const pick = button("journal-cardpick", undefined, () => pickRef(r));
  pick.setAttribute("aria-label", `Show ${refName(r)} on the board`);
  const details = refDetails(r);
  pick.append(el("strong", "", refName(r)), details ? " " + details : "");
  box.append(pick);
  if (r.kind === "log") {
    const pills = el("span", "journal-pills");
    pills.innerHTML = statusPill(r.status, r.due_on);
    box.append(pills);
  }
  const link = el("a", "journal-openlink", "Open →");
  link.href = r.kind === "log" ? `#log/${r.id}` : `#games/${r.game_id}`;
  box.append(link);
  return box;
}

/** A [[log 12]] inside a sentence: the move and the opponent, as a link to the board. */
function inlineRef(span) {
  const r = refs.get(`${span.kind}:${span.id}`);
  if (!r || !r.found) return el("span", "journal-missing", `${span.text} (${span.kind === "log" ? "entry" : "game"} not found)`);
  const b = button("journal-ref", refName(r) + (r.opponent ? ` vs ${r.opponent}` : ""), () => pickRef(r));
  b.dataset.key = `r${r.kind}${r.id}`;
  b.title = refDetails(r);
  return b;
}

// ---------------------------------------------------------------- inline text

function spans(parent, list) {
  for (const s of list) {
    let node;
    if (s.t === "text") node = document.createTextNode(s.text);
    else if (s.t === "code") node = el("code", "", s.text);
    else if (s.t === "link") {
      node = el("a", "", s.text);
      node.href = s.href;
      if (/^https?:/i.test(s.href)) {
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }
    } else if (s.t === "tag") {
      node = button("journal-tag", s.text, () => onTag(s.tag));
      node.title = `Your notes tagged #${s.tag}`;
    } else if (s.t === "ref") node = inlineRef(s);
    else if (s.t === "move") node = moveButton(byId.get(s.move), s.text, true);
    else continue;
    if (s.i) node = wrap("em", node);
    if (s.b) node = wrap("strong", node);
    parent.append(node);
  }
}

function wrap(tag, node) {
  const outer = el(tag);
  outer.append(node);
  return outer;
}
