// The Collection tab (ROADMAP 12.3): anyone's games, analysed like your own.
//   #collection                      the collections
//   #collection/<id>  (or /all)      a collection's stats, with filters in the query:
//                                    #collection/3?player=Paul%20Morphy&phase=opening
//   #collection/<id>/players         who played, and how well
//   #collection/game/<id>            one game: the board, the eval graph, every move judged,
//                                    and your Log entries from its positions
//   #collection/add  (?into=Classics) add games from a PGN, analysed on the server
//
// The API works everything out (the marks, accuracy, centipawn loss, winning chances and the
// FEN after every move), so there's no chess logic or maths here (as in core).

import { api } from "/js/api.js";
import { renderBoard, uciSquares } from "/js/board.js";
import { MARK, fmtDate, markText } from "/js/format.js";
import { esc, showError } from "/js/ui.js";

const FILTERS = ["player", "color", "result", "opening", "phase"];
const PHASE_NAME = { opening: "Opening", middlegame: "Middlegame", endgame: "Endgame" };
const JUDGMENT_NAME = { blunder: "Blunder", mistake: "Mistake", inaccuracy: "Inaccuracy" };
const HOW = "blunderbook collection import FILE --into NAME";
const PGN_TYPE = "application/x-chess-pgn";
const POLL_MS = 500;
const SAVED_JOB = "collection-import"; // the running import's id, to find it again on reload
const GAME_STATUS = {
  waiting: "Waiting", analysing: "Analysing…", added: "Added", added_known: "Added (already analysed)",
  member: "Skipped", duplicate: "Skipped", error: "Can't be read",
  not_analysed: "Not analysed",
};
const HEADLINE = { done: "Done", stopped: "Stopped", failed: "Stopped" };
const ICON = {
  first: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3v10M12 3 7 8l5 5"/></svg>',
  prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 3 5 5-5 5"/></svg>',
  last: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v10M4 3l5 5-5 5"/></svg>',
  mark: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg>',
};

let root = null;
let token = 0; // only the newest answer is drawn
let back = "#collection"; // where "← Back" goes from a game
let game = null; // the open game, as the API sent it
let ply = 0; // the position shown: 0 is the start, n is after n moves
let jobId = sessionStorage.getItem(SAVED_JOB); // the import shown on #collection/add
let pollTimer = null;

const $ = (id) => document.getElementById(id);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const num = (v) => (v == null ? "—" : String(Math.round(v)));
const pair = (a, b) => `${num(a)} · ${num(b)}`;

export async function show(section, rest) {
  if (root !== section) build(section);
  const [path, query = ""] = (rest || "").split("?");
  const parts = path.split("/").filter(Boolean);
  for (const part of ["colIndex", "colStats", "colPlayers", "colGame", "colAdd"]) $(part).hidden = true;
  if (parts[0] !== "add") clearTimeout(pollTimer);
  if (parts[0] === "add") {
    $("colAdd").hidden = false;
    await openAdd(new URLSearchParams(query).get("into") || "");
  } else if (parts[0] === "game" && parts[1]) {
    $("colGame").hidden = false;
    await openGame(parts[1]);
  } else if (parts[0] && parts[1] === "players") {
    back = location.hash;
    $("colPlayers").hidden = false;
    await openPlayers(parts[0]);
  } else if (parts[0]) {
    back = location.hash;
    $("colStats").hidden = false;
    await openStats(parts[0], new URLSearchParams(query));
  } else {
    back = "#collection";
    game = null;
    $("colIndex").hidden = false;
    await openIndex();
  }
}

function build(section) {
  root = section;
  section.innerHTML = '<div class="collection"><div id="colIndex"></div><div id="colStats" hidden></div>'
    + '<div id="colPlayers" hidden></div><div id="colGame" hidden></div><div id="colAdd" hidden></div></div>';
  section.addEventListener("keydown", stepWithKeys);
}

/** Ask the API; on a problem, say so in the error line and in `box`. */
async function load(url, box, mine) {
  try {
    const data = await api(url);
    if (mine === token) showError(null);
    return data;
  } catch (err) {
    if (mine !== token) return null;
    showError(err.message);
    box.innerHTML = `<p class="panel empty">${esc(err.message)}</p>`;
    return null;
  }
}

