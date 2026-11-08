// Library practise (ROADMAP 11.3), ported from core's Re-test view: a position from an
// entry, facing the side you practise as. Tap a piece, then a square (only the legal moves
// the API sent). "Show a hint" lights up the square the answer starts from; "I don't know —
// show me" gives up. The server checks the move and only then sends the answers and the
// entry's idea.
//
// show(box, scope): scope "" is what's due today, "all" every position, or an entry's id.

import { api } from "/js/api.js";
import { renderBoard, sqIdx, sqName, uciSquares } from "/js/board.js";
import { fmtDate } from "/js/format.js";
import { esc, showError, toast } from "/js/ui.js";

export const QUEUE = "/api/ext/library/practise";
const KIND = { opening: "Opening", trap: "Trap", tactic: "Tactic" };

let box = null;
let scope = "";
let queue = []; // the items of this session
let index = 0; // the one on the board
let right = 0; // solved in this session
let loadToken = 0;

// The position on the board.
let fen = ""; // what's drawn: the position, or the one after your move
let selected = null; // the square you tapped first
let hl = {};
let arrows = [];
let usedHint = false;
let hintSquare = null; // the hint's square, kept lit while you pick a piece
let done = false;

const $ = (id) => document.getElementById(id);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export async function show(container, to) {
  box = container;
  scope = to || "";
  await load();
}

function queuePath() {
  if (scope === "all") return QUEUE + "?all=1";
  if (scope) return QUEUE + "?entry=" + encodeURIComponent(scope);
  return QUEUE;
}

/** "← Library", or back to the entry you started from. */
function back() {
  if (scope && scope !== "all") return `<a class="gback" href="#library/${encodeURIComponent(scope)}">← Back to the entry</a>`;
  return '<a class="gback" href="#library">← Library</a>';
}

async function load() {
  const token = ++loadToken;
  let data;
  try {
    data = await api(queuePath());
  } catch (err) {
    if (token !== loadToken) return;
    showError(err.message);
    box.innerHTML = back() + `<div class="panel empty"><p>${esc(err.message)}</p></div>`;
    return;
  }
  if (token !== loadToken) return;
  showError(null);
  queue = data.items;
  index = 0;
  right = 0;
  if (queue.length) renderPosition();
  else renderEmpty(data, null);
}

// ---------------------------------------------------------------- empty and finished

function renderEmpty(data, score) {
  const next = fmtDate(data.next_due_on);
  const lead = (score === null ? "" : `${score} `) + (next ? `Next one due on ${esc(next)}.` : "");
  box.innerHTML = `${back()}
  <div class="panel rt-empty">
    <h2>${score === null ? "Nothing to practise right now" : "Session done"}</h2>
    <p class="small">${lead || "&nbsp;"}</p>
    ${data.total ? `<button class="btn primary" id="lpAll" type="button">Practise all ${data.total} anyway</button>` : ""}
  </div>`;
  if (data.total) $("lpAll").addEventListener("click", () => { location.hash = "#library/practise/all"; });
}

async function finish() {
  const score = `You got ${right} of ${plural(queue.length, "position", "positions")} right.`;
  if (scope) {
    // A whole entry, or everything: the same positions again would never end.
    box.innerHTML = `${back()}
    <div class="panel rt-empty">
      <h2>Session done</h2>
      <p class="small">${esc(score)}</p>
      <button class="btn primary" id="lpAgain" type="button">Practise ${queue.length === 1 ? "it" : "them"} again</button>
    </div>`;
    $("lpAgain").addEventListener("click", load);
    return;
  }
  // What's due: anything still due starts a new session. Positions you just tried aren't
  // due again before tomorrow.
  try {
    const data = await api(QUEUE);
    queue = data.items;
    index = 0;
    if (queue.length) {
      right = 0;
      renderPosition();
    } else {
      renderEmpty(data, score);
    }
  } catch (err) {
    showError(err.message);
  }
}

// ---------------------------------------------------------------- the position

function renderPosition() {
  const item = queue[index];
  fen = item.fen;
  selected = null;
  hl = {};
  arrows = [];
  usedHint = false;
  hintSquare = null;
  done = false;
  const side = item.side === "white" ? "White" : "Black";
  const left = queue.length - index - 1;
  box.innerHTML = `${back()}
  <div class="panel rt">
    <div>
      <div class="board" id="lpBoard"></div>
      <p class="small boardnote">Tap a piece, then tap where it should go.</p>
    </div>
    <div class="prompt">
      <div class="rtprog" aria-hidden="true"><i style="width:${Math.round((100 * index) / queue.length)}%"></i></div>
      <span class="small">Position ${index + 1} of ${queue.length} · ${KIND[item.kind]}: <a href="#library/${encodeURIComponent(item.entry_id)}">${esc(item.name)}</a></span>
      <h2>${side} to move</h2>
      <p class="q">${esc(item.prompt)}</p>
      ${item.last_move ? `<p class="small">The last move was ${esc(item.last_move)}.</p>` : ""}
      <div class="rt-actions">
        <button class="btn ghost" id="lpHint" type="button">Show a hint</button>
        <button class="btn ghost" id="lpGive" type="button">I don't know — show me</button>
      </div>
      <div class="feedback" id="lpFb" aria-live="polite"></div>
      <p class="queue">${left} more in this session.</p>
    </div>
  </div>`;
  $("lpHint").addEventListener("click", () => hint(item));
  $("lpGive").addEventListener("click", () => submit(item, null));
  draw(item);
}

