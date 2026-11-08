// The Library tab (ROADMAP 11.2): openings, traps and tactics. `#library` is the index;
// `#library/legal-trap` opens one entry: its idea, the board stepping through its moves, and
// the replies that can come next, each played out on the board.
//
// The API sends the FEN after every move, so there's no chess logic here (as in core).
// Practise positions and their answers aren't on this page: they come with 11.3.

import { api } from "/js/api.js";
import { renderBoard, uciSquares } from "/js/board.js";
import { esc, showError } from "/js/ui.js";

const API = "/api/ext/library/entries";
const KINDS = [["opening", "Openings", "Opening"], ["trap", "Traps", "Trap"], ["tactic", "Tactics", "Tactic"]];
const ICON = {
  first: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3v10M12 3 7 8l5 5"/></svg>',
  prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 3 5 5-5 5"/></svg>',
  last: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v10M4 3l5 5-5 5"/></svg>',
};

let root = null;
let entry = null; // the open entry, as the API sent it
let reply = null; // the index of the reply being played out, or null
let ply = 0; // the position shown: 0 is the start, n is after n moves of the path
let listScroll = 0; // where the index was, for "← Library"
let token = 0; // only the newest answer is drawn

const $ = (id) => document.getElementById(id);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const sideName = (side) => (side === "white" ? "White" : "Black");

export async function show(section, rest) {
  if (root !== section) build(section);
  const id = decodeURIComponent(rest || "");
  if (id) {
    if ($("libIndex").offsetParent !== null) listScroll = window.scrollY;
    $("libIndex").hidden = true;
    $("libEntry").hidden = false;
    await openEntry(id);
  } else {
    entry = null;
    $("libEntry").hidden = true;
    $("libIndex").hidden = false;
    await openIndex();
    window.scrollTo(0, listScroll);
  }
}

function build(section) {
  root = section;
  section.innerHTML = '<div class="library"><div id="libIndex"></div><div id="libEntry" hidden></div></div>';
  section.addEventListener("keydown", stepWithKeys);
}

// ---------------------------------------------------------------- the index

async function openIndex() {
  const mine = ++token;
  let list;
  try {
    list = await api(API);
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
    + KINDS.map(([kind, title]) => group(kind, title, list.filter((e) => e.kind === kind))).join("");
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
    <span class="library-name">${esc(e.name)}</span>
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
  ply = data.moves.length; // the end of the line, where the replies start
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
      <div class="nav">
        <div class="grp">
          <button class="icon" type="button" id="libFirst" aria-label="Start position">${ICON.first}</button>
          <button class="icon" type="button" id="libPrev" aria-label="Previous move">${ICON.prev}</button>
          <button class="icon" type="button" id="libNext" aria-label="Next move">${ICON.next}</button>
          <button class="icon" type="button" id="libLast" aria-label="Last move">${ICON.last}</button>
        </div>
        <span class="navlabel" id="libLabel" aria-live="polite"></span>
      </div>
      ${legend}
    </div>
    <div>
      <div class="head"><div>
        <h2>${esc(e.name)}</h2>
        <div class="meta">${meta.join(" · ")}</div>
      </div></div>
      <div class="sec"><h3>The idea</h3><p class="library-idea">${esc(e.idea)}</p></div>
      <div class="sec"><h3 id="libMovesTitle">Moves</h3>${movesHtml(e.moves)}</div>
      ${e.next.length ? `<div class="sec"><h3>What can come next</h3><ul class="library-next">${e.next.map(replyHtml).join("")}</ul></div>` : ""}
    </div>
  </div>`;
  const go = (to) => () => { ply = Math.max(0, Math.min(path().length, to())); drawEntry(); };
  $("libFirst").addEventListener("click", go(() => 0));
  $("libPrev").addEventListener("click", go(() => ply - 1));
  $("libNext").addEventListener("click", go(() => ply + 1));
  $("libLast").addEventListener("click", go(() => path().length));
  for (const b of $("libEntry").querySelectorAll(".mbtn")) {
    b.addEventListener("click", () => {
      if (b.dataset.reply !== undefined) reply = Number(b.dataset.reply);
      ply = Number(b.dataset.pos);
      drawEntry();
    });
  }
  drawEntry();
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
  return `<li class="library-reply ${n.loses ? "loses" : "sound"}">
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
  $("libFirst").disabled = $("libPrev").disabled = ply === 0;
  $("libNext").disabled = $("libLast").disabled = ply === moves.length;
  for (const b of $("libEntry").querySelectorAll(".mbtn")) {
    const mine = b.dataset.reply === undefined || Number(b.dataset.reply) === reply;
    b.setAttribute("aria-current", String(mine && Number(b.dataset.pos) === ply));
  }
}

/** ← → Home End step through the moves while an entry is open, unless you're typing. */
function stepWithKeys(ev) {
  if (!entry || $("libEntry").hidden || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) return;
  const last = path().length;
  const to = { ArrowLeft: ply - 1, ArrowRight: ply + 1, Home: 0, End: last }[ev.key];
  if (to === undefined) return;
  ev.preventDefault();
  ply = Math.max(0, Math.min(last, to));
  drawEntry();
}
