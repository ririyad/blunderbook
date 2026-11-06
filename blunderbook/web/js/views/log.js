// The Log view, ported from the demo (CLAUDE.md §11): filters and list on the left; on the
// right the board with step controls, I played / Best was, the eval bar, the game's details,
// cause chips and your notes, which save as you type.
//
// `#log/12` opens entry 12. Picking an entry updates the address without adding to history.

import { api } from "../api.js";
import { renderBoard, uciSquares } from "../board.js";
import { CAUSES } from "../causes.js";
import {
  MARK, SOURCE_NAME, SOURCE_TAG, fmtClock, fmtDate, fmtEval, fmtSpent, isDue, moveLabel,
  outcome, percent, timeControl,
} from "../format.js";
import { entriesChanged, esc, showError, toast } from "../ui.js";

const SAVE_DELAY_MS = 400;
const NARROW = "(max-width: 900px)"; // one column: the detail is under the list
const ICON = {
  first: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3v10M12 3 7 8l5 5"/></svg>',
  prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 3 5 5-5 5"/></svg>',
  blunder: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg>',
};

let root = null; // the view's section, once built
let items = []; // the list, as last fetched
let currentId = null; // the entry in the detail panel
let entry = null; // its full data, with your unsaved edits applied
let ply = 0; // the position shown: 0 is the start, n is after n moves
let showBest = false;
let listToken = 0, detailToken = 0; // only the newest answer is drawn

// Notes waiting to be saved: field -> value. Saves go one at a time, in order.
const unsaved = new Map();
let saveTimer = null;
let saving = Promise.resolve();

const $ = (id) => document.getElementById(id);
const na = (v) => (v == null || v === "" ? '<span class="na">—</span>' : esc(v));

export async function show(section, rest) {
  if (root !== section) build(section);
  const wanted = Number.parseInt(rest, 10);
  if (!(await refreshList())) {
    $("detail").replaceChildren();
    return;
  }
  const id = Number.isInteger(wanted) ? wanted : (currentId ?? items[0]?.id ?? null);
  if (id === null) renderNoEntry();
  else await select(id);
}

// ---------------------------------------------------------------- list

function build(section) {
  root = section;
  section.innerHTML = `
  <div class="log">
    <aside class="panel">
      <div class="filters">
        <label class="sr" for="fSource">Source</label>
        <select id="fSource"><option value="">All sources</option>${options(SOURCE_NAME)}</select>
        <label class="sr" for="fStatus">Status</label>
        <select id="fStatus"><option value="">Any status</option><option value="due">Due for re-test</option><option value="new">New</option><option value="missed">Missed again</option><option value="solved">Solved</option></select>
        <label class="sr" for="fCause">Cause</label>
        <select id="fCause"><option value="">Any cause</option>${CAUSES.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select>
      </div>
      <p class="count" id="count" aria-live="polite"></p>
      <ul class="list" id="list" aria-label="Entries"></ul>
    </aside>
    <article class="panel" id="detail" aria-label="Entry"></article>
  </div>`;
  for (const id of ["fSource", "fStatus", "fCause"]) {
    $(id).addEventListener("change", async () => {
      await refreshList();
      if (currentId === null && items.length) await select(items[0].id);
    });
  }
  window.addEventListener("pagehide", sendNow);
}

const options = (names) =>
  Object.entries(names).map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join("");

const filtering = () => ["fSource", "fStatus", "fCause"].some((id) => $(id).value);

/** The filters as API query parameters. "Due for re-test" is due and re-tested before. */
function query() {
  const params = new URLSearchParams();
  if ($("fSource").value) params.set("source", $("fSource").value);
  const status = $("fStatus").value;
  if (status === "due") {
    params.set("due", "1");
    params.append("status", "solved");
    params.append("status", "missed");
  } else if (status) params.set("status", status);
  if ($("fCause").value) params.set("cause", $("fCause").value);
  const text = params.toString();
  return text ? "?" + text : "";
}

/** Fetch the list for the current filters and draw it. False when it can't be fetched. */
async function refreshList() {
  const token = ++listToken;
  let found;
  try {
    found = await api("/api/blunders" + query());
  } catch (err) {
    if (token !== listToken) return false;
    showError(err.message);
    $("list").innerHTML = `<li class="empty">The Log couldn't be loaded.</li>`;
    return false;
  }
  if (token !== listToken) return false;
  showError(null);
  items = found;
  renderList();
  return true;
}

function statusPill(status, dueOn) {
  if (status === "new") return '<span class="pill p-new">New</span>';
  if (isDue(dueOn)) return '<span class="pill p-due">Due</span>';
  return status === "solved" ? '<span class="pill p-solved">Solved</span>' : '<span class="pill p-missed">Missed</span>';
}

const sourceTag = (source) => `<span class="src s-${esc(source)}">${esc(SOURCE_TAG[source] || source)}</span>`;

