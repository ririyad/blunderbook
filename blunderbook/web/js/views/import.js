// The Import view, ported from the demo (CLAUDE.md §10 "Web import", §11): paste a PGN, or
// choose or drop a .pgn file, and the server imports it in the background, the same way
// `blunderbook import` does. The report shows each game as it goes. A FEN quick entry logs
// one position and the move you played.
//
// A file is sent as its raw bytes, so the server reads its encoding (UTF-8 or Windows-1252).

import { api } from "../api.js";
import { MARK } from "../format.js";
import { entriesChanged, esc, showError } from "../ui.js";

const PGN_TYPE = "application/x-chess-pgn";
const POLL_MS = 500;
const SAVED_JOB = "blunderbook.importJob"; // survives a reload of the page, not a server restart

const PILL = {
  waiting: ["p-ready", "Waiting"],
  analysing: ["p-run", "Analysing"],
  analysed: ["p-done", "Analysed"],
  imported: ["p-done", "Imported"],
  not_analysed: ["p-dup", "Not analysed"],
  needs_side: ["p-need", "Needs your side"],
  duplicate: ["p-dup", "Skipped"],
  error: ["p-err", "Couldn't read"],
};
const HEADLINE = { done: "Done", stopped: "Stopped", failed: "Stopped with an error" };

let root = null;
let jobId = sessionStorage.getItem(SAVED_JOB);
let source = ""; // "pasted text" or the file's name, for the report's heading
let pollTimer = null;
let lastStatus = null;

const $ = (id) => document.getElementById(id);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export async function show(section) {
  if (root !== section) build(section);
  if (jobId) await poll();
}

// ---------------------------------------------------------------- the page

function build(section) {
  root = section;
  section.innerHTML = `
  <div class="imp">
    <div class="stack">
      <div class="panel card">
        <h3>Import PGN</h3>
        <p class="lead">From any source: a .pgn file from Lichess, Chess.com or ChessBase, a tournament download, or an over-the-board game you typed up from your score sheet. A file can hold many games.</p>
        <div class="drop" id="drop">
          <label class="sr" for="pgnText">PGN text</label>
          <textarea id="pgnText" spellcheck="false" placeholder='Paste PGN here, or drop a .pgn file on this box.

[White "Rashed"]
[Black "Opponent"]
1. e4 e5 2. Nf3 Nc6 ...'></textarea>
        </div>
        <div class="row">
          <span class="btn ghost filebtn">Choose .pgn file<input type="file" id="pgnFile" accept=".pgn,.txt,${PGN_TYPE}" aria-label="Choose a PGN file"></span>
          <button class="btn primary" id="importBtn" type="button">Import</button>
        </div>
        <p class="err" id="pgnErr" role="alert"></p>
        <p class="small note">Games are matched to you by the names in <code>my_names</code> in config.toml. Games you've imported before are skipped.</p>
      </div>

      <div class="panel card">
        <h3>Quick entry from a FEN</h3>
        <p class="lead">Only have one position, e.g. a game with no score sheet? Paste its FEN and the move you made, and Stockfish checks it. You're the side to move.</p>
        <form id="fenForm" novalidate>
          <div class="field" style="margin-top:0">
            <label class="lbl" for="fenIn" style="margin:0">FEN</label>
            <input id="fenIn" type="text" spellcheck="false" autocomplete="off" required placeholder="e.g. 3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32">
          </div>
          <div class="inline">
            <div class="field">
              <label class="lbl" for="fenMove" style="margin:0">Your move</label>
              <input id="fenMove" type="text" spellcheck="false" autocomplete="off" required placeholder="Rc7 or c1c7">
            </div>
            <div class="field">
              <label class="lbl" for="fenOpp" style="margin:0">Opponent <span class="na">(optional)</span></label>
              <input id="fenOpp" type="text" autocomplete="off">
            </div>
          </div>
          <div class="field">
            <label class="lbl" for="fenDate" style="margin:0">Date <span class="na">(empty: today)</span></label>
            <input id="fenDate" type="date">
          </div>
          <div class="row"><button class="btn primary" id="fenBtn" type="submit">Log this position</button></div>
        </form>
        <p class="err" id="fenErr" role="alert"></p>
        <div class="found" id="fenResult" aria-live="polite"></div>
      </div>
    </div>

    <div class="panel" id="report">
      <div class="qhead">
        <h3>Import report</h3>
        <span class="small" id="jobState" aria-live="polite"></span>
      </div>
      <div class="prog" id="jobProg" role="progressbar" aria-label="Import progress" aria-valuemin="0" aria-valuemax="100" hidden><i></i></div>
      <ul class="qlist" id="games"><li class="empty">Nothing imported yet. Paste a PGN or choose a file.</li></ul>
      <div class="qfoot" id="jobFoot" hidden></div>
    </div>
  </div>`;

  $("importBtn").addEventListener("click", () => {
    const text = $("pgnText").value;
    if (!text.trim()) {
      $("pgnErr").textContent = "Paste a PGN first, or choose a file.";
      return;
    }
    start(new Blob([text], { type: PGN_TYPE }), "pasted text");
  });
  $("pgnFile").addEventListener("change", (ev) => {
    const file = ev.target.files[0];
    ev.target.value = ""; // the same file can be chosen again
    if (file) start(file, file.name);
  });
  const drop = $("drop");
  drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    drop.classList.remove("over");
    const file = ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (file) start(file, file.name);
  });
  $("fenForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    logFen();
  });
}

