// The Patterns view, ported from the demo (CLAUDE.md §7.9, §11): four tiles, what causes
// your blunders (solid = confirmed, striped = suggested), by time control, the re-test
// history and a one-line "biggest leak". The server does the counting.

import { api } from "../api.js";
import { SOURCE_TAG, isDue, markText, moveLabel } from "../format.js";
import { esc, showError } from "../ui.js";

// The demo's advice for the most common leaks; anything else gets the general line.
const ADVICE = {
  "Missed their threat": "Before every move, ask what your opponent's last move threatens: checks, captures, threats.",
  "Moved too fast": "Most of these moves took 3 seconds or less. Do one blunder check before you move.",
};
const GENERAL_ADVICE = "Focus your next re-test sessions on these positions.";

let loadToken = 0;

export async function show(section) {
  const token = ++loadToken;
  let p;
  try {
    p = await api("/api/patterns");
  } catch (err) {
    if (token !== loadToken) return;
    showError(err.message);
    section.innerHTML = '<div class="panel"><p class="empty">Patterns couldn\'t be loaded.</p></div>';
    return;
  }
  if (token !== loadToken) return;
  section.innerHTML = p.total ? render(p) : empty();
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const pct = (n, of) => (of ? (100 * n) / of : 0);

function empty() {
  return `
  <div class="panel"><div class="empty">
    <p><b>No entries yet.</b></p>
    <p>Import a PGN on the <a href="#import">Import</a> tab, or with <code>blunderbook import FILE.pgn</code>. Patterns show up once you have a few.</p>
  </div></div>`;
}

function render(p) {
  return `
  <div class="tiles">${tiles(p)}</div>
  <div class="two">
    <div class="panel card">
      <h3>What causes your blunders</h3>
      <p class="small">Solid = causes you confirmed. Striped = auto-suggested on entries you haven't reviewed yet.</p>
      ${causes(p)}
    </div>
    <div class="panel card">
      <h3>By time control</h3>
      <p class="small">Where the blunders happen.</p>
      ${speeds(p)}
      <h3 style="margin-top:18px">Re-test history</h3>
      ${history(p)}
    </div>
  </div>`;
}

function tile(key, value, sub) {
  return `<div class="panel tile"><div class="k">${key}</div><div class="v">${value}</div><div class="s">${sub}</div></div>`;
}

function tiles(p) {
  const sources = p.by_source.map((s) => `${s.count} ${esc(SOURCE_TAG[s.source])}`).join(" · ");
  return [
    tile("Blunders logged", p.total, sources),
    tile("Due for re-test", p.due, `${plural(p.retests_done, "re-test", "re-tests")} done so far`),
    tile(
      "Currently solved",
      p.solved_pct == null ? '<span class="na">—</span>' : `${p.solved_pct}%`,
      p.retested ? `${p.solved} of ${plural(p.retested, "re-tested position", "re-tested positions")}` : "No re-tests yet",
    ),
    tile(
      "Played in ≤3 seconds",
      p.timed ? `${p.fast} of ${p.timed}` : '<span class="na">—</span>',
      p.with_clock
        ? `Entries with clock data · ${p.low_clock} under 30s left`
        : "No clock times yet (OTB games have none)",
    ),
  ].join("");
}

function causes(p) {
  if (!p.causes.length) {
    return '<p class="small">No causes yet. Confirm them on your entries in the Log.</p>';
  }
  const max = Math.max(1, ...p.causes.map((c) => c.confirmed + c.suggested));
  const rows = p.causes.map((c) => `
    <div class="hbar">
      <span>${esc(c.cause)}</span>
      <div class="track" role="img" aria-label="${c.confirmed} confirmed, ${c.suggested} suggested">
        <div class="c" style="width:${pct(c.confirmed, max)}%"></div><div class="s" style="width:${pct(c.suggested, max)}%"></div>
      </div>
      <span class="n">${c.confirmed + c.suggested}</span>
    </div>`).join("");
  const leak = p.biggest_leak;
  const insight = leak
    ? `<div class="insight"><b>Biggest leak: ${esc(leak)}.</b> ${esc(ADVICE[leak] || GENERAL_ADVICE)}</div>`
    : "";
  return rows + insight;
}

function speeds(p) {
  return p.by_speed.map((s) => {
    const label = s.speed ? s.speed[0].toUpperCase() + s.speed.slice(1) : "Unknown";
    return `
    <div class="hbar" style="grid-template-columns:80px 1fr 28px">
      <span>${esc(label)}</span>
      <div class="track" role="img" aria-label="${s.count} of ${p.total}"><div class="c" style="width:${pct(s.count, p.total)}%"></div></div>
      <span class="n">${s.count}</span>
    </div>`;
  }).join("");
}

function pill(r) {
  if (isDue(r.due_on)) return '<span class="pill p-due">Due</span>';
  return r.status === "solved"
    ? '<span class="pill p-solved">Solved</span>'
    : '<span class="pill p-missed">Missed</span>';
}

function history(p) {
  if (!p.history.length) return '<p class="small">No re-tests yet.</p>';
  return p.history.map((r) => `
    <div class="hbar" style="grid-template-columns:1fr auto">
      <span><a class="hist" href="#log/${r.id}">${moveLabel(r.move_no, r.my_color)}${esc(r.played_san)}${markText(r.judgment)}</a>
        <span class="small">vs ${esc(r.opponent || "Unknown")} · ${plural(r.attempts, "try", "tries")}</span></span>
      ${pill(r)}
    </div>`).join("");
}
