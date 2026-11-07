// The Games tab (CLAUDE.md §11): every game you imported, clean ones too, grouped by the
// import they came from or listed by date, with filters. `#games/12` opens game 12: the board
// steps through the whole game, your blunders marked in the move list, linking to the Log.
//
// FEN quick entries aren't games: they're in the Log only.

import { api } from "../api.js";
import { renderBoard, uciSquares } from "../board.js";
import { MARK, SOURCE_NAME, SOURCE_TAG, fmtDate, isDue, localDay, moveLabel, timeControl } from "../format.js";
import { esc, showError } from "../ui.js";

const SEARCH_DELAY_MS = 250;
const RESULT = { won: ["W", "Won"], lost: ["L", "Lost"], drawn: ["D", "Drawn"] };
const ICON = {
  first: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3v10M12 3 7 8l5 5"/></svg>',
  prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 3 5 5-5 5"/></svg>',
  last: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v10M4 3l5 5-5 5"/></svg>',
  blunder: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg>',
};

let root = null;
let group = "import"; // "import" | "date"
let games = []; // the list, as last fetched
let detail = null; // the open game: {game, outcome, imported_at, batch, entries}
let ply = 0; // the position shown: 0 is the start, n is after n moves
let listScroll = 0; // where the list was, for "All games"
let listToken = 0, gameToken = 0; // only the newest answer is drawn
let searchTimer = null;

const $ = (id) => document.getElementById(id);
const na = (v) => (v == null || v === "" ? '<span class="na">—</span>' : esc(v));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export async function show(section, rest) {
  if (root !== section) build(section);
  const id = Number.parseInt(rest, 10);
  if (Number.isInteger(id)) {
    if ($("gList").offsetParent !== null) listScroll = window.scrollY;
    $("gListView").hidden = true;
    $("gGameView").hidden = false;
    await openGame(id);
  } else {
    detail = null;
    $("gGameView").hidden = true;
    $("gListView").hidden = false;
    await refreshList();
    window.scrollTo(0, listScroll);
  }
}

// ---------------------------------------------------------------- the list

function build(section) {
  root = section;
  const sources = Object.entries(SOURCE_NAME).filter(([v]) => v !== "fen");
  section.innerHTML = `
  <div id="gListView">
    <div class="panel gbar">
      <label class="sr" for="gSource">Source</label>
      <select id="gSource"><option value="">All sources</option>${sources.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select>
      <label class="sr" for="gResult">Result</label>
      <select id="gResult"><option value="">Any result</option><option value="won">Won</option><option value="lost">Lost</option><option value="drawn">Drawn</option></select>
      <label class="sr" for="gSpeed">Time control</label>
      <select id="gSpeed"><option value="">Any time control</option><option value="bullet">Bullet</option><option value="blitz">Blitz</option><option value="rapid">Rapid</option><option value="classical">Classical</option></select>
      <label class="sr" for="gBlunders">Blunders</label>
      <select id="gBlunders"><option value="">With or without blunders</option><option value="with">With blunders</option><option value="clean">Clean games</option></select>
      <label class="sr" for="gQuery">Search</label>
      <input class="text gsearch" id="gQuery" type="search" maxlength="100" placeholder="Opponent or opening">
      <div class="seg" role="group" aria-label="Group the games">
        <button type="button" id="gByImport" aria-pressed="true">By import</button>
        <button type="button" id="gByDate" aria-pressed="false">By date</button>
      </div>
    </div>
    <p class="gcount" id="gCount" aria-live="polite"></p>
    <div id="gList"></div>
  </div>
  <div id="gGameView" hidden></div>`;
  for (const id of ["gSource", "gResult", "gSpeed", "gBlunders"]) $(id).addEventListener("change", refreshList);
  $("gQuery").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refreshList, SEARCH_DELAY_MS);
  });
  $("gByImport").addEventListener("click", () => setGroup("import"));
  $("gByDate").addEventListener("click", () => setGroup("date"));
  section.addEventListener("keydown", stepWithKeys);
}

function setGroup(to) {
  group = to;
  $("gByImport").setAttribute("aria-pressed", String(to === "import"));
  $("gByDate").setAttribute("aria-pressed", String(to === "date"));
  renderList();
}

const filtering = () => ["gSource", "gResult", "gSpeed", "gBlunders"].some((id) => $(id).value) || $("gQuery").value.trim();

