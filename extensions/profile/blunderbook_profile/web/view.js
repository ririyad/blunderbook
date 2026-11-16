// The Profile tab (ROADMAP 17.3): your ratings on Lichess and Chess.com.
//   #profile
//
// The sites are asked only when you press "Refresh ratings" (or run `blunderbook profile
// refresh`). Opening the tab shows what was kept last time, and your rating in your newest
// games, without asking anyone.

import { api } from "/js/api.js";
import { fmtDate, localDay } from "/js/format.js";
import { esc, showError } from "/js/ui.js";

const DASH = "—";
const COMMAND = "blunderbook profile refresh";

let root = null;
let busy = false; // a refresh is running
let asked = "the sites"; // "Lichess and Chess.com": the sites you have a username for
let token = 0; // only the newest answer is drawn

const $ = (id) => document.getElementById(id);
const signed = (n) => (n > 0 ? `+${n}` : `−${-n}`);

export async function show(section) {
  if (root !== section) build(section);
  if (busy) return; // its answer will draw the tab
  const mine = ++token;
  let data;
  try {
    data = await api("/api/ext/profile");
  } catch (err) {
    showError(err.message);
    return;
  }
  if (mine === token) draw(data);
}

function build(section) {
  root = section;
  section.innerHTML = `<div class="profile">
    <div class="panel profile-bar">
      <div class="profile-about">
        <strong>Your ratings</strong>
        <span class="small">Lichess and Chess.com are asked only when you press Refresh ratings, or run <code>${COMMAND}</code>.</span>
      </div>
      <div class="profile-refresh">
        <span class="profile-status" id="pfStatus" role="status" aria-live="polite"></span>
        <button class="btn primary" id="pfRefresh" type="button">Refresh ratings</button>
      </div>
    </div>
    <div class="profile-notes" id="pfNotes" hidden></div>
    <div class="profile-sites" id="pfSites"></div>
  </div>`;
  $("pfRefresh").addEventListener("click", refresh);
}

// ---------------------------------------------------------------- the Refresh button

async function refresh() {
  if (busy) return;
  busy = true;
  const mine = ++token;
  $("pfRefresh").disabled = true;
  $("pfRefresh").textContent = "Refreshing…";
  status(`Asking ${asked} for your ratings…`);
  let data = null;
  let failed = null;
  try {
    data = await api("/api/ext/profile/refresh", { method: "POST", body: { site: "all" } });
  } catch (err) {
    failed = err.message;
  }
  busy = false;
  $("pfRefresh").disabled = false;
  $("pfRefresh").textContent = "Refresh ratings";
  if (failed !== null) {
    status(failed, true);
    return;
  }
  showError(null);
  const tried = data.sites.filter((s) => s.username);
  const problems = tried.filter((s) => s.problem).length;
  if (!problems) status("Your ratings are up to date.");
  else if (problems === tried.length) status("Nothing was fetched. The ratings you had are kept.", true);
  else status("One site couldn't be asked. The ratings you had from it are kept.", true);
  if (mine === token) draw(data);
}

function status(text, bad = false) {
  const line = $("pfStatus");
  line.textContent = text;
  line.classList.toggle("profile-err", bad);
}

// ---------------------------------------------------------------- the sites

function draw(data) {
  const notes = $("pfNotes");
  notes.hidden = !data.warnings.length;
  notes.innerHTML = data.warnings.map((w) => `<p class="small">${esc(w)}</p>`).join("");
  $("pfSites").innerHTML = data.sites.map(site).join("");
  const named = data.sites.filter((s) => s.username).map((s) => s.title);
  asked = named.join(" and ") || "the sites";
  $("pfRefresh").disabled = busy || !named.length;
}

function site(s) {
  const who = s.fetched ? s.fetched.username : s.username;
  const head = `<h2 class="profile-name">${esc(s.title)}${who ? ` <span class="profile-user">${esc(who)}</span>` : ""}</h2>`;
  const problem = s.problem ? `<p class="small profile-err">${esc(s.problem)}</p>` : "";
  let body;
  if (s.fetched) body = fetched(s.fetched);
  else if (s.username) body = `<p class="small">Not fetched yet. Press Refresh ratings.</p>${games(s)}`;
  else body = `<p class="small">Set <code>username</code> under <code>[${esc(s.source)}]</code> in config.toml to see your ${esc(s.title)} ratings.</p>${games(s)}`;
  return `<section class="panel profile-site" aria-label="${esc(s.title)}">${head}${problem}${body}</section>`;
}

function fetched(f) {
  const day = fmtDate(localDay(f.fetched_at));
  const time = new Date(f.fetched_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const since = f.since ? ` · changes since ${esc(fmtDate(f.since))}` : "";
  const when = `<p class="small profile-when">Fetched ${esc(day)}, ${esc(time)}${since}</p>`;
  if (!f.ratings.length) return `${when}<p class="small">No ratings yet.</p>`;
  return `${when}<div class="profile-wrap"><table class="profile-table">
    <thead><tr><th scope="col">Time control</th><th scope="col" class="profile-num">Rating</th><th scope="col" class="profile-num">Best</th><th scope="col">Won / lost / drawn</th></tr></thead>
    <tbody>${f.ratings.map(rating).join("")}</tbody>
  </table></div>`;
}

function rating(r) {
  const now = r.rating === null
    ? `<span class="profile-none">${DASH}<span class="sr"> no current rating from this site</span></span>`
    : `<b class="profile-now">${r.rating}</b>${r.provisional ? '<span class="profile-prov" title="Provisional: the site isn\'t sure of it yet">?<span class="sr"> provisional</span></span>' : ""}`;
  const change = r.change ? ` <span class="${r.change > 0 ? "profile-up" : "profile-down"}">${signed(r.change)}</span>` : "";
  const best = r.best === null ? DASH : `${r.best}${r.best_at ? ` <span class="small profile-on">${esc(fmtDate(localDay(r.best_at)))}</span>` : ""}`;
  const record = r.wins === null || r.losses === null || r.draws === null
    ? DASH
    : `${r.wins} / ${r.losses} / ${r.draws}`;
  return `<tr><th scope="row">${esc(r.label)}</th><td class="profile-num">${now}${change}</td><td class="profile-num">${best}</td><td>${record}</td></tr>`;
}

/** Your rating in your newest game of each speed on this site, until it's been fetched. */
function games(s) {
  if (!s.from_games.length) return "";
  const rows = s.from_games.map((g) => `<tr><th scope="row">${esc(g.label)}</th><td class="profile-num"><b class="profile-now">${g.rating}</b></td><td><a href="#games/${g.game_id}">${esc(fmtDate(g.played_on))}</a></td></tr>`).join("");
  return `<p class="small profile-from">From your games</p><div class="profile-wrap"><table class="profile-table">
    <thead><tr><th scope="col">Time control</th><th scope="col" class="profile-num">Rating</th><th scope="col">Newest game</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}
