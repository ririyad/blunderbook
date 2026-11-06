// The Re-test view, ported from the demo (CLAUDE.md §11): the position before your blunder,
// facing your side. Tap a piece, then a square (only the legal moves the API sent). "Show a
// hint" lights up the square the best move starts from; "I don't know — show me" gives up.
// The server checks the move and only then sends the answer, your lesson and the next date.

import { api } from "../api.js";
import { renderBoard, sqIdx, sqName, uciSquares } from "../board.js";
import { MARK, SOURCE_TAG, fmtDate, moveLabel } from "../format.js";
import { entriesChanged, esc, showError, toast } from "../ui.js";

let root = null;
let queue = []; // the items of this session
let index = 0; // the one on the board
let practising = false; // "Practise all anyway"
let loadToken = 0;

// The puzzle on the board.
let fen = ""; // what's drawn: the position, or the one after your move
let selected = null; // the square you tapped first
let hl = {};
let arrows = [];
let usedHint = false;
let hintSquare = null; // the hint's square, kept lit while you pick a piece
let done = false;

const $ = (id) => document.getElementById(id);

export async function show(section) {
  root = section;
  practising = false;
  await load(false);
}

async function load(all) {
  const token = ++loadToken;
  let data;
  try {
    data = await api("/api/retest/queue" + (all ? "?all=1" : ""));
  } catch (err) {
    if (token !== loadToken) return;
    showError(err.message);
    root.innerHTML = '<div class="panel"><p class="empty">The re-test queue couldn\'t be loaded.</p></div>';
    return;
  }
  if (token !== loadToken) return;
  queue = data.items;
  index = 0;
  if (queue.length) renderPuzzle();
  else renderEmpty(data, false);
}

// ---------------------------------------------------------------- empty state

function renderEmpty(data, finished) {
  const next = fmtDate(data.next_due_on);
  const lead = data.total
    ? `${finished ? "Session done. " : ""}Next re-test: ${next ? esc(next) : "—"}.`
    : `Import a PGN on the <a href="#import">Import</a> tab, or with <code>blunderbook import FILE.pgn</code>.`;
  root.innerHTML = `
  <div class="panel rt-empty">
    <h2>Nothing due right now</h2>
    <p class="small">${lead}</p>
    ${data.total ? `<button class="btn primary" id="rtAll" type="button">Practise all ${data.total} anyway</button>` : ""}
  </div>`;
  if (data.total) {
    $("rtAll").addEventListener("click", () => {
      practising = true;
      load(true);
    });
  }
}

async function finishSession() {
  try {
    // Anything still due starts a new session: games imported meanwhile. Entries you just
    // tried aren't due again before tomorrow.
    practising = false;
    const data = await api("/api/retest/queue");
    queue = data.items;
    index = 0;
    if (queue.length) renderPuzzle();
    else renderEmpty(data, true);
  } catch (err) {
    showError(err.message);
  }
}

// ---------------------------------------------------------------- puzzle

function renderPuzzle() {
  const item = queue[index];
  fen = item.fen;
  selected = null;
  hl = {};
  arrows = [];
  usedHint = false;
  hintSquare = null;
  done = false;
  const side = item.my_color === "white" ? "White" : "Black";
  const game = [
    `${SOURCE_TAG[item.source]} game vs ${esc(item.opponent || "Unknown")}`,
    item.played_on ? esc(fmtDate(item.played_on)) : null,
  ].filter(Boolean).join(", ");
  const left = queue.length - index - 1;
  root.innerHTML = `
  <div class="panel rt">
    <div>
      <div class="board" id="rtBoard"></div>
      <p class="small boardnote">Tap a piece, then tap where it should go.</p>
    </div>
    <div class="prompt">
      <div class="rtprog" aria-hidden="true"><i style="width:${Math.round((100 * index) / queue.length)}%"></i></div>
      <span class="small">Puzzle ${index + 1} of ${queue.length}${practising ? " (practice)" : ""} · ${game}</span>
      <h2>${side} to move — find the best move</h2>
      <p class="q">Move ${item.move_no}. In the game you went wrong here. Take your time and check your opponent's threats first.</p>
      <div class="rt-actions">
        <button class="btn ghost" id="rtHint" type="button">Show a hint</button>
        <button class="btn ghost" id="rtGive" type="button">I don't know — show me</button>
      </div>
      <div class="feedback" id="fb" aria-live="polite"></div>
      <p class="queue">${left} more in this session.</p>
    </div>
  </div>`;
  $("rtHint").addEventListener("click", () => hint(item));
  $("rtGive").addEventListener("click", () => submit(item, null));
  draw(item);
}