function query() {
  const params = new URLSearchParams();
  const pairs = { source: "gSource", result: "gResult", speed: "gSpeed", blunders: "gBlunders" };
  for (const [name, id] of Object.entries(pairs)) if ($(id).value) params.set(name, $(id).value);
  const q = $("gQuery").value.trim();
  if (q) params.set("q", q);
  const text = params.toString();
  return text ? "?" + text : "";
}

async function refreshList() {
  const token = ++listToken;
  let found;
  try {
    found = await api("/api/games" + query());
  } catch (err) {
    if (token !== listToken) return;
    showError(err.message);
    $("gList").innerHTML = '<p class="panel empty">Your games couldn\'t be loaded.</p>';
    return;
  }
  if (token !== listToken) return;
  showError(null);
  games = found;
  renderList();
}

/** Each game's import, or the day it was imported when it has none (older games). */
function groupOf(g) {
  if (g.batch) return { key: "i" + g.batch.id, label: g.batch.label, at: g.batch.started_at, kind: g.batch.kind };
  const day = localDay(g.imported_at);
  return { key: "d" + day, label: `Imported ${fmtDate(day) || "earlier"}`, at: g.imported_at, kind: null };
}

function renderList() {
  const box = $("gList");
  if (!games.length) {
    $("gCount").textContent = "";
    box.innerHTML = filtering()
      ? '<p class="panel empty">No games match these filters.</p>'
      : '<div class="panel empty"><p><b>No games yet.</b></p>'
        + '<p>Import a PGN on the <a href="#import">Import</a> tab, or with <code>blunderbook import FILE.pgn</code>.</p>'
        + "<p>Every game you import is listed here, clean ones too.</p></div>";
    return;
  }
  const groups = new Map();
  for (const g of games) {
    const k = group === "import" ? groupOf(g) : { key: "all" };
    if (!groups.has(k.key)) groups.set(k.key, { ...k, games: [] });
    const entry = groups.get(k.key);
    entry.games.push(g);
    if (k.at && k.at > entry.at) entry.at = k.at;
  }
  const ordered = [...groups.values()];
  if (group === "import") ordered.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  const imports = group === "import" ? ` from ${plural(ordered.length, "import", "imports")}` : "";
  $("gCount").textContent = plural(games.length, "game", "games") + imports;
  box.innerHTML = ordered.map((grp) => `
    <section class="panel ggroup" aria-label="${esc(grp.label || "Your games")}">
      ${group === "import" ? groupHead(grp) : ""}
      <ul class="glist">${grp.games.map(gameRow).join("")}</ul>
    </section>`).join("");
}

function groupHead(grp) {
  const counts = grp.games.reduce((n, g) => n + g.blunders, 0);
  const parts = [];
  if (grp.kind) parts.push(`imported ${esc(fmtDate(localDay(grp.at)) || "")}`);
  parts.push(plural(grp.games.length, "game", "games"));
  parts.push(counts ? plural(counts, "blunder", "blunders") : "no blunders");
  return `<div class="ghead"><h3>${esc(grp.label)}</h3><span class="small">${parts.join(" · ")}</span></div>`;
}

function marks(g) {
  const parts = [["blunders", "blunder"], ["mistakes", "mistake"], ["inaccuracies", "inaccuracy"]]
    .filter(([field]) => g[field])
    .map(([field, judgment]) => `${g[field]}${MARK[judgment]}`);
  return parts.length
    ? `<span class="pill p-blunder" aria-label="${esc(entriesLabel(g))}">${parts.join(" ")}</span>`
    : '<span class="pill p-solved">Clean</span>';
}

function entriesLabel(g) {
  return [["blunders", "blunder", "blunders"], ["mistakes", "mistake", "mistakes"], ["inaccuracies", "inaccuracy", "inaccuracies"]]
    .filter(([field]) => g[field])
    .map(([field, one, many]) => plural(g[field], one, many))
    .join(", ");
}

function resultBadge(outcome) {
  const [letter, word] = RESULT[outcome] || ["–", "Result unknown"];
  return `<span class="res ${outcome || "none"}" title="${word}"><span aria-hidden="true">${letter}</span><span class="sr">${word}</span></span>`;
}

