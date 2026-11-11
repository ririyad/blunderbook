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

let retry = null;
/** What "Try again" on the error line does: the shell loads the open tab again. */
export function onRetry(fn) {
  retry = fn;
}

/** Show a problem above the views (or clear it with null), with "Try again" and "Dismiss". */
export function showError(text) {
  const el = document.getElementById("appError");
  el.replaceChildren();
  el.hidden = !text;
  if (!text) return;
  const message = document.createElement("span");
  message.textContent = text;
  el.append(message);
  const button = (label, act) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn ghost";
    b.textContent = label;
    b.addEventListener("click", act);
    el.append(b);
  };
  if (retry) button("Try again", () => { showError(null); retry(); });
  button("Dismiss", () => showError(null));
}

/** Tell the page that entries changed (the Re-test badge updates). */
export const entriesChanged = () => document.dispatchEvent(new Event("entries-changed"));
