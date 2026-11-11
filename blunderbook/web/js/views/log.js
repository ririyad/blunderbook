// The Log view, ported from the demo (CLAUDE.md §11): filters and list on the left; on the
// right the board with step controls, I played / Best was, the eval bar, the game's details,
// cause chips and your notes, which save as you type.
//
// `#log/12` opens entry 12, and the filters are in the address too
// (`#log/12?status=due&cause=…&notes=missing`), so a link or a reload keeps them. Picking an
// entry or a filter updates the address without adding to history.

import { api } from "../api.js";
import { renderBoard, uciSquares } from "../board.js";
import { CAUSES } from "../causes.js";
import { showExplanation } from "../explain.js";
import {
  JUDGMENT_WORD, MARK, SOURCE_NAME, SOURCE_TAG, fmtClock, fmtDate, fmtEval, fmtSpent, isDue, moveLabel,
  markPill, outcome, percent, statusPill, timeControl,
} from "../format.js";
import { bindSteps, stepsHtml } from "../steps.js";
import { entriesChanged, esc, showError, toast } from "../ui.js";

const SAVE_DELAY_MS = 400;
const NARROW = "(max-width: 900px)"; // one column: the detail is under the list

let root = null; // the view's section, once built
let items = []; // the list, as last fetched
let currentId = null; // the entry in the detail panel
let entry = null; // its full data, with your unsaved edits applied
let ply = 0; // the position shown: 0 is the start, n is after n moves
let showBest = false;
let steps = null; // the step controls under the board
let listToken = 0, detailToken = 0; // only the newest answer is drawn

// Notes waiting to be saved: field -> value. Saves go one at a time, in order.
const unsaved = new Map();
let saveTimer = null;
let saving = Promise.resolve();

const $ = (id) => document.getElementById(id);
const na = (v) => (v == null || v === "" ? '<span class="na">—</span>' : esc(v));

export async function show(section, rest) {
  if (root !== section) build(section);
  const [path, asked] = (rest || "").split("?");
  if (asked !== undefined) setFilters(new URLSearchParams(asked)); // none given: they stay
  const wanted = Number.parseInt(path, 10);
  if (!(await refreshList())) {
    $("detail").replaceChildren();
    return;
  }
  let id = Number.isInteger(wanted) ? wanted : currentId;
  // A link with filters and no entry (from Patterns) opens the first one that matches.
  if (id === null || (!Number.isInteger(wanted) && asked !== undefined && !items.some((item) => item.id === id))) {
    id = items[0]?.id ?? null;
  }
  history.replaceState(null, "", address(id));
  if (id === null) renderNoEntry();
  else await select(id);
}

/** The address of entry `id` (or of the list) with the filters that are set. */
function address(id) {
  const params = new URLSearchParams();
  for (const [name, el] of [["source", "fSource"], ["status", "fStatus"], ["cause", "fCause"]]) {
    if ($(el).value) params.set(name, $(el).value);
  }
  if (notesOnly()) params.set("notes", "missing");
  const text = params.toString();
  return "#log" + (id === null ? "" : "/" + id) + (text ? "?" + text : "");
}

/** Set the filters from an address. One that isn't given, or isn't a choice, is cleared. */
function setFilters(params) {
  for (const [name, el] of [["source", "fSource"], ["status", "fStatus"], ["cause", "fCause"]]) {
    const value = params.get(name) || "";
    $(el).value = [...$(el).options].some((o) => o.value === value) ? value : "";
  }
  $("fNotes").setAttribute("aria-pressed", String(params.get("notes") === "missing"));
}