function renderList() {
  const ul = $("list");
  ul.replaceChildren();
  if (!items.length) {
    const text = filtering() ? "No blunders match these filters." : "No entries yet.";
    ul.innerHTML = `<li class="empty">${text}</li>`;
    $("count").textContent = "";
    return;
  }
  $("count").textContent = items.length === 1 ? "1 entry" : `${items.length} entries`;
  for (const item of items) {
    const when = [];
    if (item.source !== "fen") when.push(esc(timeControl(item.speed, item.tc_label) || "No time control"));
    if (item.played_on) when.push(esc(fmtDate(item.played_on)));
    const li = document.createElement("li");
    li.innerHTML = `<button class="item" type="button" aria-current="${item.id === currentId}">`
      + `<span class="pill p-blunder">${MARK[item.judgment]}</span>`
      + `<span class="mv">${esc(moveLabel(item.move_no, item.my_color) + item.played_san)}</span>`
      + statusPill(item.status, item.due_on)
      + `<span class="sub">${sourceTag(item.source)} <span class="opp">vs ${esc(item.opponent || "Unknown")}</span></span>`
      + `<span class="when">${when.join(" · ")}</span></button>`;
    li.firstChild.addEventListener("click", () => pick(item.id));
    ul.appendChild(li);
  }
}

function markCurrent() {
  const buttons = $("list").querySelectorAll(".item");
  items.forEach((item, i) => buttons[i]?.setAttribute("aria-current", String(item.id === currentId)));
}

async function pick(id) {
  history.replaceState(null, "", "#log/" + id);
  await select(id);
  if (window.matchMedia(NARROW).matches) $("detail").scrollIntoView({ block: "start" });
}

// ---------------------------------------------------------------- detail