function gameRow(g) {
  const elo = g.opponent_elo ? ` (${g.opponent_elo})` : "";
  const sub = [
    `<span class="src s-${esc(g.source)}">${esc(SOURCE_TAG[g.source] || g.source)}</span>`,
    esc(timeControl(g.speed, g.tc_label) || "No time control"),
    g.opening ? esc(g.opening) : null,
  ].filter(Boolean).join(" · ");
  const side = g.my_color === "white" ? "White" : "Black";
  return `<li><a class="grow" href="#games/${g.id}">
    ${resultBadge(g.outcome)}
    <span class="who"><span class="side ${g.my_color}" title="You played ${side}"></span><span class="sr">You played ${side}, </span>vs ${esc(g.opponent || "Unknown")}${esc(elo)}</span>
    <span class="marks">${marks(g)}</span>
    <span class="sub">${sub}</span>
    <span class="when">${esc(fmtDate(g.played_on) || "Date unknown")}</span>
  </a></li>`;
}

// ---------------------------------------------------------------- one game

async function openGame(id) {
  const token = ++gameToken;
  const view = $("gGameView");
  let data;
  try {
    data = await api(`/api/games/${id}`);
  } catch (err) {
    if (token !== gameToken) return;
    detail = null;
    view.innerHTML = `<div class="panel empty"><p>${esc(err.message)}</p><p><a href="#games">All games</a></p></div>`;
    return;
  }
  if (token !== gameToken) return;
  detail = data;
  ply = 0;
  renderGame();
  window.scrollTo(0, 0);
}

/** The plies of your entries: ply -> entry. */
const entryAt = () => new Map(detail.entries.map((e) => [e.ply, e]));

function renderGame() {
  const { game: g, entries } = detail;
  const mine = g.my_color === "white" ? g.white_elo : g.black_elo;
  const theirs = g.my_color === "white" ? g.black_elo : g.white_elo;
  const side = g.my_color === "white" ? "White" : "Black";
  const meta = [`You played ${side}`, g.opening ? esc(g.opening) + (g.eco ? ` (${esc(g.eco)})` : "") : "Opening not recorded"];
  if (g.played_on) meta.push(esc(fmtDate(g.played_on)));
  const from = detail.batch
    ? esc(detail.batch.label)
    : `Imported ${esc(fmtDate(localDay(detail.imported_at)) || "earlier")}`;
  $("gGameView").innerHTML = `
  <a class="gback" href="#games">← All games</a>
  <div class="panel detail">
    <div class="boardwrap">
      <div class="board" id="gBoard"></div>
      <div class="nav">
        <div class="grp">
          <button class="icon" type="button" id="gFirst" aria-label="Start of game">${ICON.first}</button>
          <button class="icon" type="button" id="gPrev" aria-label="Previous move">${ICON.prev}</button>
          <button class="icon" type="button" id="gNext" aria-label="Next move">${ICON.next}</button>
          <button class="icon" type="button" id="gLast" aria-label="End of game">${ICON.last}</button>
          <button class="icon" type="button" id="gNextBl" aria-label="Next of your mistakes">${ICON.blunder}</button>
        </div>
        <span class="navlabel" id="gLabel" aria-live="polite"></span>
      </div>
      <div class="legend"><span><i class="l-played"></i>Your mistake</span><span><i class="l-sel"></i>Last move</span></div>
    </div>
    <div>
      <div class="head"><div>
        <h2>${resultBadge(detail.outcome)} vs ${esc(g.opponent || "Unknown")}</h2>
        <div class="meta">${meta.join(" · ")}</div>
      </div></div>
      <div class="grid">
        <div class="cell"><div class="k">Source</div><div class="v">${esc(g.site_label || SOURCE_NAME[g.source])}</div></div>
        <div class="cell"><div class="k">Time control</div><div class="v">${na(timeControl(g.speed, g.tc_label))}</div></div>
        <div class="cell"><div class="k">Result</div><div class="v">${na(g.result)}${detail.outcome ? " · " + RESULT[detail.outcome][1] : ""}</div></div>
        <div class="cell"><div class="k">Ratings</div><div class="v">Me ${na(mine)} · Opp ${na(theirs)}</div></div>
        <div class="cell"><div class="k">Analysed with</div><div class="v">${na(g.engine_name)}${g.engine_depth ? " · depth " + g.engine_depth : ""}</div></div>
        <div class="cell"><div class="k">Imported from</div><div class="v">${from}</div></div>
      </div>
      <div class="sec"><h3>Your mistakes in this game</h3>${entriesHtml(entries, g)}</div>
      <div class="sec"><h3 id="gMovesTitle">Moves</h3>${movesHtml(g)}</div>
    </div>
  </div>`;
  const last = g.moves.length;
  const go = (to) => () => { ply = Math.max(0, Math.min(last, to())); drawGame(); };
  $("gFirst").onclick = go(() => 0);
  $("gPrev").onclick = go(() => ply - 1);
  $("gNext").onclick = go(() => ply + 1);
  $("gLast").onclick = go(() => last);
  $("gNextBl").onclick = go(nextMistake);
  for (const b of $("gGameView").querySelectorAll(".mbtn")) {
    b.addEventListener("click", () => { ply = Number(b.dataset.pos); drawGame(); });
  }
  drawGame();
}