const nothingYet = () => `<div class="panel empty"><p>No collections yet.</p>
  <p>Add anyone's games here, or with <code>${HOW}</code>. Each game is analysed once, by the same Stockfish and rules as your own.</p>
  <p><a class="btn primary" href="#collection/add">Add games</a></p></div>`;

// ---------------------------------------------------------------- the collections

async function openIndex() {
  const mine = ++token;
  const box = $("colIndex");
  const data = await load(`/api/ext/collection/collections`, box, mine);
  if (!data || mine !== token) return;
  if (!data.collections.length) {
    box.innerHTML = nothingYet();
    return;
  }
  const rows = data.collections.map((c) => row(`#collection/${c.id}`, c.name, plural(c.games, "game", "games")));
  if (data.collections.length > 1) {
    rows.push(row("#collection/all", "All collections", `${plural(data.games, "game", "games")}, each once`));
  }
  box.innerHTML = `<p class="collection-intro">Anyone's games, analysed by the same Stockfish and the same thresholds as your Log. Nothing here goes into your Log.</p>
    <section class="panel collection-group" aria-labelledby="colListTitle">
      <div class="collection-head"><h3 id="colListTitle">Collections</h3><a class="btn ghost" href="#collection/add">Add games</a></div>
      <ul class="collection-list">${rows.join("")}</ul>
    </section>`;
}

const row = (href, name, sub) => `<li><a class="collection-row" href="${href}">
    <span class="collection-name">${esc(name)}</span><span class="small">${esc(sub)}</span></a></li>`;

// ---------------------------------------------------------------- a collection's stats

async function openStats(id, params) {
  const mine = ++token;
  const box = $("colStats");
  const query = new URLSearchParams({ collection: id });
  for (const key of FILTERS) if (params.get(key)) query.set(key, params.get(key));
  const data = await load(`/api/ext/collection/stats?${query}`, box, mine);
  if (!data || mine !== token) return;
  if (!data.total) {
    box.innerHTML = '<a class="gback" href="#collection">← All collections</a>' + nothingYet();
    return;
  }
  const f = Object.fromEntries(FILTERS.map((k) => [k, params.get(k) || ""]));
  const who = f.player ? data.labels[0] : null;
  const engines = data.engines.length ? `${esc(data.engines.join(", "))}, the same thresholds as your Log` : "";
  box.innerHTML = `
    <a class="gback" href="#collection">← All collections</a>
    <div class="collection-top">
      <div><h2>${esc(who || data.title)}</h2>
        <p class="meta">${who ? `In ${esc(data.title)} · ` : ""}${plural(data.total, "game", "games")}. ${engines}.</p></div>
      <div class="collection-buttons">
        ${data.collection != null ? `<a class="btn ghost" href="#collection/add?into=${encodeURIComponent(data.title)}">Add games</a>` : ""}
        <a class="btn ghost" href="#collection/${id}/players">Players</a>
      </div>
    </div>
    ${filterBar(data, f)}
    ${data.games ? statsBody(data, f) : `<p class="panel empty">No games${who ? ` of ${esc(who)}` : ""} with these filters.</p>`}`;
  for (const key of FILTERS) {
    const el = $(`colF-${key}`);
    if (el) el.addEventListener("change", () => setFilter(id, f, key, el.value));
  }
}

function setFilter(id, f, key, value) {
  const next = { ...f, [key]: value };
  // Won and lost are from a player's side; White and Black won are without one.
  const fits = next.player ? ["won", "lost", "drawn"] : ["white", "black", "drawn"];
  if (next.result && !fits.includes(next.result)) next.result = "";
  const query = new URLSearchParams();
  for (const k of FILTERS) if (next[k]) query.set(k, next[k]);
  location.hash = `#collection/${id}${query.size ? "?" + query : ""}`;
}

function select(key, label, options, value) {
  const opts = options.map(([v, text]) => `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(text)}</option>`).join("");
  return `<label class="collection-filter"><span class="sr">${label}</span><select id="colF-${key}">${opts}</select></label>`;
}

