// The page shell: hash router (#log, #retest, #patterns) and the Re-test badge.
// A route can carry more after a slash (#log/12); the view gets that part.

import { api } from "./api.js";
import { showError } from "./ui.js";
import * as log from "./views/log.js";
import * as patterns from "./views/patterns.js";
import * as retest from "./views/retest.js";

const VIEWS = { log, retest, patterns };
const TITLES = { log: "Log", retest: "Re-test", patterns: "Patterns" };
const DEFAULT = "log";

function route() {
  const [name, ...rest] = location.hash.replace(/^#/, "").split("/");
  if (!(name in VIEWS)) {
    history.replaceState(null, "", "#" + DEFAULT);
    show(DEFAULT, "");
    return;
  }
  show(name, rest.join("/"));
}

function show(name, rest) {
  for (const tab of document.querySelectorAll(".tab")) {
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  for (const view of document.querySelectorAll(".view")) {
    view.classList.toggle("on", view.id === "view-" + name);
  }
  document.title = TITLES[name] + " · Blunderbook";
  showError(null);
  VIEWS[name].show(document.getElementById("view-" + name), rest);
}

/** Entries due today or earlier, new ones included. */
async function refreshBadge() {
  const badge = document.getElementById("dueBadge");
  try {
    const due = await api("/api/blunders?due=1");
    badge.textContent = String(due.length);
    badge.hidden = due.length === 0;
    badge.setAttribute("aria-label", due.length + " due");
  } catch (err) {
    badge.hidden = true;
    showError(err.message);
  }
}

window.addEventListener("hashchange", route);
document.addEventListener("entries-changed", refreshBadge);
route();
refreshBadge();
