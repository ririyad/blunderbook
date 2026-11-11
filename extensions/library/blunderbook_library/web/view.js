// The Library tab (ROADMAP 11.2 to 11.4): openings, traps and tactics. `#library` is the
// index; `#library/legal-trap` opens one entry: its idea, the board stepping through its
// moves, the replies that can come next, each played out on the board, and your own Log
// entries from games that reached its position.
// `#library/practise` (`/all`, `/legal-trap`) is practise, in ./practise.js.
//
// The API sends the FEN after every move, so there's no chess logic here (as in core).

import { api } from "/js/api.js";
import { renderBoard, uciSquares } from "/js/board.js";
import { MARK, fmtDate, plural } from "/js/format.js";
import { bindSteps, stepsHtml } from "/js/steps.js";
import { esc, showError } from "/js/ui.js";
import * as practise from "./practise.js";

const API = "/api/ext/library/entries";
const KINDS = [["opening", "Openings", "Opening"], ["trap", "Traps", "Trap"], ["tactic", "Tactics", "Tactic"]];

let root = null;
let entry = null; // the open entry, as the API sent it
let reply = null; // the index of the reply being played out, or null
let ply = 0; // the position shown: 0 is the start, n is after n moves of the path
let steps = null; // the step controls under the board
let listScroll = 0; // where the index was, for "← Library"
let token = 0; // only the newest answer is drawn

const $ = (id) => document.getElementById(id);
const sideName = (side) => (side === "white" ? "White" : "Black");

export async function show(section, rest) {
  if (root !== section) build(section);
  const [first, ...more] = (rest || "").split("/");
  const id = decodeURIComponent(first);
  if ($("libIndex").offsetParent !== null) listScroll = window.scrollY;
  for (const part of ["libIndex", "libEntry", "libPractise"]) $(part).hidden = true;
  if (id === "practise") {
    entry = null;
    $("libPractise").hidden = false;
    ++token; // an index or entry still loading isn't drawn
    await practise.show($("libPractise"), decodeURIComponent(more.join("/")));
  } else if (id) {
    $("libEntry").hidden = false;
    await openEntry(id);
  } else {
    entry = null;
    $("libIndex").hidden = false;
    await openIndex();
    window.scrollTo(0, listScroll);
  }
}

function build(section) {
  root = section;
  section.innerHTML = '<div class="library"><div id="libIndex"></div><div id="libEntry" hidden></div><div id="libPractise" hidden></div></div>';
}

// ---------------------------------------------------------------- the index

async function openIndex() {
  const mine = ++token;
  let list, due;
  try {
    [list, due] = await Promise.all([api(API), api(practise.QUEUE)]);
  } catch (err) {
    if (mine !== token) return;
    showError(err.message);
    $("libIndex").innerHTML = '<p class="panel empty">The Library couldn\'t be loaded.</p>';
    return;
  }
  if (mine !== token) return;
  showError(null);
  if (!list.length) {
    $("libIndex").innerHTML = '<div class="panel empty"><p>The Library is empty.</p>'
      + "<p>Run <code>blunderbook library check</code> to see why.</p></div>";
    return;
  }
  $("libIndex").innerHTML = '<p class="library-intro">Openings, traps and tactics. Open one to step through its moves and the replies that can come next.</p>'
    + practisePanel(list, due)
    + KINDS.map(([kind, title]) => group(kind, title, list.filter((e) => e.kind === kind))).join("");
  const start = $("libStart");
  if (start) start.addEventListener("click", () => { location.hash = start.dataset.to; });
}

/** What's due, and a button to start. */
function practisePanel(list, due) {
  const total = list.reduce((n, e) => n + e.practise.positions, 0);
  const solved = list.reduce((n, e) => n + e.practise.solved, 0);
  const tried = list.reduce((n, e) => n + e.practise.tried, 0);
  const n = due.items.length;
  const done = tried ? ` · ${solved} of ${total} solved` : "";
  let lead, button;
  if (n) {
    lead = `${plural(n, "position", "positions")} to practise today${done}.`;
    button = `<button class="btn primary" type="button" id="libStart" data-to="#library/practise">Practise ${n}</button>`;
  } else {
    const next = fmtDate(due.next_due_on);
    lead = `Nothing due today${next ? `. Next on ${esc(next)}` : ""}${done}.`;
    button = `<button class="btn ghost" type="button" id="libStart" data-to="#library/practise/all">Practise all ${total} anyway</button>`;
  }
  return `<div class="panel library-practise"><div><h3>Practise</h3><p class="small">${lead}</p></div>${button}</div>`;
}