function filterBar(data, f) {
  const players = data.players.includes(f.player) || !f.player ? data.players : [f.player, ...data.players];
  const results = f.player
    ? [["", "Any result"], ["won", "Won"], ["lost", "Lost"], ["drawn", "Drawn"]]
    : [["", "Any result"], ["white", "White won"], ["black", "Black won"], ["drawn", "Drawn"]];
  const openings = data.opening_options.map((o) => [o.eco || o.name, [o.eco, o.name].filter(Boolean).join(" ")]);
  return `<div class="panel collection-filters">
    ${select("player", "Player", [["", "Any player"], ...players.map((p) => [p, p])], f.player)}
    ${select("color", "Colour", [["", f.player ? "Either colour" : "Both sides"], ["white", "White"], ["black", "Black"]], f.color)}
    ${select("result", "Result", results, f.result)}
    ${select("opening", "Opening", [["", "Any opening"], ...openings], f.opening)}
    ${select("phase", "Phase", [["", "Every phase"], ["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]], f.phase)}
  </div>`;
}

function statsBody(data, f) {
  const [a, b] = data.sides;
  const [la, lb] = data.labels;
  const one = Boolean(f.player || f.color); // only one side's marks count
  const blunders = one ? a.blunders : a.blunders + b.blunders;
  const moves = one ? a.moves : a.moves + b.moves;
  const s = data.score;
  const unfinished = s.unfinished ? ` · ${s.unfinished} unfinished` : "";
  const filtered = data.games !== data.total ? `of ${data.total}` : plural(data.players.length, "player", "players");
  return `
    <div class="collection-tiles">
      ${tile(data.games, "Games", filtered)}
      ${tile(`${s.won}–${s.drawn}–${s.lost}`, `${esc(la)}'s score`, `won · drawn · lost${unfinished}`)}
      ${tile(pair(a.accuracy, b.accuracy), "Accuracy", `${esc(la)} · ${esc(lb)}, the average per game`)}
      ${tile(pair(a.acpl, b.acpl), "Average centipawn loss", `${esc(la)} · ${esc(lb)}`)}
      ${tile(blunders, "Blunders", `In ${plural(moves, "move", "moves")}${one ? ` by ${esc(la)}` : ""}`, "collection-bad")}
    </div>
    <div class="collection-two">
      ${phasesPanel(data, one)}
      ${openingsPanel(data)}
    </div>
    ${gamesPanel(data)}`;
}

const tile = (value, title, sub, extra = "") => `<div class="panel collection-tile">
    <div class="collection-value ${extra}">${value}</div><div class="collection-label">${title}</div><div class="small">${sub}</div></div>`;

function marks(t) {
  const parts = [["blunders", "??", "collection-b"], ["mistakes", "?", "collection-m"], ["inaccuracies", "?!", "collection-i"]]
    .filter(([k]) => t[k])
    .map(([k, mark, cls]) => `<span class="${cls}">${t[k]}${mark}</span>`);
  if (!t.moves) return '<span class="small">—</span>';
  return parts.length ? parts.join(" ") : '<span class="collection-clean">Clean</span>';
}

function phasesPanel(data, one) {
  const top = Math.max(1, ...data.phases.map((p) => p.acpl || 0));
  const rows = data.phases.map((p) => {
    const name = `<span class="collection-phase">${PHASE_NAME[p.phase]} <span class="small">${plural(p.moves, "move", "moves")}</span></span>`;
    if (!p.moves) return `<div class="collection-prow">${name}<span class="small">No moves in this phase.</span><span></span></div>`;
    return `<div class="collection-prow">${name}
      <span class="collection-meter"><span class="collection-track"><span class="collection-fill" style="width:${Math.round(((p.acpl || 0) / top) * 100)}%"></span></span>
      <span class="collection-num">${num(p.acpl)} ACPL</span></span>
      <span class="collection-marks">${marks(p)}</span></div>`;
  });
  const whose = one ? `${esc(data.labels[0])}'s moves` : "both sides";
  return `<section class="panel collection-panel" aria-labelledby="colPhaseTitle">
    <div class="collection-title"><h3 id="colPhaseTitle">By phase</h3>
      <span class="small">Average centipawn loss, ${whose}. The opening is the first 10 moves; the endgame six pieces or fewer.</span></div>
    ${rows.join("")}</section>`;
}

