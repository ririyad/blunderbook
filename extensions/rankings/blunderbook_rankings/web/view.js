// The Rankings tab (ROADMAP 16.3): the FIDE, Lichess and Chess.com top lists.
//   #rankings  or  #rankings/fide?speed=blitz&list=women&fed=NOR
//   #rankings/lichess?board=blitz
//   #rankings/chesscom?board=live_blitz
//
// The lists are downloaded only when you press Update (or run `blunderbook rankings
// update`). Only the latest list of each is kept; the
// players' profile links come from the API too.

import { api } from "/js/api.js";
import { fmtDate, localDay } from "/js/format.js";
import { esc, showError } from "/js/ui.js";

const SOURCES = [["fide", "FIDE"], ["lichess", "Lichess"], ["chesscom", "Chess.com"]];
const COMMAND = "blunderbook rankings update";
const POLL_MS = 500;
const HEADLINE = { done: "Done.", stopped: "Stopped.", failed: "The update stopped." };

let root = null;
let token = 0; // only the newest answer is drawn
let current = "fide"; // the sub-tab shown
let status = null; // the last /status answer
let jobId = null; // the update being followed
let pollTimer = null;

const $ = (id) => document.getElementById(id);
const when = (timestamp) => fmtDate(localDay(timestamp));
const signed = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "0");