const notesOnly = () => $("fNotes").getAttribute("aria-pressed") === "true";

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
        <button class="chip fnotes" type="button" id="fNotes" aria-pressed="false" title="Entries with no confirmed cause or no lesson yet">Needs your notes</button>
      </div>
      <p class="count" id="count" aria-live="polite"></p>
      <ul class="list" id="list" aria-label="Entries"></ul>
    </aside>
    <article class="panel" id="detail" aria-label="Entry"></article>
  </div>`;
  const filtered = async () => {
    if (!(await refreshList())) return;
    if (currentId === null && items.length) await select(items[0].id);
    else renderPager();
    history.replaceState(null, "", address(currentId));
  };
  for (const id of ["fSource", "fStatus", "fCause"]) $(id).addEventListener("change", filtered);
  $("fNotes").addEventListener("click", () => {
    $("fNotes").setAttribute("aria-pressed", String(!notesOnly()));
    filtered();
  });
  window.addEventListener("pagehide", sendNow);
}

const options = (names) =>
  Object.entries(names).map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join("");

const filtering = () => ["fSource", "fStatus", "fCause"].some((id) => $(id).value) || notesOnly();

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
  if (notesOnly()) params.set("notes", "missing");
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
    if (item.needs_notes) when.push('<span class="todo">needs notes</span>');
    const li = document.createElement("li");
    li.innerHTML = `<button class="item" type="button" aria-current="${item.id === currentId}">`
      + markPill(item.judgment)
      + `<span class="mv">${esc(moveLabel(item.move_no, item.my_color) + item.played_san)}</span>`
      + statusPill(item.status, item.due_on)
      + `<span class="sub">${sourceTag(item.source)} <span class="opp">vs ${esc(item.opponent || "Unknown")}</span></span>`
      + `<span class="when">${when.join(" · ")}</span></button>`;
    li.firstChild.addEventListener("click", () => pick(item.id));
    ul.appendChild(li);
  }
}

/** Mark the open entry in the list, and bring it into view there (the list scrolls on its
 *  own, so the page doesn't move). */
function markCurrent() {
  const ul = $("list"), buttons = ul.querySelectorAll(".item");
  items.forEach((item, i) => buttons[i]?.setAttribute("aria-current", String(item.id === currentId)));
  const at = items.findIndex((item) => item.id === currentId);
  if (at < 0 || !buttons[at] || ul.scrollHeight <= ul.clientHeight) return;
  const row = buttons[at].getBoundingClientRect(), box = ul.getBoundingClientRect();
  if (row.top < box.top) ul.scrollTop -= box.top - row.top + 6;
  else if (row.bottom > box.bottom) ul.scrollTop += row.bottom - box.bottom + 6;
}

async function pick(id) {
  history.replaceState(null, "", address(id));
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

/** Previous / Next over the list as it's filtered, and "3 of 12". */
function renderPager() {
  const box = $("pager");
  if (!box || !entry) return;
  const at = items.findIndex((item) => item.id === entry.id);
  const to = (i, label) => {
    const item = items[i];
    return `<button class="btn ghost" type="button" data-id="${item ? item.id : ""}" ${item ? "" : "disabled"}>${label}</button>`;
  };
  box.innerHTML = at < 0
    ? '<span class="small">Not in the list: it doesn\'t match the filters.</span>'
    : `${to(at - 1, "← Previous")}<span class="small" aria-live="polite">${at + 1} of ${items.length}</span>${to(at + 1, "Next →")}`;
  for (const b of box.querySelectorAll("button[data-id]")) {
    if (b.dataset.id) b.addEventListener("click", () => pick(Number(b.dataset.id)));
  }
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
  <nav class="pager" id="pager" aria-label="Entries in the list"></nav>
  <div class="detail">
    <div class="boardwrap">
      <div class="board" id="dBoard"></div>
      ${stepsHtml("n", { mark: "Jump to the position before your move" })}
      <label class="toggle"><input type="checkbox" id="tBest" ${showBest ? "checked" : ""}> Show best move on the board</label>
      <div class="legend"><span><i class="l-played"></i>Your move</span><span><i class="l-best"></i>Best move</span></div>
    </div>
    <div>
      <div class="head"><div>
        <h2>${esc(moveLabel(e.move_no, g.my_color))}<span class="bad">${esc(e.played_san + mark)}</span>${e.judgment === "missed" ? " " + markPill("missed") : ""}</h2>
        <div class="meta">${meta.join(" · ")}</div>
      </div>${g.source !== "fen" ? `<a class="btn ghost" href="#games/${g.id}">See the whole game</a>` : ""}</div>
      <div class="moves">
        <div class="mvbox bad"><div class="k">I played</div><div class="v">${esc(e.played_san)}</div><div class="line">Refutation: ${esc(e.refutation_san || "—")}</div></div>
        <div class="mvbox good"><div class="k">Best was</div><div class="v">${esc(e.best_san)}</div><div class="line">${esc(e.best_line_san)}</div></div>
      </div>
      <div class="ai" id="explain"></div>
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
        <div class="delask" id="delBox"><button class="btn ghost danger" type="button" id="delBtn">Delete this entry</button></div>
      </div>
    </div>
  </div>`;
  const pos = positions(e);
  steps = bindSteps("n", {
    last: () => pos.fens.length - 1,
    get: () => ply,
    set: (to) => { ply = to; drawBoard(); },
    mark: () => pos.blunder,
  });
  drawBoard();
  renderCauses();
  renderPager();
  showExplanation($("explain"), e.id, e.explanation, e.judgment);
  $("tBest").onchange = (ev) => { showBest = ev.target.checked; drawBoard(); };
  $("tThink").addEventListener("input", (ev) => edit("thinking", ev.target.value));
  $("tLesson").addEventListener("input", (ev) => edit("lesson", ev.target.value));
  $("delBtn").addEventListener("click", askDelete);
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
  $("nLabel").textContent = label;
  steps.sync();
}