function score(s) {
  return `${s.won}–${s.drawn}–${s.lost}`;
}

function openingsPanel(data) {
  const [a, b] = data.labels.map((l) => (data.labels[1] === "Opponents" ? l : l[0]));
  const rows = data.openings.map((o) => `<tr>
      <td><b>${esc(o.eco || "—")}</b></td>
      <td>${esc(o.name || "Not recorded")}${o.color ? ` <span class="small">as ${o.color === "white" ? "White" : "Black"}</span>` : ""}</td>
      <td class="collection-r">${o.sides[0].games}</td>
      <td class="collection-r">${score(o.score)}</td>
      <td class="collection-r">${pair(o.sides[0].accuracy, o.sides[1].accuracy)}</td></tr>`).join("");
  return `<section class="collection-panel collection-bare" aria-labelledby="colOpenTitle">
    <div class="collection-title"><h3 id="colOpenTitle">Openings</h3><span class="small">What was played, and how it went</span></div>
    <div class="panel collection-scroll"><table class="collection-table">
      <thead><tr><th scope="col">ECO</th><th scope="col">Opening</th><th scope="col" class="collection-r">Games</th>
      <th scope="col" class="collection-r">W–D–L</th><th scope="col" class="collection-r">Accuracy ${esc(a)} · ${esc(b)}</th></tr></thead>
      <tbody>${rows}</tbody></table></div></section>`;
}

function gamesPanel(data) {
  const rows = data.lines.map((g) => {
    const when = [g.event, g.date].filter(Boolean).map(esc).join(", ");
    const opening = [g.eco, plural(g.moves, "move", "moves")].filter(Boolean).map(esc).join(" · ");
    return `<tr>
      <td><a class="collection-game" href="#collection/game/${g.id}">${esc(g.white || "?")}</a><div class="small">vs ${esc(g.black || "?")}</div></td>
      <td><span class="collection-result">${esc(g.result || "*")}</span></td>
      <td>${esc(g.opening || "Opening not recorded")}<div class="small">${opening}</div></td>
      <td>${when || '<span class="small">—</span>'}</td>
      <td class="collection-r">${pair(g.by_side[0].accuracy, g.by_side[1].accuracy)}</td>
      <td>${marks(g.by_side[0])}<span class="small"> · </span>${marks(g.by_side[1])}</td></tr>`;
  }).join("");
  return `<section class="collection-panel collection-bare" aria-labelledby="colGamesTitle">
    <div class="collection-title"><h3 id="colGamesTitle">Games</h3><span class="small">In the order they were added. Open one for its eval graph and every move judged</span></div>
    <div class="panel collection-scroll"><table class="collection-table collection-wide">
      <thead><tr><th scope="col">Game</th><th scope="col">Result</th><th scope="col">Opening</th><th scope="col">Played</th>
      <th scope="col" class="collection-r">Accuracy W · B</th><th scope="col">Marks W · B</th></tr></thead>
      <tbody>${rows}</tbody></table></div></section>`;
}

// ---------------------------------------------------------------- players