function entriesHtml(entries, g) {
  if (!entries.length) {
    return `<p class="small">No blunders found${g.engine_depth ? ` at depth ${g.engine_depth}` : ""}.</p>`;
  }
  return '<ul class="gentries">' + entries.map((e) => `<li><a class="gentry" href="#log/${e.id}">
      <span class="pill p-blunder">${MARK[e.judgment]}</span>
      <span class="mv">${esc(moveLabel(e.move_no, g.my_color) + e.played_san)}</span>
      ${statusPill(e.status, e.due_on)}
      <span class="small">Open in the Log</span>
    </a></li>`).join("") + "</ul>";
}

function statusPill(status, dueOn) {
  if (status === "new") return '<span class="pill p-new">New</span>';
  if (isDue(dueOn)) return '<span class="pill p-due">Due</span>';
  return status === "solved" ? '<span class="pill p-solved">Solved</span>' : '<span class="pill p-missed">Missed</span>';
}

/** The move list in rows of a move number, White's move and Black's. Position i + 1 is
 *  after move i, so each button jumps to the position after its move. */
function movesHtml(g) {
  if (!g.moves.length) return '<p class="small">This game\'s moves can\'t be read.</p>';
  const marked = entryAt();
  const rows = [];
  for (const m of g.moves) {
    if (m.color === "white" || !rows.length) rows.push({ no: m.move_no, white: null, black: null });
    rows[rows.length - 1][m.color] = m;
  }
  const cell = (m) => {
    if (!m) return '<span class="mempty">…</span>';
    const e = marked.get(m.ply);
    const text = esc(m.san) + (e ? MARK[e.judgment] : "");
    return `<button type="button" class="mbtn${e ? " bad" : ""}" data-pos="${m.ply + 1}" aria-label="${esc(moveLabel(m.move_no, m.color) + m.san)}${e ? ", your " + e.judgment : ""}">${text}</button>`;
  };
  return `<ol class="mlist" aria-labelledby="gMovesTitle">${rows.map((r) => `<li><span class="no">${r.no}.</span>${cell(r.white)}${cell(r.black)}</li>`).join("")}</ol>`;
}

/** The position before your next mistake after this one, or the first again. */
function nextMistake() {
  const plies = detail.entries.map((e) => e.ply).sort((a, b) => a - b);
  if (!plies.length) return ply;
  return plies.find((p) => p > ply) ?? plies[0];
}

function drawGame() {
  const g = detail.game, marked = entryAt(), hl = {}, arrows = [];
  let label = "Start position";
  if (ply > 0) {
    const m = g.moves[ply - 1];
    const [f, t] = uciSquares(m.uci);
    const e = marked.get(m.ply);
    hl[f] = hl[t] = e ? "played" : "sel";
    if (e) arrows.push({ from: f, to: t, color: "red" });
    label = `After ${moveLabel(m.move_no, m.color)}${m.san}${e ? MARK[e.judgment] : ""}`;
  }
  const upcoming = marked.get(ply);
  if (upcoming) label += ` · your ${upcoming.judgment} comes next`;
  const fen = ply === 0 ? g.start_fen : g.moves[ply - 1].fen;
  renderBoard($("gBoard"), fen, g.my_color, { hl, arrows, label });
  $("gLabel").textContent = label;
  $("gFirst").disabled = $("gPrev").disabled = ply === 0;
  $("gNext").disabled = $("gLast").disabled = ply === g.moves.length;
  $("gNextBl").disabled = !detail.entries.length;
  for (const b of $("gGameView").querySelectorAll(".mbtn")) {
    b.setAttribute("aria-current", String(Number(b.dataset.pos) === ply));
  }
}

/** ← and → step through the game while it's open, unless you're typing. */
function stepWithKeys(ev) {
  if (!detail || $("gGameView").hidden || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) return;
  const last = detail.game.moves.length;
  const to = { ArrowLeft: ply - 1, ArrowRight: ply + 1, Home: 0, End: last }[ev.key];
  if (to === undefined) return;
  ev.preventDefault();
  ply = Math.max(0, Math.min(last, to));
  drawGame();
}