function positionLabel(e, pos) {
  if (ply === pos.blunder) return `Position before your ${JUDGMENT_WORD[e.judgment]}`;
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
  savedMessage("Saving…");
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
      if (id === currentId && !unsaved.size) savedMessage("Saved");
      if (id === currentId) noteWritten();
    } catch (err) {
      if (id !== currentId) { toast("A note wasn't saved: " + err.message); return; }
      for (const [field, value] of Object.entries(body)) if (!unsaved.has(field)) unsaved.set(field, value);
      savedMessage("Not saved: " + err.message, true);
    }
  });
  return saving;
}

/** The list's "needs notes" follows what you just wrote: a cause and a lesson clear it. */
function noteWritten() {
  const item = items.find((i) => i.id === entry.id);
  const needs = !entry.causes.length || !entry.lesson.trim();
  if (!item || item.needs_notes === needs) return;
  item.needs_notes = needs;
  const top = $("list").scrollTop;
  renderList();
  $("list").scrollTop = top;
}

/** Closing the page: send what's left without waiting. */
function sendNow() {
  clearTimeout(saveTimer);
  if (!unsaved.size || currentId === null) return;
  api(`/api/blunders/${currentId}`, { method: "PATCH", body: Object.fromEntries(unsaved), keepalive: true }).catch(() => {});
  unsaved.clear();
}

/** The save line under your notes: "Saving…", then "Saved" until the next change. A save
 *  that failed stays in red, with "Try again". */
function savedMessage(text, failed = false) {
  const msg = $("savedMsg");
  if (!msg) return;
  msg.textContent = text;
  msg.classList.toggle("fail", failed);
  if (!failed) return;
  const again = document.createElement("button");
  again.type = "button";
  again.className = "btn ghost";
  again.textContent = "Try again";
  again.addEventListener("click", () => { savedMessage("Saving…"); flush(); });
  msg.append(" ", again);
}

// ---------------------------------------------------------------- delete

const entryName = (e) => moveLabel(e.move_no, e.game.my_color) + e.played_san + MARK[e.judgment];

/** "Delete this entry" asks in its own place: Delete or Keep (Escape keeps). */
function askDelete() {
  const box = $("delBox");
  box.innerHTML = `<span role="group" aria-label="Delete this entry?">
      <span class="small">Delete ${esc(entryName(entry))} from your Log? Its game stays, so importing it again won't bring it back.</span>
      <button class="btn danger" type="button" id="delYes">Delete</button>
      <button class="btn ghost" type="button" id="delNo">Keep</button>
    </span>`;
  const keep = () => {
    box.innerHTML = '<button class="btn ghost danger" type="button" id="delBtn">Delete this entry</button>';
    $("delBtn").addEventListener("click", askDelete);
    $("delBtn").focus();
  };
  $("delNo").addEventListener("click", keep);
  $("delYes").addEventListener("click", remove);
  box.onkeydown = (ev) => { if (ev.key === "Escape" && $("delNo")) keep(); };
  $("delNo").focus();
}

async function remove() {
  const e = entry;
  const name = entryName(e);
  $("delYes").disabled = true;
  await flush();
  try {
    await api(`/api/blunders/${e.id}`, { method: "DELETE" });
  } catch (err) {
    toast("Not deleted: " + err.message);
    if ($("delYes")) $("delYes").disabled = false;
    return;
  }
  const at = items.findIndex((item) => item.id === e.id);
  await refreshList();
  entriesChanged();
  toast(`Deleted ${name} from your Log.`);
  const next = items[Math.min(Math.max(at, 0), items.length - 1)];
  history.replaceState(null, "", address(next ? next.id : null));
  if (next) await select(next.id);
  else renderNoEntry();
}