async function openPlayers(id) {
  const mine = ++token;
  const box = $("colPlayers");
  const data = await load(`/api/ext/collection/players?collection=${encodeURIComponent(id)}`, box, mine);
  if (!data || mine !== token) return;
  const rows = data.players.map((p) => `<tr>
      <td><a class="collection-game" href="#collection/${id}?player=${encodeURIComponent(p.name)}">${esc(p.name)}</a></td>
      <td class="collection-r">${p.games}</td><td class="collection-r">${p.as_white}</td><td class="collection-r">${p.as_black}</td>
      <td class="collection-r">${score(p.score)}</td><td class="collection-r">${num(p.accuracy)}</td></tr>`).join("");
  box.innerHTML = `<a class="gback" href="#collection/${id}">← ${esc(data.title)}</a>
    <div class="collection-top"><div><h2>Players</h2><p class="meta">${esc(data.title)} · ${plural(data.players.length, "player", "players")}, most games first. Open one for their stats.</p></div></div>
    ${data.players.length ? `<div class="panel collection-scroll"><table class="collection-table">
      <thead><tr><th scope="col">Player</th><th scope="col" class="collection-r">Games</th><th scope="col" class="collection-r">White</th>
      <th scope="col" class="collection-r">Black</th><th scope="col" class="collection-r">W–D–L</th><th scope="col" class="collection-r">Accuracy</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : '<p class="panel empty">No player names in these games.</p>'}`;
}

// ---------------------------------------------------------------- one game

async function openGame(id) {
  const mine = ++token;
  const box = $("colGame");
  game = null;
  const data = await load(`/api/ext/collection/games/${encodeURIComponent(id)}`, box, mine);
  if (!data || mine !== token) return;
  game = data;
  ply = 0;
  renderGame();
}

function renderGame() {
  const g = game;
  const elo = (e) => (e ? ` (${e})` : "");
  const meta = [g.event, g.date, [g.eco, g.opening].filter(Boolean).join(" ")].filter(Boolean).map(esc);
  const sideRow = (name, t, cls) => `<tr><th scope="row"><span class="side ${cls}" aria-hidden="true"></span>${esc(name || "?")}</th>
    <td class="collection-r">${num(t.accuracy)}</td><td class="collection-r">${num(t.acpl)}</td><td>${marks(t)}</td></tr>`;
  const inc = g.collections.map((c) => `<a href="#collection/${c.id}">${esc(c.name)}</a>`).join(", ");
  $("colGame").innerHTML = `
  <a class="gback" href="${esc(back)}">← Back</a>
  <div class="panel detail">
    <div class="boardwrap">
      <div class="board" id="colBoard"></div>
      <div class="nav">
        <div class="grp">
          <button class="icon" type="button" id="colFirst" aria-label="Start of game">${ICON.first}</button>
          <button class="icon" type="button" id="colPrev" aria-label="Previous move">${ICON.prev}</button>
          <button class="icon" type="button" id="colNext" aria-label="Next move">${ICON.next}</button>
          <button class="icon" type="button" id="colLast" aria-label="End of game">${ICON.last}</button>
          <button class="icon" type="button" id="colNextMark" aria-label="Next marked move">${ICON.mark}</button>
        </div>
        <span class="navlabel" id="colLabel" aria-live="polite"></span>
      </div>
      <div class="collection-graphwrap">
        <div class="collection-graph" id="colGraph"></div>
        <p class="small">White's winning chances after each move: up is better for White. Click to jump there.</p>
      </div>
    </div>
    <div>
      <div class="head"><div>
        <h2>${esc(g.white || "?")}${elo(g.white_elo)} <span class="collection-vs">vs</span> ${esc(g.black || "?")}${elo(g.black_elo)}</h2>
        <div class="meta">${esc(g.result || "*")}${meta.length ? " · " + meta.join(" · ") : ""}</div>
      </div></div>
      <div class="sec"><div class="panel collection-scroll"><table class="collection-table">
        <thead><tr><th scope="col">Side</th><th scope="col" class="collection-r">Accuracy</th><th scope="col" class="collection-r">ACPL</th><th scope="col">Marks</th></tr></thead>
        <tbody>${sideRow(g.white, g.by_side[0], "white")}${sideRow(g.black, g.by_side[1], "black")}</tbody></table></div></div>
      <div class="sec" id="colMove" aria-live="polite"></div>
      ${yoursHtml(g)}
      <div class="sec"><h3 id="colMovesTitle">Moves</h3>${movesHtml(g)}</div>
      <p class="small collection-source">${esc(g.site_label)} · Analysed with ${esc(g.engine)} · In ${inc}</p>
    </div>
  </div>`;
  const last = g.moves.length;
  const go = (to) => () => jump(to());
  $("colFirst").addEventListener("click", go(() => 0));
  $("colPrev").addEventListener("click", go(() => ply - 1));
  $("colNext").addEventListener("click", go(() => ply + 1));
  $("colLast").addEventListener("click", go(() => last));
  $("colNextMark").addEventListener("click", go(nextMark));
  for (const b of $("colGame").querySelectorAll(".mbtn, .collection-here")) b.addEventListener("click", () => jump(Number(b.dataset.pos)));
  $("colGraph").addEventListener("click", (ev) => {
    const box = ev.currentTarget.getBoundingClientRect();
    jump(Math.round(((ev.clientX - box.left) / box.width) * last));
  });
  drawGame();
}

function jump(to) {
  ply = Math.max(0, Math.min(game.moves.length, to));
  drawGame();
}

/** The position after the next marked move, or the first again. */
function nextMark() {
  const marked = game.moves.filter((m) => m.judgment).map((m) => m.ply + 1);
  if (!marked.length) return ply;
  return marked.find((p) => p > ply) ?? marked[0];
}

/** Your Log entries whose position (before your move) comes up in this game. */
function yoursHtml(g) {
  if (!g.yours.length) return "";
  const items = g.yours.map((y) => {
    const when = [y.opponent ? `vs ${esc(y.opponent)}` : null, y.played_on ? esc(fmtDate(y.played_on)) : null].filter(Boolean).join(" · ");
    return `<li class="collection-mine">
      <a href="#log/${y.id}"><b>${esc(y.label)}${markText(y.judgment)}</b></a>
      <span class="small">${when || "Your game"}</span>
      <button class="btn ghost collection-here" type="button" data-pos="${y.ply}">Show it here</button></li>`;
  }).join("");
  return `<div class="sec"><h3>From your Log</h3>
    <p class="small">You reached a position of this game in your own games, and went wrong there.</p>
    <ul class="collection-yours">${items}</ul></div>`;
}

function movesHtml(g) {
  if (!g.moves.length) return '<p class="small">No moves.</p>';
  const rows = [];
  for (const m of g.moves) {
    if (m.color === "white" || !rows.length) rows.push({ no: m.move_no, white: null, black: null });
    rows[rows.length - 1][m.color] = m;
  }
  const cell = (m) => {
    if (!m) return '<span class="mempty">…</span>';
    const name = m.judgment ? `, ${m.judgment}` : "";
    return `<button type="button" class="mbtn${m.judgment ? " bad" : ""}" data-pos="${m.ply + 1}" aria-label="${esc(m.label + name)}">${esc(m.san)}${m.judgment ? MARK[m.judgment] : ""}</button>`;
  };
  return `<ol class="mlist" aria-labelledby="colMovesTitle">${rows.map((r) => `<li><span class="no">${r.no}.</span>${cell(r.white)}${cell(r.black)}</li>`).join("")}</ol>`;
}

function drawGame() {
  const g = game, hl = {}, arrows = [];
  const m = ply > 0 ? g.moves[ply - 1] : null;
  let label = "Start position";
  if (m) {
    const [f, t] = uciSquares(m.uci);
    hl[f] = hl[t] = m.judgment ? "played" : "sel";
    if (m.judgment) arrows.push({ from: f, to: t, color: "red" });
    label = `After ${m.label}${m.judgment ? MARK[m.judgment] : ""}`;
  }
  renderBoard($("colBoard"), g.positions[ply].fen, "white", { hl, arrows, label });
  $("colLabel").textContent = label;
  $("colFirst").disabled = $("colPrev").disabled = ply === 0;
  $("colNext").disabled = $("colLast").disabled = ply === g.moves.length;
  for (const b of $("colGame").querySelectorAll(".mbtn")) b.setAttribute("aria-current", String(Number(b.dataset.pos) === ply));
  $("colMove").innerHTML = moveBox(m);
  $("colGraph").innerHTML = graph(g);
}

function moveBox(m) {
  if (!m) return '<p class="small">Step through the game, or open a marked move from the graph or the list.</p>';
  const eval_ = evalText(game.positions[m.ply + 1].eval);
  const facts = `${eval_} after it · accuracy ${num(m.accuracy)} · lost ${m.cp_loss} cp`;
  if (!m.judgment) return `<div class="collection-move"><b>${esc(m.label)}</b> <span class="small">${facts}</span></div>`;
  return `<div class="collection-move collection-marked">
    <div><b>${esc(m.label)}${MARK[m.judgment]}</b> <span class="pill p-blunder">${JUDGMENT_NAME[m.judgment]}</span> <span class="small">${facts}</span></div>
    ${m.best_san ? `<div>Best was <b>${esc(m.best_san)}</b>${m.best_line ? `: ${esc(m.best_line)}` : ""}</div>` : ""}
    ${m.refutation ? `<div class="small">After it: ${esc(m.refutation)}</div>` : ""}
  </div>`;
}

/** White POV, like Lichess: {cp: 36} -> "+0.36", {mate: -2} -> "−M2". */
function evalText(ev) {
  if ("mate" in ev) return ev.mate === 0 ? "Mate" : (ev.mate > 0 ? "+" : "−") + "M" + Math.abs(ev.mate);
  const v = ev.cp / 100;
  return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
}

/** The eval graph: White's winning chances after each move, the marked moves as dots,
 *  and a line at the position shown. */
function graph(g) {
  const W = 600, H = 120, n = Math.max(1, g.positions.length - 1);
  const x = (i) => ((i / n) * W).toFixed(1);
  const y = (c) => ((1 - c) * H).toFixed(1);
  const line = g.positions.map((p, i) => `${x(i)},${y(p.chances)}`).join(" ");
  const dots = g.moves.filter((m) => m.judgment).map((m) => {
    const p = g.positions[m.ply + 1];
    return `<circle class="collection-dot collection-dot-${m.judgment}" cx="${x(m.ply + 1)}" cy="${y(p.chances)}" r="4"/>`;
  }).join("");
  const label = `White's winning chances through the game, ${plural(g.moves.filter((m) => m.judgment).length, "marked move", "marked moves")}`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
    <rect class="collection-black" x="0" y="0" width="${W}" height="${H}"/>
    <polygon class="collection-white" points="0,${H} ${line} ${W},${H}"/>
    <line class="collection-mid" x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}"/>
    <line class="collection-now" x1="${x(ply)}" y1="0" x2="${x(ply)}" y2="${H}"/>
    ${dots}</svg>`;
}

function stepWithKeys(ev) {
  if (!game || $("colGame").hidden || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) return;
  const to = { ArrowLeft: ply - 1, ArrowRight: ply + 1, Home: 0, End: game.moves.length }[ev.key];
  if (to === undefined) return;
  ev.preventDefault();
  jump(to);
}

// ---------------------------------------------------------------- adding games

async function openAdd(into) {
  const mine = ++token;
  const box = $("colAdd");
  let names = [];
  try {
    names = (await api("/api/ext/collection/collections")).collections.map((c) => c.name);
  } catch (err) {
    showError(err.message);
  }
  if (mine !== token) return;
  box.innerHTML = `
    <a class="gback" href="#collection">← All collections</a>
    <div class="panel collection-add">
      <h2>Add games</h2>
      <p class="small">From any PGN file, anyone's games. Stockfish analyses every move of both players, at your engine depth, with the same rules as your Log. A game already analysed isn't analysed again, and games already in the collection are skipped. Nothing goes into your Log.</p>
      <label class="collection-lbl" for="colInto">Collection</label>
      <input class="collection-input" id="colInto" type="text" list="colNames" maxlength="60" autocomplete="off" placeholder="A new name, or one you have" value="${esc(into)}">
      <datalist id="colNames">${names.map((n) => `<option value="${esc(n)}"></option>`).join("")}</datalist>
      <div class="collection-drop" id="colDrop">
        <label class="collection-lbl" for="colPgn">PGN</label>
        <textarea id="colPgn" spellcheck="false" placeholder="Paste PGN here, or drop a .pgn file on this box."></textarea>
      </div>
      <div class="collection-actions">
        <span class="btn ghost collection-file">Choose .pgn file<input type="file" id="colFile" accept=".pgn,.txt,${PGN_TYPE}" aria-label="Choose a PGN file"></span>
        <button class="btn primary" id="colGo" type="button">Add games</button>
      </div>
      <p class="collection-err" id="colErr" role="alert"></p>
    </div>
    <div id="colJob"></div>`;
  $("colGo").addEventListener("click", () => {
    const text = $("colPgn").value;
    if (!text.trim()) {
      $("colErr").textContent = "Paste a PGN first, or choose a file.";
      return;
    }
    startImport(new Blob([text], { type: PGN_TYPE }));
  });
  $("colFile").addEventListener("change", (ev) => {
    const file = ev.target.files[0];
    ev.target.value = ""; // the same file can be chosen again
    if (file) startImport(file);
  });
  const drop = $("colDrop");
  drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("collection-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("collection-over"));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    drop.classList.remove("collection-over");
    const file = ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (file) startImport(file);
  });
  if (jobId) await poll();
}

async function startImport(data) {
  const into = $("colInto").value.trim();
  $("colErr").textContent = "";
  if (!into) {
    $("colErr").textContent = "Give the collection a name.";
    $("colInto").focus();
    return;
  }
  showError(null);
  $("colGo").disabled = true;
  try {
    const started = await api(`/api/ext/collection/import?into=${encodeURIComponent(into)}`, { method: "POST", data, type: PGN_TYPE });
    jobId = started.job_id;
    sessionStorage.setItem(SAVED_JOB, jobId);
    await poll();
    $("colJob").scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (err) {
    $("colErr").textContent = err.message;
  } finally {
    $("colGo").disabled = false;
  }
}

async function poll() {
  clearTimeout(pollTimer);
  if (!$("colJob") || $("colAdd").hidden) return;
  let job;
  try {
    job = await api(`/api/ext/collection/import/${encodeURIComponent(jobId)}`);
  } catch (err) {
    if (err.status === 404) { // from before the server restarted
      jobId = null;
      sessionStorage.removeItem(SAVED_JOB);
      return;
    }
    showError(err.message);
    pollTimer = setTimeout(poll, POLL_MS * 4);
    return;
  }
  renderJob(job);
  if (job.status === "running") pollTimer = setTimeout(poll, POLL_MS);
}

function renderJob(job) {
  const running = job.status === "running";
  const state = running
    ? job.game_index
      ? `Analysing game ${job.game_index} of ${job.games_to_analyse} · ${job.percent}%`
      : "Starting…"
    : HEADLINE[job.status];
  const rows = job.games.map((g) => {
    const name = g.game_id != null ? `<a href="#collection/game/${g.game_id}">${esc(g.players)}</a>` : esc(g.players);
    const why = g.reason ? `<div class="small">${esc(g.reason)}</div>` : "";
    const warn = g.warnings.map((w) => `<div class="small">Note: ${esc(w)}</div>`).join("");
    return `<li class="collection-jrow"><span>Game ${g.number} · ${name}${why}${warn}</span>
      <span class="collection-jstatus collection-js-${g.status}">${GAME_STATUS[g.status]}</span></li>`;
  }).join("");
  const notes = job.notes.map((n) => `<p class="small">Note: ${esc(n)}</p>`).join("");
  const foot = running ? "" : `
    ${job.error ? `<p class="collection-err">${esc(job.error)}</p>` : ""}
    ${notes}
    <p><b>${esc(job.summary)}</b>${job.created ? ` · New collection: ${esc(job.collection)}` : ""}</p>
    ${job.collection_id != null ? `<div class="collection-actions"><a class="btn ghost" href="#collection/${job.collection_id}">Open ${esc(job.collection)}</a></div>` : ""}`;
  $("colJob").innerHTML = `<section class="panel collection-job" aria-labelledby="colJobTitle">
    <div class="collection-title"><h3 id="colJobTitle">Into ${esc(job.collection)}</h3>
      <span class="small" aria-live="polite">${esc(state)}${job.engine_name ? ` · ${esc(job.engine_name)}` : ""}</span></div>
    ${running ? `<div class="collection-prog" role="progressbar" aria-label="Import progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${job.percent}"><span class="collection-bar" style="width:${job.percent}%"></span></div>` : ""}
    <ul class="collection-jlist">${rows}</ul>${foot}</section>`;
}
