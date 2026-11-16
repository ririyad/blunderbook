// "Rating over time" on the Profile tab (ROADMAP 17.4): your rating month by month in one
// time control, a line per site, and your blunders per game under it. All of it comes from
// the games in your Log (`history` in GET /api/ext/profile); nothing here asks a site.
//
// Two plots share the months along the bottom, each with its own scale: ratings on top,
// blunders per game below. They're never drawn on one scale.
//
// The SVG is drawn at the panel's real width (and again when that changes), so lines stay
// 2 px and text stays readable on a phone. Point at a month, or focus the chart and use
// ← → Home End, to read its numbers; "The numbers" has them all as a table.

import { plural } from "/js/format.js";
import { esc } from "/js/ui.js";

const SITES = [["lichess", "Lichess"], ["chesscom", "Chess.com"]];
const PAD = { top: 12, right: 44, bottom: 22, left: 40 };
const LINES_H = 170; // the ratings plot
const GAP = 34; // between the two plots: room for the lower one's title
const BARS_H = 54; // the blunders plot
const HEIGHT = PAD.top + LINES_H + GAP + BARS_H + PAD.bottom;
const BAR_MAX = 24;
const DOT_ROOM = 14; // px per month below which only each line's last dot is drawn
const LABEL_ROOM = 62; // px an x label needs ("Sep 2026")

let speed = null; // the time control shown; kept while the tab stays open
let observer = null;

/** Draw the panel into `box` from the API's `history` (one chart per time control). */
export function mountChart(box, history) {
  if (observer) observer.disconnect();
  if (!history.length) {
    box.innerHTML = `<h2 class="profile-name">Rating over time</h2>
      <p class="small">No Lichess or Chess.com games with your rating in your Log yet. Sync or import some, and your rating by month shows here.</p>`;
    return;
  }
  if (!history.some((c) => c.speed === speed)) {
    speed = history.reduce((most, c) => (c.games > most.games ? c : most)).speed;
  }
  const picks = history.map((c) => `<button class="profile-pick" type="button" data-speed="${esc(c.speed)}" aria-pressed="${c.speed === speed}">${esc(c.label)}</button>`).join("");
  box.innerHTML = `<div class="profile-chart-head">
      <h2 class="profile-name">Rating over time</h2>
      <div class="profile-picks" role="group" aria-label="Time control">${picks}</div>
    </div>
    <p class="small" id="pfChartAbout"></p>
    <div class="profile-legend" id="pfLegend"></div>
    <div class="profile-plot" id="pfPlot" tabindex="0" role="group" aria-label="Rating over time. Use the left and right arrow keys to read each month.">
      <div id="pfSvg"></div>
      <div class="profile-tip" id="pfTip" role="status" hidden></div>
    </div>
    <details class="profile-numbers"><summary>The numbers</summary><div class="profile-wrap" id="pfNumbers"></div></details>`;
  for (const button of box.querySelectorAll(".profile-pick")) {
    button.addEventListener("click", () => {
      speed = button.dataset.speed;
      mountChart(box, history);
      box.querySelector('.profile-pick[aria-pressed="true"]').focus(); // the panel was redrawn
    });
  }
  const chart = history.find((c) => c.speed === speed);
  const plot = box.querySelector("#pfPlot");
  const state = { chart, plot, at: null, geometry: null };
  about(box, chart);
  legend(box, chart);
  numbers(box, chart);
  draw(state);
  bind(state);
  observer = new ResizeObserver(() => draw(state));
  observer.observe(plot);
}

// ---------------------------------------------------------------- words around the plot

const monthDate = (key) => new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1);
const monthShort = (key) => monthDate(key).toLocaleDateString(undefined, { month: "short" });
const monthYear = (key) => monthDate(key).toLocaleDateString(undefined, { month: "short", year: "numeric" });
const monthLong = (key) => monthDate(key).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const perGame = (value) => (value === null ? "—" : value.toFixed(value < 10 ? 2 : 1).replace(/\.?0+$/, "") || "0");
const shown = (chart) => SITES.filter(([key]) => chart.months.some((m) => m[key] !== null));

function about(box, chart) {
  const first = chart.months[0].month;
  const last = chart.months[chart.months.length - 1].month;
  const span = first === last ? monthLong(first) : `${monthLong(first)} to ${monthLong(last)}`;
  box.querySelector("#pfChartAbout").textContent =
    `${chart.label}: ${plural(chart.games, "game", "games")} with your rating in your Log, ${span}. Each point is your rating in the month's last game.`;
}

function legend(box, chart) {
  const keys = shown(chart).map(([key, name]) =>
    `<span class="profile-key"><svg width="26" height="10" aria-hidden="true"><line class="profile-line profile-line-${key}" x1="1" y1="5" x2="25" y2="5"/></svg>${esc(name)}</span>`);
  keys.push('<span class="profile-key"><svg width="12" height="10" aria-hidden="true"><rect class="profile-bar" x="2" y="0" width="8" height="10" rx="2"/></svg>Blunders per game</span>');
  box.querySelector("#pfLegend").innerHTML = keys.join("");
}