function draw(item) {
  const el = $("rtBoard");
  if (!el) return;
  if (done) {
    renderBoard(el, fen, item.my_color, { hl, arrows, label: "The position after the re-test" });
  } else {
    renderBoard(el, fen, item.my_color, { hl, arrows, onClick: (i) => tap(item, i) });
  }
}

/** The legal moves from `from` to `to`, e.g. ["e7e8q", "e7e8r", ...] or ["e2e3"]. */
const movesBetween = (item, from, to) => item.legal_uci.filter((m) => m.slice(0, 4) === from + to);
const movesFrom = (item, from) => item.legal_uci.some((m) => m.slice(0, 2) === from);

function tap(item, i) {
  if (done) return;
  const square = sqName(i);
  if (selected !== null) {
    const moves = movesBetween(item, sqName(selected), square);
    if (moves.length) {
      // A promotion is offered once per piece; a queen, as in the demo.
      submit(item, moves.find((m) => m.endsWith("q")) || moves[0]);
      return;
    }
  }
  if (movesFrom(item, square)) {
    selected = i;
    hl = { ...hintHl(), [i]: "sel" };
  } else {
    selected = null;
    hl = hintHl();
  }
  draw(item);
}

const hintHl = () => (hintSquare === null ? {} : { [hintSquare]: "sel" });

async function hint(item) {
  try {
    const { from_square } = await api(`/api/retest/${item.id}/hint`);
    usedHint = true;
    hintSquare = sqIdx(from_square);
    hl = { ...hl, [hintSquare]: "sel" };
    draw(item);
    toast("Hint: the best move starts from the highlighted square");
  } catch (err) {
    showError(err.message);
  }
}

async function submit(item, move) {
  if (done) return;
  done = true;
  let result;
  try {
    result = await api(`/api/retest/${item.id}/attempt`, {
      method: "POST",
      body: { move_uci: move, used_hint: usedHint },
    });
  } catch (err) {
    done = false;
    showError(err.message);
    return;
  }
  hintSquare = null;
  entriesChanged();
  showResult(item, result);
}

function showResult(item, r) {
  const [bf, bt] = uciSquares(r.best_uci);
  hl = {};
  arrows = [];
  if (r.move_uci) {
    fen = r.move_fen;
    const [f, t] = uciSquares(r.move_uci);
    hl = { [f]: r.solved ? "ok" : "bad", [t]: r.solved ? "ok" : "bad" };
  }
  if (!r.solved) {
    arrows = [{ from: bf, to: bt, color: "green" }];
    if (!r.move_uci) hl = { [bf]: "best", [bt]: "best" };
  }
  draw(item);

  const played = `<b>${moveLabel(item.move_no, item.my_color)}${esc(r.played_san)}${MARK[r.judgment]}</b>`;
  const days = r.next_in_days === 1 ? "1 day" : `${r.next_in_days} days`;
  const topChoice = r.move_uci && r.move_uci.slice(0, 4) !== r.best_uci.slice(0, 4)
    ? ` (engine's top choice: ${esc(r.best_san)})`
    : "";
  const fb = $("fb");
  fb.className = "feedback on " + (r.solved ? "ok" : "no");
  fb.innerHTML = r.solved
    ? `<h3>Solved — ${esc(r.move_san)}${topChoice}</h3>
       <p style="margin:0">In the game you played ${played}. Next re-test in ${days}, on ${esc(fmtDate(r.due_on))}.</p>`
    : `<h3>Missed — best was ${esc(r.best_san)}</h3>
       <p style="margin:0">${esc(r.best_line_san)}. In the game you played ${played}${r.refutation_san ? " (" + esc(r.refutation_san) + ")" : ""}.
       ${r.move_san ? `This time you played ${esc(r.move_san)}. ` : ""}It comes back tomorrow.</p>`;
  fb.innerHTML += r.lesson
    ? `<div class="lesson"><b>Your rule:</b> ${esc(r.lesson)}</div>`
    : `<div class="lesson small">No lesson written for this one yet. <a href="#log/${r.id}">Add it in the Log.</a></div>`;
  const last = index + 1 >= queue.length;
  fb.innerHTML += `<div class="rt-actions"><button class="btn primary" id="rtNext" type="button">${last ? "Finish" : "Next puzzle"}</button></div>`;
  $("rtHint").disabled = true;
  $("rtGive").disabled = true;
  $("rtNext").addEventListener("click", () => {
    if (last) finishSession();
    else {
      index++;
      renderPuzzle();
    }
  });
  $("rtNext").focus();
}
