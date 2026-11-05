// Small helpers shared by the views.

/** Escape text for use inside HTML. Everything from the API or the user goes through this. */
export const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let toastTimer;
/** A short message at the bottom of the page, read out by screen readers. */
export function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2400);
}

/** Show a problem above the views (or clear it with null). */
export function showError(text) {
  const el = document.getElementById("appError");
  el.textContent = text || "";
  el.hidden = !text;
}

/** Tell the page that entries changed (the Re-test badge updates). */
export const entriesChanged = () => document.dispatchEvent(new Event("entries-changed"));
