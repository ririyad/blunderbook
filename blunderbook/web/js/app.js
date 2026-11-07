// The page shell: hash router (#log, #retest, #patterns, #import, and a tab per extension)
// and the Re-test badge. A route can carry more after a slash (#log/12); the view gets
// that part.
//
// Extensions (CLAUDE.md §15) are listed by /api/extensions. Each gets a tab and a section;
// its /ext/<name>/view.js is loaded the first time its tab opens, and has the same
// show(root, rest) as the built-in views.

import { api } from "./api.js";
import { showError } from "./ui.js";
import * as importView from "./views/import.js";
import * as log from "./views/log.js";
import * as patterns from "./views/patterns.js";
import * as retest from "./views/retest.js";

const VIEWS = { log, retest, patterns, import: importView };
const TITLES = { log: "Log", retest: "Re-test", patterns: "Patterns", import: "Import" };
const DEFAULT = "log";
const extensions = new Map(); // name -> its view module, a promise once it's asked for

function route() {
  const [name, ...rest] = location.hash.replace(/^#/, "").split("/");
  if (!(name in VIEWS) && !extensions.has(name)) {
    history.replaceState(null, "", "#" + DEFAULT);
    show(DEFAULT, "");
    return;
  }
  show(name, rest.join("/"));
}

async function show(name, rest) {
  for (const tab of document.querySelectorAll(".tab")) {
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  for (const view of document.querySelectorAll(".view")) {
    view.classList.toggle("on", view.id === "view-" + name);
  }
  document.title = TITLES[name] + " · Blunderbook";
  showError(null);
  let view;
  try {
    view = await viewOf(name);
  } catch (err) {
    extensions.set(name, null); // try again next time
    showError(`The ${TITLES[name]} tab couldn't be loaded: ${err.message}`);
    return;
  }
  view.show(document.getElementById("view-" + name), rest);
}

function viewOf(name) {
  if (name in VIEWS) return VIEWS[name];
  if (!extensions.get(name)) extensions.set(name, import(`/ext/${name}/view.js`));
  return extensions.get(name);
}

/** A tab, a section and the styles of each extension that has a page. */
async function addExtensions() {
  let list = [];
  try {
    list = await api("/api/extensions");
  } catch (err) {
    showError(err.message);
    return;
  }
  const tabs = document.querySelector(".tabs");
  const app = document.querySelector(".app");
  for (const x of list) {
    if (x.name in VIEWS || extensions.has(x.name)) continue;
    const tab = document.createElement("a");
    tab.className = "tab";
    tab.href = "#" + x.name;
    tab.dataset.view = x.name;
    tab.textContent = x.title;
    tabs.append(tab);
    const section = document.createElement("section");
    section.className = "view";
    section.id = "view-" + x.name;
    section.setAttribute("aria-label", x.title);
    app.append(section);
    if (x.css) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = `/ext/${x.name}/view.css`;
      document.head.append(link);
    }
    TITLES[x.name] = x.title;
    extensions.set(x.name, null);
  }
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
await addExtensions(); // first: #library/... must find its tab
route();
refreshBadge();