// ---------------------------------------------------------------- import

async function start(data, from) {
  $("pgnErr").textContent = "";
  showError(null);
  $("importBtn").disabled = true;
  try {
    const started = await api("/api/import", { method: "POST", data, type: PGN_TYPE });
    jobId = started.job_id;
    sessionStorage.setItem(SAVED_JOB, jobId);
    source = from;
    lastStatus = null;
    await poll();
  } catch (err) {
    $("pgnErr").textContent = err.message;
  } finally {
    $("importBtn").disabled = false;
  }
}

async function poll() {
  clearTimeout(pollTimer);
  let job;
  try {
    job = await api(`/api/import/${jobId}`);
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
  if (job.status === "running") {
    pollTimer = setTimeout(poll, POLL_MS);
  } else if (lastStatus === "running" || lastStatus === null) {
    if (job.games.some((g) => g.entries.length)) entriesChanged();
  }
  lastStatus = job.status;
}

function renderJob(job) {
  const running = job.status === "running";
  const state = running
    ? job.game_index
      ? `Analysing game ${job.game_index} of ${job.games_to_analyse} · ${job.percent}%`
      : "Starting Stockfish…"
    : HEADLINE[job.status];
  $("jobState").textContent = (source ? `From ${source} · ` : "") + state;

  const prog = $("jobProg");
  prog.hidden = !running;
  prog.setAttribute("aria-valuenow", String(job.percent));
  prog.querySelector("i").style.width = job.percent + "%";

  $("games").innerHTML = job.games.map((g) => row(job, g)).join("");

  const foot = $("jobFoot");
  foot.hidden = running; // the summary counts the new entries, which come at the end
  if (running) return;
  const notes = job.notes.map((n) => `<p class="small note">Note: ${esc(n)}</p>`).join("");
  const error = job.error ? `<p class="bad-text">${esc(job.error)}</p>` : "";
  foot.innerHTML = `<div><b>${esc(job.summary)}</b>${error}${notes}</div>`
    + (job.games.some((g) => g.entries.length) ? '<a class="btn ghost" href="#log">Open the Log</a>' : "");
}

function row(job, g) {
  const [cls, label] = PILL[g.status] || ["p-ready", g.status];
  const share = g.status === "analysing" && job.total ? ` ${Math.floor((100 * job.done) / job.total)}%` : "";
  const meta = [
    g.site_label,
    g.date || "date unknown",
    g.my_color ? `you played ${g.my_color[0].toUpperCase()}${g.my_color.slice(1)}` : null,
  ].filter(Boolean).map(esc).join(" · ");
  const notes = g.warnings.map((w) => `<div class="m">Note: ${esc(w)}</div>`).join("");
  let found = "";
  if (g.status === "imported") {
    found = g.entries.length
      ? `${plural(g.entries.length, "blunder", "blunders")} found: `
        + g.entries.map((en) => `<a href="#log/${en.id}">${esc(en.label)}${MARK[en.judgment]}</a>`).join(", ")
      : "No blunders by you in this game.";
    found = `<div class="found">${found}</div>`;
  } else if (g.reason) {
    found = `<div class="found">${esc(g.reason)}</div>`;
  }
  return `
  <li class="qrow">
    <div class="t"><span>Game ${g.number} · ${esc(g.players)}</span><span class="pill ${cls}">${label}${share}</span></div>
    <div class="m">${meta}</div>
    ${notes}${found}
  </li>`;
}

// ---------------------------------------------------------------- FEN quick entry

async function logFen() {
  const fen = $("fenIn").value.trim(), move = $("fenMove").value.trim();
  $("fenErr").textContent = "";
  $("fenResult").innerHTML = "";
  if (!fen || !move) {
    $("fenErr").textContent = "Enter the FEN and the move you played.";
    return;
  }
  const body = { fen, move };
  if ($("fenOpp").value.trim()) body.opponent = $("fenOpp").value.trim();
  if ($("fenDate").value) body.date = $("fenDate").value;
  const button = $("fenBtn");
  button.disabled = true;
  button.textContent = "Checking with Stockfish…";
  try {
    const out = await api("/api/fen", { method: "POST", body });
    const link = out.entry_id != null ? ` <a href="#log/${out.entry_id}">Open it in the Log</a>.` : "";
    const notes = out.notes.map((n) => `<p class="small note">Note: ${esc(n)}</p>`).join("");
    $("fenResult").innerHTML = `<p style="margin:0">${esc(out.message)}${link}</p>${notes}`;
    if (out.result === "logged") entriesChanged();
  } catch (err) {
    $("fenErr").textContent = err.message;
  } finally {
    button.disabled = false;
    button.textContent = "Log this position";
  }
}