async function select(id) {
  await flush();
  const token = ++detailToken;
  currentId = id;
  markCurrent();
  let data;
  try {
    data = await api(`/api/blunders/${id}`);
  } catch (err) {
    if (token !== detailToken) return;
    entry = null;
    $("detail").innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  if (token !== detailToken) return;
  entry = data;
  ply = positions(entry).blunder;
  renderDetail();
}

function renderNoEntry() {
  currentId = null;
  entry = null;
  $("detail").innerHTML = filtering()
    ? '<p class="empty">Pick an entry, or change the filters.</p>'
    : '<div class="empty"><p><b>No entries yet.</b></p>'
      + `<p>Import a PGN on the <a href="#import">Import</a> tab, or with <code>blunderbook import FILE.pgn</code>.</p>`
      + "<p>For one position with no PGN, use the FEN quick entry there, or <code>blunderbook fen</code>.</p></div>";
}

/** The positions the step controls go through, and which one comes before your move. */
function positions(e) {
  const moves = e.game.moves;
  if (!moves.length || moves[e.ply]?.uci !== e.played_uci) {
    return { fens: [e.fen_before], blunder: 0 }; // the stored game can't be read: just this position
  }
  return { fens: [e.game.start_fen, ...moves.map((m) => m.fen)], blunder: e.ply };
}

function renderDetail() {
  const e = entry, g = e.game, mark = MARK[e.judgment];
  const before = percent(e.chances_before), after = percent(e.chances_after);
  const mine = g.my_color === "white" ? g.white_elo : g.black_elo;
  const theirs = g.my_color === "white" ? g.black_elo : g.white_elo;
  const opening = g.opening || (g.source === "fen" ? "Position from a FEN" : "Opening not recorded");
  const meta = [
    `${g.my_color === "white" ? "White" : "Black"} vs ${esc(g.opponent || "Unknown")}${theirs ? " (" + theirs + ")" : ""}`,
    esc(opening),
  ];
  if (g.played_on) meta.push(esc(fmtDate(g.played_on)));
  const due = isDue(e.due_on) ? "<b>today</b>" : esc(fmtDate(e.due_on));
  $("detail").innerHTML = `
  <div class="detail">
    <div class="boardwrap">
      <div class="board" id="dBoard"></div>
      <div class="nav">
        <div class="grp">
          <button class="icon" type="button" id="nFirst" aria-label="Start of game">${ICON.first}</button>
          <button class="icon" type="button" id="nPrev" aria-label="Previous move">${ICON.prev}</button>
          <button class="icon" type="button" id="nNext" aria-label="Next move">${ICON.next}</button>
          <button class="icon" type="button" id="nBl" aria-label="Jump to the position before your move">${ICON.blunder}</button>
        </div>
        <span class="navlabel" id="navLabel" aria-live="polite"></span>
      </div>
      <label class="toggle"><input type="checkbox" id="tBest" ${showBest ? "checked" : ""}> Show best move on the board</label>
      <div class="legend"><span><i class="l-played"></i>Your move</span><span><i class="l-best"></i>Best move</span></div>
    </div>
    <div>
      <div class="head"><div>
        <h2>${esc(moveLabel(e.move_no, g.my_color))}<span class="bad">${esc(e.played_san + mark)}</span></h2>
        <div class="meta">${meta.join(" · ")}</div>
      </div></div>
      <div class="moves">
        <div class="mvbox bad"><div class="k">I played</div><div class="v">${esc(e.played_san)}</div><div class="line">Refutation: ${esc(e.refutation_san || "—")}</div></div>
        <div class="mvbox good"><div class="k">Best was</div><div class="v">${esc(e.best_san)}</div><div class="line">${esc(e.best_line_san)}</div></div>
      </div>
      <div class="evalrow">
        <div class="evalhead"><span>Your winning chances</span><span class="num">${before}% → <b class="bad-text">${after}%</b></span></div>
        <div class="bar" role="img" aria-label="Your winning chances fell from ${before}% to ${after}%"><div class="before" style="width:${before}%"></div><div class="after" style="width:${after}%"></div></div>
        <div class="small">Eval ${fmtEval(e.eval_before)} → ${fmtEval(e.eval_after)}, from White's side, like on Lichess.</div>
      </div>
      <div class="grid">
        <div class="cell"><div class="k">Source</div><div class="v">${esc(g.site_label || SOURCE_NAME[g.source])}</div></div>
        <div class="cell"><div class="k">Time control</div><div class="v">${na(timeControl(g.speed, g.tc_label))}</div></div>
        <div class="cell"><div class="k">Result</div><div class="v">${na(outcome(g.result, g.my_color))}</div></div>
        <div class="cell"><div class="k">Ratings</div><div class="v">Me ${na(mine)} · Opp ${na(theirs)}</div></div>
        <div class="cell"><div class="k">Clock left</div><div class="v">${na(fmtClock(e.clock_left_s))}</div></div>
        <div class="cell"><div class="k">Time on move</div><div class="v">${na(fmtSpent(e.time_spent_s))}</div></div>
      </div>
      ${!g.has_clocks && g.source !== "fen" ? `<p class="small note">No clock times in this PGN, so time-based causes aren't suggested.</p>` : ""}
      <div class="sec"><h3 id="causesTitle">Why it happened</h3><div id="causes"></div></div>
      <div class="sec"><label class="lbl" for="tThink">What I was thinking</label>
        <textarea id="tThink" placeholder="Write it while the game is fresh. Only you know this part.">${esc(e.thinking)}</textarea></div>
      <div class="sec"><label class="lbl" for="tLesson">Lesson — the rule I'll follow next time</label>
        <textarea id="tLesson" placeholder="One rule you can check during a game.">${esc(e.lesson)}</textarea>
        <div class="saved" id="savedMsg" aria-live="polite"></div></div>
      <div class="dfoot">
        <div class="rtrow">${statusPill(e.status, e.due_on)}<span class="small">Next re-test ${due}</span></div>
        <button class="btn ghost danger" type="button" id="delBtn">Delete this entry</button>
      </div>
    </div>
  </div>`;
  drawBoard();
  renderCauses();
  const pos = positions(e);
  const step = (to) => () => { ply = Math.max(0, Math.min(pos.fens.length - 1, to())); drawBoard(); };
  $("nFirst").onclick = step(() => 0);
  $("nPrev").onclick = step(() => ply - 1);
  $("nNext").onclick = step(() => ply + 1);
  $("nBl").onclick = step(() => pos.blunder);
  $("tBest").onchange = (ev) => { showBest = ev.target.checked; drawBoard(); };
  $("tThink").addEventListener("input", (ev) => edit("thinking", ev.target.value));
  $("tLesson").addEventListener("input", (ev) => edit("lesson", ev.target.value));
  $("delBtn").onclick = remove;
}

function drawBoard() {
  const e = entry, pos = positions(e), hl = {}, arrows = [];
  if (ply === pos.blunder) {
    const [f, t] = uciSquares(e.played_uci);
    hl[f] = hl[t] = "played";
    arrows.push({ from: f, to: t, color: "red" });
    if (showBest) {
      const [bf, bt] = uciSquares(e.best_uci);
      hl[bf] = hl[bt] = "best";
      arrows.push({ from: bf, to: bt, color: "green" });
    }
  } else if (ply > 0) {
    const [f, t] = uciSquares(e.game.moves[ply - 1].uci);
    hl[f] = hl[t] = ply === pos.blunder + 1 ? "played" : "sel";
  }
  const label = positionLabel(e, pos);
  renderBoard($("dBoard"), pos.fens[ply], e.game.my_color, { hl, arrows, label });
  $("navLabel").textContent = label;
  $("nFirst").disabled = $("nPrev").disabled = ply === 0;
  $("nNext").disabled = ply === pos.fens.length - 1;
}

function positionLabel(e, pos) {
  if (ply === pos.blunder) return `Position before your ${e.judgment}`;
  if (ply === 0) return "Start position";
  const m = e.game.moves[ply - 1];
  const text = moveLabel(m.move_no, m.color) + m.san;
  return ply === pos.blunder + 1 ? `After ${text}${MARK[e.judgment]}` : `After ${text}`;
}

function renderCauses() {
  const e = entry;
  const box = $("causes");
  const suggested = e.auto_causes.filter((c) => !e.causes.includes(c));
  box.innerHTML = '<div class="chips" role="group" aria-labelledby="causesTitle"></div>'
    + (suggested.length ? '<p class="small note">Dashed chips are suggested from the clock and the engine line. Tap to confirm.</p>' : "")
    + (e.causes.includes("Other")
      ? `<div class="other"><label class="lbl" for="tOther">Other cause</label><input class="text" id="tOther" type="text" placeholder="What else was it?" value="${esc(e.other_cause || "")}"></div>`
      : "");
  const chips = box.firstChild;
  for (const cause of CAUSES) {
    const on = e.causes.includes(cause), sug = !on && e.auto_causes.includes(cause);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (sug ? " sugg" : "");
    b.setAttribute("aria-pressed", String(on));
    b.innerHTML = esc(cause) + (sug ? ' <span class="auto">auto</span>' : "");
    b.addEventListener("click", () => toggleCause(cause));
    chips.appendChild(b);
  }
  $("tOther")?.addEventListener("input", (ev) => edit("other_cause", ev.target.value));
}

function toggleCause(cause) {
  const chosen = new Set(entry.causes);
  if (chosen.has(cause)) chosen.delete(cause);
  else chosen.add(cause);
  const causes = CAUSES.filter((c) => chosen.has(c)); // the fixed order, as the server keeps it
  entry.causes = causes;
  renderCauses();
  const pressed = [...$("causes").querySelectorAll(".chip")][CAUSES.indexOf(cause)];
  pressed?.focus();
  edit("causes", causes, { now: true });
}

// ---------------------------------------------------------------- saving

/** Note a change to your part of the entry. Text waits for a pause in typing; causes go now. */
function edit(field, value, { now = false } = {}) {
  entry[field] = value;
  unsaved.set(field, value);
  clearTimeout(saveTimer);
  if (now) flush();
  else saveTimer = setTimeout(flush, SAVE_DELAY_MS);
}

/** Send what's unsaved, after any save already on its way. Resolves when it's done. */
function flush() {
  clearTimeout(saveTimer);
  if (!unsaved.size || currentId === null) return saving;
  const id = currentId, body = Object.fromEntries(unsaved);
  unsaved.clear();
  saving = saving.then(async () => {
    try {
      await api(`/api/blunders/${id}`, { method: "PATCH", body });
      if (id === currentId) savedMessage("Saved");
    } catch (err) {
      if (id !== currentId) { toast("A note wasn't saved: " + err.message); return; }
      for (const [field, value] of Object.entries(body)) if (!unsaved.has(field)) unsaved.set(field, value);
      savedMessage("Not saved: " + err.message + " It will try again when you type.", true);
    }
  });
  return saving;
}

/** Closing the page: send what's left without waiting. */
function sendNow() {
  clearTimeout(saveTimer);
  if (!unsaved.size || currentId === null) return;
  api(`/api/blunders/${currentId}`, { method: "PATCH", body: Object.fromEntries(unsaved), keepalive: true }).catch(() => {});
  unsaved.clear();
}

let savedTimer = null;
function savedMessage(text, failed = false) {
  const msg = $("savedMsg");
  if (!msg) return;
  msg.textContent = text;
  msg.classList.toggle("fail", failed);
  clearTimeout(savedTimer);
  if (!failed) savedTimer = setTimeout(() => { msg.textContent = ""; }, 1200);
}

// ---------------------------------------------------------------- delete

async function remove() {
  const e = entry;
  const name = moveLabel(e.move_no, e.game.my_color) + e.played_san + MARK[e.judgment];
  if (!confirm(`Delete ${name} from your Log? Its game stays in the database, so importing it again won't bring it back.`)) return;
  await flush();
  try {
    await api(`/api/blunders/${e.id}`, { method: "DELETE" });
  } catch (err) {
    toast("Not deleted: " + err.message);
    return;
  }
  const at = items.findIndex((item) => item.id === e.id);
  await refreshList();
  entriesChanged();
  toast(`Deleted ${name} from your Log.`);
  const next = items[Math.min(Math.max(at, 0), items.length - 1)];
  if (next) {
    history.replaceState(null, "", "#log/" + next.id);
    await select(next.id);
  } else {
    history.replaceState(null, "", "#log");
    renderNoEntry();
  }
}