function numbers(box, chart) {
  const sites = shown(chart);
  const rows = chart.months.filter((m) => m.games).map((m) =>
    `<tr><th scope="row">${esc(monthYear(m.month))}</th>${sites.map(([key]) => `<td class="profile-num">${m[key] === null ? "—" : m[key]}</td>`).join("")}<td class="profile-num">${m.games}</td><td class="profile-num">${perGame(m.blunders_per_game)}</td></tr>`).join("");
  box.querySelector("#pfNumbers").innerHTML = `<table class="profile-table">
    <thead><tr><th scope="col">Month</th>${sites.map(([, name]) => `<th scope="col" class="profile-num">${esc(name)}</th>`).join("")}<th scope="col" class="profile-num">Games</th><th scope="col" class="profile-num">Blunders per game</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

// ---------------------------------------------------------------- the plot

/** A clean scale around the ratings: its lowest and highest line, and the step between. */
function ratingScale(values) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  let step = [25, 50, 100, 200, 500].find((s) => (hi - lo) / s <= 4) || 1000;
  let from = Math.floor(lo / step) * step;
  let to = Math.ceil(hi / step) * step;
  if (from === to) {
    from -= step;
    to += step;
  }
  if ((to - from) / step > 5) step *= 2;
  from = Math.floor(from / step) * step;
  to = Math.ceil(to / step) * step;
  return { from, to, step };
}

/** The top of the blunders scale: the next 0.5 above the worst month (at least 0.5). */
const barsTop = (months) => Math.max(0.5, Math.ceil(Math.max(0, ...months.map((m) => m.blunders_per_game || 0)) * 2) / 2);

function draw(state) {
  const { chart, plot } = state;
  const width = Math.max(280, Math.floor(plot.clientWidth));
  const months = chart.months;
  const band = (width - PAD.left - PAD.right) / months.length;
  const x = (i) => PAD.left + band * (i + 0.5);
  const scale = ratingScale(months.flatMap((m) => SITES.map(([key]) => m[key]).filter((v) => v !== null)));
  const y = (rating) => PAD.top + LINES_H * (1 - (rating - scale.from) / (scale.to - scale.from));
  const base = PAD.top + LINES_H + GAP + BARS_H; // the bars' baseline
  const top = barsTop(months);
  const right = width - PAD.right;
  state.geometry = { width, band, x, y, base };

  const parts = [];
  // Recessive hairlines and the numbers they stand for.
  for (let rating = scale.from; rating <= scale.to; rating += scale.step) {
    parts.push(`<line class="profile-grid" x1="${PAD.left}" y1="${y(rating)}" x2="${right}" y2="${y(rating)}"/>`);
    parts.push(`<text class="profile-tick" x="${PAD.left - 6}" y="${y(rating) + 4}" text-anchor="end">${rating}</text>`);
  }
  parts.push(`<text class="profile-tick" x="${PAD.left}" y="${base - BARS_H - 10}">Blunders per game</text>`);
  parts.push(`<line class="profile-grid" x1="${PAD.left}" y1="${base - BARS_H}" x2="${right}" y2="${base - BARS_H}"/>`);
  parts.push(`<text class="profile-tick" x="${PAD.left - 6}" y="${base - BARS_H + 4}" text-anchor="end">${perGame(top)}</text>`);
  parts.push(`<line class="profile-axis" x1="${PAD.left}" y1="${base}" x2="${right}" y2="${base}"/>`);
  parts.push(`<text class="profile-tick" x="${PAD.left - 6}" y="${base + 4}" text-anchor="end">0</text>`);

  // The months along the bottom: as many labels as fit, the year on the first and each January.
  const every = Math.max(1, Math.ceil(LABEL_ROOM / band));
  months.forEach((m, i) => {
    if (i % every) return;
    const text = i === 0 || m.month.endsWith("-01") ? monthYear(m.month) : monthShort(m.month);
    parts.push(`<text class="profile-tick" x="${x(i)}" y="${base + 16}" text-anchor="middle">${esc(text)}</text>`);
  });

  // Blunders per game: thin bars from one baseline, rounded at the top only.
  const barWidth = Math.max(2, Math.min(BAR_MAX, band - 2));
  months.forEach((m, i) => {
    if (!m.blunders_per_game) return;
    const h = Math.max(1, BARS_H * (m.blunders_per_game / top));
    const r = Math.min(4, barWidth / 2, h);
    const left = x(i) - barWidth / 2;
    parts.push(`<path class="profile-bar" data-month="${i}" d="M${left},${base} v${-(h - r)} q0,${-r} ${r},${-r} h${barWidth - 2 * r} q${r},0 ${r},${r} v${h - r} z"/>`);
  });

  // A line per site through the months it has a rating in, then its dots over the line.
  const ends = [];
  for (const [key] of SITES) {
    const points = months.map((m, i) => [i, m[key]]).filter(([, v]) => v !== null);
    if (!points.length) continue;
    if (points.length > 1) {
      parts.push(`<polyline class="profile-line profile-line-${key}" points="${points.map(([i, v]) => `${x(i)},${y(v)}`).join(" ")}"/>`);
    }
    const dots = band >= DOT_ROOM ? points : points.slice(-1);
    for (const [i, v] of dots) parts.push(`<circle class="profile-dot profile-dot-${key}" data-month="${i}" cx="${x(i)}" cy="${y(v)}" r="4"/>`);
    const [i, v] = points[points.length - 1];
    ends.push({ x: x(i), y: y(v), value: v });
  }
  // Each line's last value beside its end, unless the two would sit on top of each other.
  const apart = ends.length < 2 || Math.abs(ends[0].y - ends[1].y) >= 14 || Math.abs(ends[0].x - ends[1].x) >= 40;
  if (apart) for (const end of ends) parts.push(`<text class="profile-end" x="${end.x + 9}" y="${end.y + 4}">${end.value}</text>`);

  parts.push(`<line class="profile-cross" id="pfCross" x1="0" y1="${PAD.top}" x2="0" y2="${base}" visibility="hidden"/>`);
  plot.querySelector("#pfSvg").innerHTML =
    `<svg class="profile-svg" width="${width}" height="${HEIGHT}" viewBox="0 0 ${width} ${HEIGHT}" role="img" aria-label="${esc(summary(chart))}">${parts.join("")}</svg>`;
  point(state, state.at);
}

function summary(chart) {
  const parts = shown(chart).map(([key, name]) => {
    const values = chart.months.map((m) => m[key]).filter((v) => v !== null);
    const first = values[0];
    const last = values[values.length - 1];
    return values.length > 1 ? `${name} from ${first} to ${last}` : `${name} ${last}`;
  });
  return `Your ${chart.label.toLowerCase()} rating by month: ${parts.join(", ")}. Blunders per game by month under it.`;
}

// ---------------------------------------------------------------- reading a month

function bind(state) {
  const { plot, chart } = state;
  const last = chart.months.length - 1;
  plot.addEventListener("pointermove", (event) => {
    const { band } = state.geometry;
    const px = event.clientX - plot.getBoundingClientRect().left;
    point(state, Math.max(0, Math.min(last, Math.floor((px - PAD.left) / band))));
  });
  plot.addEventListener("pointerleave", () => point(state, null));
  plot.addEventListener("blur", () => point(state, null));
  plot.addEventListener("keydown", (event) => {
    const moves = { ArrowLeft: -1, ArrowRight: 1 };
    let to;
    if (event.key in moves) to = state.at === null ? (event.key === "ArrowLeft" ? last : 0) : state.at + moves[event.key];
    else if (event.key === "Home") to = 0;
    else if (event.key === "End") to = last;
    else if (event.key === "Escape") to = null;
    else return;
    event.preventDefault();
    event.stopPropagation();
    point(state, to === null ? null : Math.max(0, Math.min(last, to)));
  });
}

/** Show month `i`'s numbers beside a hairline through it (null hides both). */
function point(state, i) {
  state.at = i;
  const { plot, chart, geometry } = state;
  const cross = plot.querySelector("#pfCross");
  const tip = plot.querySelector("#pfTip");
  for (const mark of plot.querySelectorAll(".profile-on-month")) mark.classList.remove("profile-on-month");
  if (i === null || !cross) {
    if (cross) cross.setAttribute("visibility", "hidden");
    tip.hidden = true;
    return;
  }
  const at = geometry.x(i);
  cross.setAttribute("x1", at);
  cross.setAttribute("x2", at);
  cross.setAttribute("visibility", "visible");
  for (const mark of plot.querySelectorAll(`[data-month="${i}"]`)) mark.classList.add("profile-on-month");

  // Built with DOM calls and textContent: nothing from the API is parsed as HTML here.
  const month = chart.months[i];
  tip.replaceChildren();
  const title = document.createElement("div");
  title.className = "profile-tip-title";
  title.textContent = monthLong(month.month);
  tip.append(title);
  for (const [key, name] of shown(chart)) {
    if (month[key] === null) continue;
    tip.append(row(String(month[key]), name, `profile-swatch profile-swatch-${key}`));
  }
  if (month.games) {
    tip.append(row(perGame(month.blunders_per_game), "blunders per game", "profile-swatch profile-swatch-bar"));
    tip.append(row(String(month.games), month.games === 1 ? "game" : "games", ""));
  } else {
    const none = document.createElement("div");
    none.className = "profile-tip-row";
    none.textContent = "No games this month";
    tip.append(none);
  }
  tip.hidden = false;
  // Beside the hairline, on whichever side has room.
  const room = geometry.width - at;
  tip.style.left = room > tip.offsetWidth + 16 ? `${at + 10}px` : `${Math.max(0, at - tip.offsetWidth - 10)}px`;
}

/** One tooltip line: the value first and strong, then what it is, keyed by a stroke. */
function row(value, label, swatch) {
  const line = document.createElement("div");
  line.className = "profile-tip-row";
  const key = document.createElement("span");
  key.className = swatch || "profile-swatch-none";
  const strong = document.createElement("b");
  strong.textContent = value;
  const text = document.createElement("span");
  text.textContent = label;
  line.append(key, strong, text);
  return line;
}
