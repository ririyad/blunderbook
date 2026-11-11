// How values read on the page. Pure functions: no DOM, no fetch.

/** Short source tags for the list, and full names for the detail. */
export const SOURCE_TAG = { lichess: "Lichess", chesscom: "Chess.com", pgn: "PGN", otb: "OTB", fen: "FEN" };
export const SOURCE_NAME = { lichess: "Lichess", chesscom: "Chess.com", pgn: "PGN file", otb: "Over the board", fen: "FEN entry" };

/** The chess marks for a judgment. */
export const MARK = { blunder: "??", mistake: "?", inaccuracy: "?!", missed: "" };

/** What each judgment is called in a sentence: "your missed win comes next". */
export const JUDGMENT_WORD = { blunder: "blunder", mistake: "mistake", inaccuracy: "inaccuracy", missed: "missed win" };

/** After a move in text: its mark, or " (missed win)" for a missed win, which has none. */
export const markText = (judgment) => judgment === "missed" ? " (missed win)" : MARK[judgment];

/** The pill in a list: the mark in red, or "Missed win" in amber. */
export const markPill = (judgment) => judgment === "missed"
  ? '<span class="pill p-missed-win">Missed win</span>'
  : `<span class="pill p-blunder">${MARK[judgment]}</span>`;

/** An entry's re-test pill: New, Due, Solved or Missed. */
export function statusPill(status, dueOn) {
  if (status === "new") return '<span class="pill p-new">New</span>';
  if (isDue(dueOn)) return '<span class="pill p-due">Due</span>';
  return status === "solved" ? '<span class="pill p-solved">Solved</span>' : '<span class="pill p-missed">Missed</span>';
}

/** "1 game", "3 games". */
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "6. " for White, "5... " for Black. */
export const moveLabel = (moveNo, color) => moveNo + (color === "white" ? ". " : "... ");

const pad = (n) => String(n).padStart(2, "0");

/** Today on this computer, "YYYY-MM-DD", like the due dates the API sends. */
export function localToday(now = new Date()) {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export const isDue = (dueOn, today = localToday()) => dueOn <= today;

/** "2026-10-12" -> "12 Oct" (with the year when it isn't this year). null stays null. */
export function fmtDate(value, now = new Date()) {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  const options = { day: "numeric", month: "short" };
  if (y !== now.getFullYear()) options.year = "numeric";
  return new Date(y, m - 1, d).toLocaleDateString(undefined, options);
}

/** A UTC timestamp as your local "YYYY-MM-DD" (for fmtDate), or null if it can't be read. */
export function localDay(timestamp) {
  const d = new Date(timestamp);
  return Number.isNaN(d.getTime()) ? null : localToday(d);
}

/** White POV, like Lichess: {cp: 36} -> "+0.36", {mate: -2} -> "−M2", {mate: 0} -> "#". */
export function fmtEval(ev) {
  if ("mate" in ev) return ev.mate === 0 ? "#" : (ev.mate > 0 ? "+" : "−") + "M" + Math.abs(ev.mate);
  const v = ev.cp / 100;
  return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
}

/** Seconds on the clock: 402 -> "6:42", 5400 -> "1:30:00". null stays null. */
export function fmtClock(seconds) {
  if (seconds == null) return null;
  const t = Math.round(seconds);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** Time spent on a move: 1.24 -> "1.2s", 14.6 -> "15s". null stays null. */
export function fmtSpent(seconds) {
  if (seconds == null) return null;
  return (seconds < 10 ? Math.round(seconds * 10) / 10 : Math.round(seconds)) + "s";
}

/** "Win" / "Draw" / "Loss" from your side, or null when the result isn't known. */
export function outcome(result, myColor) {
  if (result === "1/2-1/2") return "Draw";
  if (result === "1-0") return myColor === "white" ? "Win" : "Loss";
  if (result === "0-1") return myColor === "black" ? "Win" : "Loss";
  return null;
}

/** "Blitz 3+2", "3+2" without a speed, or null. */
export function timeControl(speed, tcLabel) {
  if (!tcLabel) return null;
  return speed ? speed[0].toUpperCase() + speed.slice(1) + " " + tcLabel : tcLabel;
}

/** Your winning chances as a whole percentage: 0.5331 -> 53. */
export const percent = (chances) => Math.round(chances * 100);