/** Where your practise of an entry stands, as a pill. */
function progressPill(c) {
  if (!c.tried) return '<span class="pill p-new">New</span>';
  if (c.solved === c.positions && !c.due) return '<span class="pill p-solved">Solved</span>';
  if (c.due) return '<span class="pill p-due">Due</span>';
  return `<span class="pill p-missed">${c.solved} of ${c.positions} solved</span>`;
}

function group(kind, title, items) {
  if (!items.length) return "";
  return `<section class="panel library-group" aria-labelledby="libKind-${kind}">
    <div class="library-head"><h3 id="libKind-${kind}">${title}</h3><span class="small">${plural(items.length, "entry", "entries")}</span></div>
    <ul class="library-list">${items.map(row).join("")}</ul>
  </section>`;
}

function row(e) {
  const where = [e.opening, e.eco].filter(Boolean).map(esc).join(" · ");
  return `<li><a class="library-row" href="#library/${encodeURIComponent(e.id)}">
    <span class="library-name">${esc(e.name)} ${progressPill(e.practise)}</span>
    <span class="small"><span class="side ${e.side}" aria-hidden="true"></span>You play ${sideName(e.side)}${where ? " · " + where : ""}</span>
  </a></li>`;
}

// ---------------------------------------------------------------- one entry

async function openEntry(id) {
  const mine = ++token;
  const view = $("libEntry");
  let data;
  try {
    data = await api(`${API}/${encodeURIComponent(id)}`);
  } catch (err) {
    if (mine !== token) return;
    entry = null;
    view.innerHTML = `<div class="panel empty"><p>${esc(err.message)}</p><p><a href="#library">The Library</a></p></div>`;
    return;
  }
  if (mine !== token) return;
  showError(null);
  entry = data;
  reply = null;
  // An opening is learnt from its first move; a trap or a tactic opens where it matters,
  // at the end of the line, where the replies start.
  ply = data.kind === "opening" ? 0 : data.moves.length;
  renderEntry();
  window.scrollTo(0, 0);
}

/** The moves the step controls go through: the entry's, then the reply being played out. */
const path = () => (reply === null ? entry.moves : entry.moves.concat(entry.next[reply].moves));

function renderEntry() {
  const e = entry;
  const kind = KINDS.find(([k]) => k === e.kind)[2];
  const meta = [kind, `You play ${sideName(e.side)}`];
  if (e.opening) meta.push(esc(e.opening) + (e.eco ? ` (${esc(e.eco)})` : ""));
  else if (e.eco) meta.push(esc(e.eco));
  const legend = e.next.length
    ? '<div class="legend"><span><i class="l-sel"></i>Last move</span><span><i class="l-best"></i>A sound reply</span><span><i class="l-played"></i>A reply that loses</span></div>'
    : "";
  $("libEntry").innerHTML = `
  <a class="gback" href="#library">← Library</a>
  <div class="panel detail">
    <div class="boardwrap">
      <div class="board" id="libBoard"></div>
      ${stepsHtml("lib", { first: "Start position", last: "Last move" })}
      ${legend}
    </div>
    <div>
      <div class="head"><div>
        <h2>${esc(e.name)}</h2>
        <div class="meta">${meta.join(" · ")}</div>
      </div>
      <div class="library-go">
        <button class="btn primary" type="button" id="libPractiseIt">Practise ${e.practise.positions === 1 ? "this position" : `these ${e.practise.positions} positions`}</button>
        <span class="small">${e.practise.tried ? `${e.practise.solved} of ${e.practise.positions} solved` : "Not practised yet"}</span>
      </div></div>
      <div class="sec"><h3>The idea</h3><p class="library-idea">${esc(e.idea)}</p></div>
      <div class="sec"><h3 id="libMovesTitle">Moves</h3>${movesHtml(e.moves)}</div>
      ${e.next.length ? `<div class="sec"><h3>What can come next</h3><ul class="library-next">${e.next.map(replyHtml).join("")}</ul></div>` : ""}
      <div class="sec"><h3 id="libYoursTitle">From your Log</h3><div id="libYours" aria-live="polite"><p class="small">Looking through your Log…</p></div></div>
    </div>
  </div>`;
  $("libPractiseIt").addEventListener("click", () => { location.hash = `#library/practise/${encodeURIComponent(e.id)}`; });
  steps = bindSteps("lib", { last: () => path().length, get: () => ply, set: (to) => { ply = to; drawEntry(); } });
  for (const b of $("libEntry").querySelectorAll(".mbtn")) {
    b.addEventListener("click", () => {
      if (b.dataset.reply !== undefined) reply = Number(b.dataset.reply);
      ply = Number(b.dataset.pos);
      drawEntry();
    });
  }
  drawEntry();
  loadYours(e);
}

/** Your Log entries from games that reached this position, linking to the Log. They're
 *  asked for after the entry is drawn, so the Log can never keep the entry from showing. */
