// The step controls under a board: start / back / forward / end, and an optional "jump to
// the marked move" button. One copy for the Log, Games and the extensions' boards
// (CLAUDE.md §11, §15), so they all behave the same.
//
// ← → Home End work for whichever bound board is on the page, wherever the focus is, unless
// you're typing. Each view keeps its own position and draws its own board:
//
//   box.innerHTML = `... ${stepsHtml("g", { mark: "Next of your mistakes" })} ...`;
//   steps = bindSteps("g", { last: () => moves.length, get: () => ply, set: (to) => { ply = to; draw(); } });
//   // in draw(): $("gLabel").textContent = "After 4. Bg5"; steps.sync();

const svg = (inner) =>
  `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;

export const ICON = {
  first: svg('<path d="M4 3v10M12 3 7 8l5 5"/>'),
  prev: svg('<path d="M10 3 5 8l5 5"/>'),
  next: svg('<path d="m6 3 5 5-5 5"/>'),
  last: svg('<path d="M12 3v10M4 3l5 5-5 5"/>'),
  mark: svg('<circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/>'),
};

const attr = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/** The buttons and the label, with ids `${p}First`, `${p}Prev`, `${p}Next`, `${p}Last`,
 *  `${p}Mark` (when `mark` names it) and `${p}Label`. `first` and `last` name the ends. */
export function stepsHtml(p, { first = "Start of game", last = "End of game", mark = null } = {}) {
  const button = (id, label, icon) =>
    `<button class="icon" type="button" id="${p}${id}" aria-label="${attr(label)}" title="${attr(label)}">${icon}</button>`;
  return `<div class="nav">
    <div class="grp">
      ${button("First", first, ICON.first)}
      ${button("Prev", "Previous move", ICON.prev)}
      ${button("Next", "Next move", ICON.next)}
      ${button("Last", last, ICON.last)}
      ${mark ? button("Mark", mark, ICON.mark) : ""}
    </div>
    <span class="navlabel" id="${p}Label" aria-live="polite"></span>
  </div>`;
}

const bound = []; // the boards on the page: {nav, opts}

/**
 * Wire the controls `stepsHtml(p)` made.
 *
 * opts.last  () => the last position (0 is the start)
 * opts.get   () => the position shown
 * opts.set   (to) => show position `to` (already within 0..last) and draw
 * opts.mark  () => the position the mark button jumps to, or null when there's none
 *
 * Returns {sync}: call sync() after drawing, so the buttons at an end are disabled.
 */
export function bindSteps(p, opts) {
  const el = (id) => document.getElementById(p + id);
  const go = (to) => {
    if (to === null || to === undefined) return;
    opts.set(Math.max(0, Math.min(opts.last(), to)));
  };
  el("First").addEventListener("click", () => go(0));
  el("Prev").addEventListener("click", () => go(opts.get() - 1));
  el("Next").addEventListener("click", () => go(opts.get() + 1));
  el("Last").addEventListener("click", () => go(opts.last()));
  el("Mark")?.addEventListener("click", () => go(opts.mark()));
  bound.push({ nav: el("Label").parentElement, go, opts });
  return {
    sync() {
      const at = opts.get(), last = opts.last();
      el("First").disabled = el("Prev").disabled = at === 0;
      el("Next").disabled = el("Last").disabled = at === last;
      if (el("Mark")) el("Mark").disabled = opts.mark() === null;
    },
  };
}

const TYPING = ["INPUT", "TEXTAREA", "SELECT"];

document.addEventListener("keydown", (ev) => {
  if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.defaultPrevented) return;
  if (TYPING.includes(ev.target.tagName) || ev.target.isContentEditable) return;
  for (let i = bound.length - 1; i >= 0; i--) if (!bound[i].nav.isConnected) bound.splice(i, 1);
  const board = bound.find((b) => b.nav.offsetParent !== null); // the one on screen
  if (!board) return;
  const at = board.opts.get();
  const to = { ArrowLeft: at - 1, ArrowRight: at + 1, Home: 0, End: board.opts.last() }[ev.key];
  if (to === undefined) return;
  ev.preventDefault();
  board.go(to);
});