export async function show(section, rest) {
  if (root !== section) build(section);
  const [path, query = ""] = (rest || "").split("?");
  current = SOURCES.some(([key]) => key === path) ? path : "fide";
  for (const link of root.querySelectorAll(".rankings-tab")) {
    if (link.dataset.source === current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const mine = ++token;
  await Promise.all([loadStatus(), loadList(new URLSearchParams(query), mine)]);
}

function build(section) {
  root = section;
  const tabs = SOURCES.map(([key, name]) => `<a class="rankings-tab" href="#rankings/${key}" data-source="${key}">${name}</a>`).join("");
  section.innerHTML = `<div class="rankings">
    <p class="rankings-intro">The top players of FIDE (the official world ratings), Lichess and Chess.com. They're downloaded only when you press Update, and only what changed.</p>
    <nav class="rankings-tabs" aria-label="Rankings">${tabs}</nav>
    <div class="panel rankings-bar">
      <div class="rankings-source" id="rkSource"></div>
      <div class="rankings-update">
        <span class="rankings-progress" id="rkProgress" role="status" aria-live="polite"></span>
        <span class="rankings-track" id="rkTrack" hidden><span class="rankings-fill" id="rkFill"></span></span>
        <button class="btn primary" id="rkUpdate" type="button">Update</button>
      </div>
    </div>
    <div class="panel rankings-report" id="rkReport" hidden></div>
    <div id="rkList"></div>
  </div>`;
  $("rkUpdate").addEventListener("click", startUpdate);
}

// ---------------------------------------------------------------- status and the Update button

async function loadStatus() {
  try {
    status = await api("/api/ext/rankings/status");
  } catch (err) {
    showError(err.message);
    return;
  }
  drawSource();
  if (status.job_id && !jobId) {
    jobId = status.job_id; // an update running since before a reload
    poll();
  }
}

function drawSource() {
  if (!status) return;
  const s = status.sources.find((x) => x.source === current);
  const name = s.list_label ? `${s.title}: ${s.list_label} lists` : s.title;
  const lines = [`<strong>${esc(name)}</strong>`];
  const downloaded = s.fetched_at ? when(s.fetched_at) : null;
  const checked = s.checked_at ? when(s.checked_at) : null;
  const also = checked && checked !== downloaded ? ` · checked ${esc(checked)}` : "";
  lines.push(`<span class="small">${downloaded ? `Downloaded ${esc(downloaded)}` : "Not downloaded yet"}${also}</span>`);
  if (s.stale) lines.push('<span class="rankings-stale">A newer FIDE list is usually out after the 1st.</span>');
  if (s.last_error) lines.push(`<span class="small rankings-err">The last update failed: ${esc(s.last_error)}</span>`);
  $("rkSource").innerHTML = lines.join("");
  if (!jobId) $("rkUpdate").textContent = `Update ${s.title}`;
  $("rkUpdate").title = `Downloads ${s.size}, if it changed`;
}

async function startUpdate() {
  $("rkUpdate").disabled = true;
  $("rkReport").hidden = true;
  try {
    jobId = (await api("/api/ext/rankings/update", { method: "POST", body: { source: current } })).job_id;
  } catch (err) {
    $("rkUpdate").disabled = false;
    showError(err.message);
    return;
  }
  showError(null);
  poll();
}

async function poll() {
  clearTimeout(pollTimer);
  let job;
  try {
    job = await api(`/api/ext/rankings/update/${encodeURIComponent(jobId)}`);
  } catch (err) {
    if (err.status === 404) { // from before the server restarted
      jobId = null;
      drawIdle();
      return;
    }
    showError(err.message);
    pollTimer = setTimeout(poll, POLL_MS * 4);
    return;
  }
  if (job.status === "running") {
    $("rkUpdate").disabled = true;
    $("rkUpdate").textContent = "Updating…";
    $("rkProgress").textContent = `${job.label} · ${job.percent}%`;
    $("rkTrack").hidden = false;
    $("rkFill").style.width = `${job.percent}%`;
    pollTimer = setTimeout(poll, POLL_MS);
    return;
  }
  jobId = null;
  drawIdle();
  drawReport(job);
  const mine = ++token;
  await Promise.all([loadStatus(), loadList(new URLSearchParams(location.hash.split("?")[1] || ""), mine)]);
}

function drawIdle() {
  $("rkUpdate").disabled = false;
  $("rkProgress").textContent = "";
  $("rkTrack").hidden = true;
  drawSource();
}

function drawReport(job) {
  const lines = job.outcomes.map((o) => (o.error
    ? `<p class="rankings-err">${esc(o.message)} The lists you had are kept.</p>`
    : `<p>${esc(o.message)}</p>`));
  if (job.error) lines.push(`<p class="rankings-err">${esc(job.error)}</p>`);
  if (!lines.length) lines.push(`<p>${esc(HEADLINE[job.status] || "")}</p>`);
  for (const note of job.notes) lines.push(`<p class="small">${esc(note)}</p>`);
  $("rkReport").innerHTML = lines.join("");
  $("rkReport").hidden = false;
}

// ---------------------------------------------------------------- the lists

async function loadList(params, mine) {
  const box = $("rkList");
  const board = pick(params, ["board"]);
  const url = current === "lichess" ? `/api/ext/rankings/lichess?${board}`
    : current === "chesscom" ? `/api/ext/rankings/chesscom?${board}`
      : `/api/ext/rankings/fide?${pick(params, ["speed", "list", "fed"])}`;
  let data;
  try {
    data = await api(url);
  } catch (err) {
    if (mine !== token) return;
    showError(err.message);
    box.innerHTML = `<p class="panel empty">${esc(err.message)}</p>`;
    return;
  }
  if (mine !== token) return;
  showError(null);
  box.innerHTML = current === "fide" ? fideHtml(data) : boardHtml(data);
  for (const select of box.querySelectorAll("select[data-key]")) {
    select.addEventListener("change", () => go(box));
  }
}

function pick(params, keys) {
  const out = new URLSearchParams();
  for (const key of keys) if (params.get(key)) out.set(key, params.get(key));
  return out.toString();
}

/** The filters' values as the address, so a reload or a link keeps them. */
function go(box) {
  const out = new URLSearchParams();
  for (const select of box.querySelectorAll("select[data-key]")) {
    if (select.value) out.set(select.dataset.key, select.value);
  }
  const query = out.toString();
  location.hash = `#rankings/${current}${query ? `?${query}` : ""}`;
}

const options = (items, chosen) => items.map((o) => `<option value="${esc(o.key)}"${o.key === chosen ? " selected" : ""}>${esc(o.name)}</option>`).join("");

const nothingYet = (title, what, source) => `<div class="panel empty"><p>No ${esc(title)} ${what} yet.</p>
  <p>Press Update to download them, or run <code>${COMMAND} ${source}</code>.</p></div>`;

function credit(source, text) {
  const s = status && status.sources.find((x) => x.source === source);
  const link = s ? ` <a href="${esc(s.about_url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>` : "";
  return `<p class="rankings-credit">${text}${link ? ` ·${link}` : ""}</p>`;
}

function fideHtml(data) {
  if (!data.month) {
    return `<div class="panel empty"><p>No FIDE lists yet.</p>
      <p>Press Update to download FIDE's standard, rapid and blitz lists (about 35 MB), or run <code>${COMMAND} fide</code>. Only the top players are kept: the world's top 100 and each federation's top 50.</p></div>`;
  }
  const feds = [{ key: "", name: "World" }, ...data.federations.map((f) => ({ key: f, name: f }))];
  const filters = `<div class="panel rankings-filters">
      <select data-key="speed" aria-label="Time control">${options(data.speeds, data.speed)}</select>
      <select data-key="list" aria-label="List">${options(data.lists, data.category)}</select>
      <select data-key="fed" aria-label="Federation">${options(feds, data.fed || "")}</select>
    </div>`;
  const list = data.lists.find((o) => o.key === data.category).name;
  const speed = data.speeds.find((o) => o.key === data.speed).name;
  const where = data.fed ? `${data.fed} top 50` : "World top 100";
  if (!data.players.length) {
    return filters + `<p class="panel empty">No players in the ${esc(where)} · ${esc(speed)} · ${esc(list)} list.</p>`;
  }
  const rows = data.players.map((p) => `<tr>
      <td class="rankings-num">${p.rank}</td>
      <td class="rankings-name"><span class="rankings-title">${esc(p.title || "")}</span><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.name)}</a></td>
      <td>${esc(p.fed || "—")}</td>
      <td class="rankings-num">${p.rating}</td>
      <td class="rankings-num">${p.games == null ? "—" : p.games}</td>
      <td class="rankings-num">${p.born == null ? "—" : p.born}</td>
    </tr>`).join("");
  return filters + `<div class="panel rankings-wrap"><table class="rankings-table">
      <caption class="sr">${esc(where)} · ${esc(speed)} · ${esc(list)}</caption>
      <thead><tr><th class="rankings-num">#</th><th>Player</th><th>Fed</th><th class="rankings-num">Rating</th><th class="rankings-num">Games</th><th class="rankings-num">Born</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
    + credit("fide", `${esc(where)} · ${esc(speed)} · ${esc(list)}, from FIDE's rating list of ${esc(data.month_label)}. Active players only.`);
}

function ratingChange(n) {
  const cls = n > 0 ? "rankings-up" : n < 0 ? "rankings-down" : "rankings-same";
  return `<span class="${cls}">${signed(n)}</span>`;
}

function boardHtml(data) {
  const title = data.source === "lichess" ? "Lichess" : "Chess.com";
  const filters = `<div class="panel rankings-filters">
      <select data-key="board" aria-label="Leaderboard">${options(data.boards, data.board)}</select>
    </div>`;
  if (!data.fetched_at) return nothingYet(title, "leaderboards", data.source);
  const name = data.boards.find((o) => o.key === data.board).name;
  if (!data.players.length) return filters + `<p class="panel empty">No players on ${esc(title)}'s ${esc(name)} leaderboard.</p>`;
  const progress = data.players.some((p) => p.progress != null);
  const rows = data.players.map((p) => `<tr>
      <td class="rankings-num">${p.rank}</td>
      <td class="rankings-name"><span class="rankings-title">${esc(p.title || "")}</span><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.username)}</a></td>
      <td class="rankings-num">${p.rating}</td>
      ${progress ? `<td class="rankings-num">${p.progress == null ? "" : ratingChange(p.progress)}</td>` : ""}
    </tr>`).join("");
  return filters + `<div class="panel rankings-wrap"><table class="rankings-table">
      <caption class="sr">${esc(title)} · ${esc(name)}</caption>
      <thead><tr><th class="rankings-num">#</th><th>Player</th><th class="rankings-num">Rating</th>${progress ? '<th class="rankings-num"><span class="sr">Recent change</span></th>' : ""}</tr></thead>
      <tbody>${rows}</tbody></table></div>`
    + credit(data.source, `${esc(title)}'s ${esc(name)} leaderboard, downloaded ${esc(when(data.fetched_at))}.${progress ? ` The change is ${esc(title)}'s own, over recent games.` : ""}`);
}