async function loadYours(e) {
  let found;
  try {
    found = await api(`${API}/${encodeURIComponent(e.id)}/log`);
  } catch (err) {
    if (entry !== e) return;
    $("libYours").innerHTML = `<p class="small">Your Log couldn't be read: ${esc(err.message)}</p>`;
    return;
  }
  if (entry !== e) return; // another entry was opened meanwhile
  if (!found.length) {
    $("libYours").innerHTML = '<p class="small">None of your Log entries come from a game that reached this position.</p>';
    return;
  }
  const fell = found.filter((m) => m.fell_in).length;
  const lead = `${plural(found.length, "entry", "entries")} from your games that reached this position`
    + (fell ? `, and you fell into it ${fell === 1 ? "once" : `${fell} times`}` : "") + ".";
  $("libYours").innerHTML = `<p class="small">${lead}</p><ul class="library-yours" aria-labelledby="libYoursTitle">${found.map(mineHtml).join("")}</ul>`;
}

function mineHtml(m) {
  const where = m.fell_in
    ? '<span class="pill p-blunder">Fell into it</span>'
    : m.on_line ? '<span class="pill p-new">On this line</span>' : "";
  const game = [`vs ${esc(m.opponent || "Unknown")}`, m.played_on ? esc(fmtDate(m.played_on)) : null].filter(Boolean).join(" · ");
  return `<li><a class="library-mine" href="#log/${m.id}">
    <span class="pill p-blunder" aria-label="${esc(m.judgment)}">${MARK[m.judgment]}</span>
    <b>${esc(m.move)}</b>${where}
    <span class="small">${game}</span>
    <span class="small library-open">Open in the Log</span>
  </a></li>`;
}

/** The entry's moves in rows of a move number, White's move and Black's, as on the game
 *  page. Position i + 1 is after move i, so each button jumps to the position after it. */
function movesHtml(moves) {
  if (!moves.length) return '<p class="small">It starts from the position on the board.</p>';
  const rows = [];
  moves.forEach((m, i) => {
    if (m.color === "white" || !rows.length) rows.push({ no: m.move_no, white: null, black: null });
    rows[rows.length - 1][m.color] = { ...m, pos: i + 1 };
  });
  const cell = (m) => (m
    ? `<button type="button" class="mbtn" data-pos="${m.pos}" aria-label="${esc(m.label)}">${esc(m.san)}</button>`
    : '<span class="mempty">…</span>');
  return `<ol class="mlist" aria-labelledby="libMovesTitle">${rows.map((r) => `<li><span class="no">${r.no}.</span>${cell(r.white)}${cell(r.black)}</li>`).join("")}</ol>`;
}

/** One reply: whether it loses, its moves as buttons (the reply, then what follows), and
 *  what it means. */
function replyHtml(n, i) {
  const start = entry.moves.length;
  const buttons = n.moves.map((m, j) => {
    const text = j === 0 || m.color === "white" ? m.label : m.san;
    const bad = j === 0 && n.loses ? " bad" : "";
    return `<button type="button" class="mbtn${bad}" data-reply="${i}" data-pos="${start + j + 1}" aria-label="${esc(m.label)}">${esc(text)}</button>`;
  }).join("");
  const pill = n.loses ? '<span class="pill p-blunder">Loses</span>' : '<span class="pill p-solved">Sound</span>';
  return `<li class="library-reply ${n.loses ? "library-loses" : "library-sound"}">
    <div class="library-line">${pill}${buttons}</div>
    <p class="library-says">${esc(n.says)}</p>
  </li>`;
}

function drawEntry() {
  const moves = path(), hl = {}, arrows = [];
  let label = "Start position";
  if (ply > 0) {
    const m = moves[ply - 1];
    const [f, t] = uciSquares(m.uci);
    if (reply !== null && ply - 1 === entry.moves.length) {
      // The reply itself: green when it's sound, red when it loses.
      const loses = entry.next[reply].loses;
      hl[f] = hl[t] = loses ? "played" : "best";
      arrows.push({ from: f, to: t, color: loses ? "red" : "green" });
    } else {
      hl[f] = hl[t] = "sel";
    }
    label = `After ${m.label}`;
  }
  if (ply === entry.moves.length && entry.next.length && reply === null) {
    label += " · pick a reply below";
  }
  const fen = ply === 0 ? entry.start_fen : moves[ply - 1].fen;
  renderBoard($("libBoard"), fen, entry.side, { hl, arrows, label });
  $("libLabel").textContent = label;
  steps.sync();
  for (const b of $("libEntry").querySelectorAll(".mbtn")) {
    const mine = b.dataset.reply === undefined || Number(b.dataset.reply) === reply;
    b.setAttribute("aria-current", String(mine && Number(b.dataset.pos) === ply));
  }
}