function draw(item) {
  const el = $("lpBoard");
  if (!el) return;
  if (done) {
    renderBoard(el, fen, item.side, { hl, arrows, label: "The position after your try" });
  } else {
    const targets = selected === null ? [] : targetsFrom(item, sqName(selected));
    renderBoard(el, fen, item.side, { hl, arrows, targets, onClick: (i) => tap(item, i) });
  }
}

/** The legal moves from `from` to `to`, e.g. ["e7e8q", "e7e8r", ...] or ["e2e3"]. */
const movesBetween = (item, from, to) => item.legal_uci.filter((m) => m.slice(0, 4) === from + to);
const movesFrom = (item, from) => item.legal_uci.some((m) => m.slice(0, 2) === from);
/** The squares the piece on `from` can go to, for the board's dots. */
const targetsFrom = (item, from) =>
  [...new Set(item.legal_uci.filter((m) => m.slice(0, 2) === from).map((m) => sqIdx(m.slice(2, 4))))];

function tap(item, i) {
  if (done) return;
  const square = sqName(i);
  if (selected !== null) {
    const moves = movesBetween(item, sqName(selected), square);
    if (moves.length) {
      // A promotion is offered once per piece; a queen, as in Re-test.
      submit(item, moves.find((m) => m.endsWith("q")) || moves[0]);
      return;
    }
  }
  if (movesFrom(item, square) && i !== selected) {
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
    const { from_square } = await api(`/api/ext/library/practise/${encodeURIComponent(item.entry_id)}/${item.n}/hint`);
    usedHint = true;
    hintSquare = sqIdx(from_square);
    hl = { ...hl, [hintSquare]: "sel" };
    draw(item);
    toast("Hint: the answer starts from the highlighted square");
  } catch (err) {
    showError(err.message);
  }
}

async function submit(item, move) {
  if (done) return;
  done = true;
  let result;
  try {
    result = await api(`/api/ext/library/practise/${encodeURIComponent(item.entry_id)}/${item.n}/attempt`, {
      method: "POST",
      body: { move_uci: move, used_hint: usedHint },
    });
  } catch (err) {
    done = false;
    showError(err.message);
    return;
  }
  hintSquare = null;
  if (result.solved) right++;
  showResult(item, result);
}

/** "5... Bxd1 falls into it: 6. Bxf7+ Ke7 7. Nd5#." and what the entry says about it. */
function replyText(r, lead) {
  const line = r.line ? `: ${esc(r.line)}` : "";
  return `<p class="library-said"><b>${esc(r.move)}</b> ${lead}${line}. ${esc(r.says)}</p>`;
}

function showResult(item, r) {
  const [af, at] = uciSquares(r.answer_uci);
  hl = {};
  arrows = [];
  if (r.move_uci) {
    fen = r.move_fen;
    const [f, t] = uciSquares(r.move_uci);
    hl = { [f]: r.solved ? "ok" : "bad", [t]: r.solved ? "ok" : "bad" };
  }
  if (!r.solved) {
    arrows = [{ from: af, to: at, color: "green" }];
    if (!r.move_uci) hl = { [af]: "best", [at]: "best" };
  }
  draw(item);

  const others = r.answers.filter((a) => a !== r.answer_san);
  const parts = [];
  if (r.solved) {
    if (others.length) parts.push(`<p class="library-said">Also right: ${others.map(esc).join(", ")}.</p>`);
    if (r.your_reply) parts.push(replyText(r.your_reply, "is sound"));
  } else {
    if (r.your_reply && r.your_reply.loses) parts.push(replyText(r.your_reply, "falls into it"));
    else if (r.your_reply) parts.push(replyText(r.your_reply, "isn't the answer here"));
    else if (r.move_san) parts.push(`<p class="library-said">You played ${esc(r.move_san)}.</p>`);
    if (r.answer_reply) parts.push(replyText(r.answer_reply, "is the answer"));
    else if (others.length) parts.push(`<p class="library-said">${others.map(esc).join(", ")} ${others.length === 1 ? "is" : "are"} right too.</p>`);
  }
  if (r.line_next) parts.push(`<p class="library-said">The line goes on with ${esc(r.line_next)}.</p>`);
  const days = r.next_in_days === 1 ? "1 day" : `${r.next_in_days} days`;
  const when = r.solved ? `Next in ${days}, on ${esc(fmtDate(r.due_on))}.` : "It comes back tomorrow.";
  const title = r.solved
    ? `Right — ${esc(r.move_san)}`
    : r.move_uci ? `Not this time — the answer was ${esc(r.answer_san)}` : `The answer was ${esc(r.answer_san)}`;
  const last = index + 1 >= queue.length;
  const fb = $("lpFb");
  fb.className = "feedback on " + (r.solved ? "ok" : "no");
  fb.innerHTML = `<h3>${title}</h3>${parts.join("")}
    <div class="lesson"><b>The idea:</b> ${esc(r.idea)}</div>
    <p class="library-said">${when}</p>
    <div class="rt-actions"><button class="btn primary" id="lpNext" type="button">${last ? "Finish" : "Next position"}</button></div>`;
  $("lpHint").disabled = true;
  $("lpGive").disabled = true;
  $("lpNext").addEventListener("click", () => {
    if (last) finish();
    else {
      index++;
      renderPosition();
    }
  });
  $("lpNext").focus();
}
