// The Journal tab (ROADMAP 19.3): your chess notes. `#journal` is the list, `#journal/12`
// reads a note, `#journal/12/write` writes it, `#journal/12/history` shows its earlier
// versions (19.5) and `#journal/new` starts one.
// `#journal?tag=traps` (or `?q=…`) opens the list filtered.
//
// Reading (./read.js) draws the tree the server made from the note, with the board beside
// it: there's no chess logic on the page. Writing (./write.js) is a plain textarea that
// saves when you pause.
//
// Keys, while this tab is open: Ctrl/Cmd+K finds a note, Ctrl/Cmd+E switches between
// Writing and Reading, Esc goes back to the list, and n starts a note.

import { api } from "/js/api.js";
import { fmtDate, localDay, plural } from "/js/format.js";
import { showError, toast } from "/js/ui.js";
import * as history from "./history.js";
import * as read from "./read.js";
import * as write from "./write.js";
import { MOD } from "./write.js";

const API = "/api/ext/journal/notes";
const MODES = ["write", "history"];
const UNTITLED = "Untitled";

let root = null;
let note = null; // the open note as the API sent it; null for the list or a new note
let mode = "list"; // "list" | "read" | "write" | "history"
let q = "";
let tag = "";
let listed = null; // the list's last answer
let token = 0; // only the newest note answer is drawn
let listToken = 0;
let searchTimer = 0;

const $ = (id) => document.getElementById(id);

export async function show(section, rest) {
  if (root !== section) build(section);
  const [path, query] = (rest || "").split("?");
  if (query !== undefined) {
    const params = new URLSearchParams(query);
    q = params.get("q") || "";
    tag = (params.get("tag") || "").toLowerCase();
    $("jSearch").value = q;
  }
  const saved = await write.leave();
  if (!saved.ok) {
    // The text you typed isn't saved yet: stay with it.
    history.replaceState(null, "", saved.id === null ? "#journal/new" : `#journal/${saved.id}/write`);
    toast("Your last changes aren't saved yet: " + saved.message);
    return;
  }
  const [first, second] = path.split("/");
  const mine = ++token;
  if (first === "new") openNew();
  else if (/^\d+$/.test(first)) await openNote(Number(first), MODES.includes(second) ? second : "read", mine);
  else openList();
  refreshList();
}

function build(section) {
  root = section;
  section.innerHTML = `<div class="journal journal-listing" id="jWrap">
    <aside class="journal-side" aria-label="Notes">
      <a class="btn primary journal-new" href="#journal/new">New note <span class="journal-key" aria-hidden="true">n</span></a>
      <button class="journal-find" type="button" id="jFind"><span>Find or jump to a note</span><span class="journal-kbd" aria-hidden="true">${MOD}K</span></button>
      <label class="journal-search">Search
        <input type="search" id="jSearch" placeholder="Titles, text, players, openings" autocomplete="off">
      </label>
      <div class="journal-tags" id="jTags" role="group" aria-label="Tags"></div>
      <p class="small journal-count" id="jCount" aria-live="polite"></p>
      <ul class="panel journal-notes" id="jNotes" aria-label="Your notes"></ul>
      <a class="small journal-export" id="jExport" href="/api/ext/journal/export" download hidden>Export every note as a .zip of Markdown files</a>
    </aside>
    <div class="journal-bar" id="jBar" hidden></div>
    <div class="journal-body" id="jBody"></div>
    <section class="journal-panel" id="jPanel" aria-label="Board" hidden></section>
  </div>
  <dialog class="journal-switch" id="jSwitch" aria-label="Find a note">
    <input class="journal-switchq" type="search" id="jSwitchQ" placeholder="Find a note, or start a new one" autocomplete="off"
      role="combobox" aria-expanded="true" aria-controls="jSwitchList" aria-autocomplete="list">
    <ul class="journal-switchlist" id="jSwitchList" role="listbox" aria-label="Notes"></ul>
    <p class="small journal-switchhelp">↑ ↓ to choose, Enter to open, Esc to close</p>
  </dialog>`;
  $("jFind").addEventListener("click", openSwitcher);
  $("jSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { q = $("jSearch").value.trim(); refreshList(); }, 120);
  });
  $("jSwitchQ").addEventListener("input", findInSwitcher);
  $("jSwitchQ").addEventListener("keydown", switcherKeys);
  $("jSwitch").addEventListener("close", () => { if (switchReturn?.isConnected) switchReturn.focus(); });
}

// ---------------------------------------------------------------- the three states

function layout(state, withPanel) {
  const wrap = $("jWrap");
  wrap.classList.toggle("journal-listing", state === "list");
  wrap.classList.toggle("journal-open", state !== "list");
  wrap.classList.toggle("journal-reading", state === "read");
  wrap.classList.toggle("journal-writing", state === "write");
  wrap.classList.toggle("journal-withpanel", withPanel);
  $("jPanel").hidden = !withPanel;
  $("jBar").hidden = state === "list";
}

function openList() {
  note = null;
  mode = "list";
  layout("list", false);
  $("jBar").replaceChildren();
  $("jPanel").replaceChildren();
  drawEmpty();
}

/** The body beside the list when no note is open (wide screens only). */
function drawEmpty() {
  if (mode !== "list") return;
  const none = listed && listed.total === 0;
  $("jBody").innerHTML = none
    ? `<div class="panel empty"><p>Your Journal is empty. Start a note with New note, or press n.</p>
        <p>Write in Markdown. A <code>\`\`\`pgn</code> block, a <code>\`\`\`fen</code> block and moves in a
        sentence, like 6. Nxd5??, play on a board when you read the note.</p></div>`
    : '<p class="panel empty">Open a note on the left, or start a new one.</p>';
}

function openNew() {
  note = null;
  mode = "write";
  layout("write", true);
  drawBar();
  write.open($("jBody"), $("jPanel"), null, writeHooks);
}

async function openNote(id, wanted, mine) {
  let data;
  try {
    data = await api(`${API}/${id}`);
  } catch (err) {
    if (mine !== token) return;
    note = null;
    mode = "list";
    layout("list", false);
    if (err.status === 404) {
      showError(null);
      $("jBody").innerHTML = '<p class="panel empty">There\'s no such note. It may have been deleted.</p>';
    } else {
      showError(err.message);
      $("jBody").innerHTML = '<p class="panel empty">This note couldn\'t be loaded.</p>';
    }
    return;
  }
  if (mine !== token) return;
  showError(null);
  note = data;
  mode = wanted;
  if (mode === "write") {
    layout("write", true);
    drawBar();
    write.open($("jBody"), $("jPanel"), note, writeHooks);
  } else if (mode === "history") {
    layout("history", false);
    $("jPanel").replaceChildren();
    drawBar();
    history.open($("jBody"), note, historyHooks);
  } else {
    drawBar();
    const chess = read.open($("jBody"), $("jPanel"), note, { onTag: pickTag, onChanged: changedInReading });
    layout("read", chess);
  }
}

const historyHooks = {
  status: (text) => { if (mode === "history") $("jStatus").textContent = text; },
  restored(saved, from) {
    note = saved;
    refreshList();
    toast(`The text from ${from} is back. The text before is kept in History.`);
    location.hash = `#journal/${saved.id}`;
  },
};

/** Reading mode changed the note (a line put into a game): keep it, and the list. */
function changedInReading(saved) {
  note = saved;
  drawBar();
  refreshList();
}

const writeHooks = {
  status: () => $("jStatus"),
  created(saved) {
    note = saved;
    // Still on the new note: give it its own address, without a new history entry.
    if (location.hash === "#journal/new") history.replaceState(null, "", `#journal/${saved.id}/write`);
    if (mode === "write") drawBar();
  },
  saved(saved) {
    if (note && note.id === saved.id) note = saved;
    refreshList();
  },
};

// ---------------------------------------------------------------- the bar over a note

function drawBar() {
  const bar = $("jBar");
  const id = note ? note.id : null;
  const link = (label, href, current) => {
    const a = document.createElement(href ? "a" : "span");
    a.textContent = label;
    if (href) a.href = href;
    if (current) a.setAttribute("aria-current", "page");
    if (!href && !current) a.setAttribute("aria-disabled", "true");
    return a;
  };
  bar.innerHTML = `<div class="journal-barl">
      <a class="journal-back" href="#journal">← All notes</a>
      <div class="journal-modes" id="jModes" role="group" aria-label="Mode"></div>
    </div>
    <div class="journal-barr">
      <span class="journal-status" id="jStatus" aria-live="polite"></span>
      <span class="journal-own" id="jOwn"></span>
    </div>`;
  $("jModes").append(
    link("Write", id === null ? null : `#journal/${id}/write`, mode === "write"),
    link("Read", id === null ? null : `#journal/${id}`, mode === "read"),
    link("History", id === null ? null : `#journal/${id}/history`, mode === "history"),
  );
  $("jModes").title = `${MOD}E switches`;
  if (mode === "read") $("jStatus").textContent = edited(note.updated_at);
  if (id === null) return;
  const own = $("jOwn");
  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "btn ghost";
  pin.id = "jPin";
  pin.textContent = note.pinned ? "Unpin" : "Pin";
  pin.setAttribute("aria-pressed", String(note.pinned));
  pin.addEventListener("click", togglePin);
  const del = document.createElement("span");
  del.id = "jDelBox";
  own.append(pin, " ", del);
  deleteButton();
}

/** "Edited just now", "Edited 5 min ago", "Edited 3 h ago", "Edited 12 Nov". */
function edited(timestamp) {
  const seconds = (Date.now() - new Date(timestamp).getTime()) / 1000;
  if (seconds < 60) return "Edited just now";
  if (seconds < 3600) return `Edited ${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `Edited ${Math.floor(seconds / 3600)} h ago`;
  return "Edited " + fmtDate(localDay(timestamp));
}

async function togglePin() {
  const want = !note.pinned;
  const id = note.id;
  try {
    const saved = await api(`${API}/${id}`, { method: "PATCH", body: { pinned: want } });
    if (!note || note.id !== id) return;
    note.pinned = saved.pinned;
    $("jPin").textContent = saved.pinned ? "Unpin" : "Pin";
    $("jPin").setAttribute("aria-pressed", String(saved.pinned));
    toast(saved.pinned ? "Pinned to the top of the list." : "Unpinned.");
    refreshList();
  } catch (err) {
    toast("Not changed: " + err.message);
  }
}

function deleteButton() {
  const box = $("jDelBox");
  box.innerHTML = '<button class="btn ghost danger" type="button" id="jDel">Delete</button>';
  $("jDel").addEventListener("click", askDelete);
}

/** "Delete" asks in its own place: Delete or Keep (Escape keeps). No browser dialogs. */
function askDelete() {
  const box = $("jDelBox");
  box.innerHTML = `<span class="journal-ask" role="group" aria-label="Delete this note?">
      <span class="small">Delete this note and its earlier versions? Only a backup can bring it back.</span>
      <button class="btn danger" type="button" id="jDelYes">Delete</button>
      <button class="btn ghost" type="button" id="jDelNo">Keep</button>
    </span>`;
  const keep = () => {
    deleteButton();
    $("jDel").focus();
  };
  $("jDelNo").addEventListener("click", keep);
  $("jDelYes").addEventListener("click", remove);
  box.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && $("jDelNo")) {
      ev.preventDefault();
      keep();
    }
  });
  $("jDelNo").focus();
}

async function remove() {
  const id = note.id;
  const title = note.title || UNTITLED;
  $("jDelYes").disabled = true;
  write.discard();
  try {
    await api(`${API}/${id}`, { method: "DELETE" });
  } catch (err) {
    toast("Not deleted: " + err.message);
    if ($("jDelYes")) $("jDelYes").disabled = false;
    return;
  }
  toast(`Deleted “${title}”.`);
  note = null;
  location.hash = "#journal";
}

// ---------------------------------------------------------------- the list

async function refreshList() {
  const mine = ++listToken;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (tag) params.set("tag", tag);
  let data;
  try {
    data = await api(`${API}?${params}`);
  } catch (err) {
    if (mine === listToken) showError(err.message);
    return;
  }
  if (mine !== listToken) return;
  listed = data;
  $("jExport").hidden = data.total === 0;
  drawTags();
  drawList();
  drawEmpty();
}

function drawTags() {
  const box = $("jTags");
  box.replaceChildren();
  const tags = listed.tags.map((t) => t.tag);
  if (tag && !tags.includes(tag)) tags.unshift(tag); // a filter by a tag no note has (any more)
  for (const name of tags) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "journal-tagchip";
    b.textContent = "#" + name;
    b.setAttribute("aria-pressed", String(name === tag));
    b.addEventListener("click", () => pickTag(name === tag ? "" : name));
    box.append(b);
  }
}

/** Keep one tag's notes (or all, with ""). Used by the chips and the tags in a note. */
function pickTag(name) {
  tag = name;
  refreshList().then(() => {
    const pressed = [...$("jTags").children].find((b) => b.getAttribute("aria-pressed") === "true");
    if (pressed && mode === "list") pressed.focus();
  });
  // From a note on a narrow screen, the list isn't on screen: go to it.
  if (mode !== "list" && name && root.querySelector(".journal-side").offsetParent === null) location.hash = "#journal";
}

function drawList() {
  const list = $("jNotes");
  list.replaceChildren();
  const shown = listed.notes.length;
  const filtering = Boolean(q || tag);
  $("jCount").textContent = filtering
    ? `${shown} of ${plural(listed.total, "note", "notes")}`
    : plural(listed.total, "note", "notes");
  if (!shown) {
    const li = document.createElement("li");
    li.className = "journal-none";
    li.textContent = listed.total ? "No notes match." : "No notes yet.";
    list.append(li);
    return;
  }
  for (const n of listed.notes) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.className = "journal-note";
    a.href = `#journal/${n.id}`;
    if (note && note.id === n.id) a.setAttribute("aria-current", "page");
    const top = document.createElement("span");
    top.className = "journal-ntop";
    const title = document.createElement("span");
    title.className = "journal-ntitle";
    title.textContent = n.title || UNTITLED;
    top.append(title);
    if (n.pinned) {
      const pinned = document.createElement("span");
      pinned.className = "journal-pinned";
      pinned.textContent = "Pinned";
      top.append(pinned);
    }
    a.append(top);
    if (n.snippet) {
      const snip = document.createElement("span");
      snip.className = "journal-snip";
      snip.textContent = n.snippet;
      a.append(snip);
    }
    if (n.tags.length) {
      const tags = document.createElement("span");
      tags.className = "journal-ntags";
      tags.textContent = n.tags.map((t) => "#" + t).join(" · ");
      a.append(tags);
    }
    li.append(a);
    list.append(li);
  }
}

// ---------------------------------------------------------------- the quick switcher

let switchReturn = null; // where the focus goes back to
let options = []; // [{label, hint, href}]
let chosen = 0;
let switchToken = 0;

function openSwitcher() {
  const dialog = $("jSwitch");
  if (dialog.open) return;
  switchReturn = document.activeElement;
  $("jSwitchQ").value = "";
  dialog.showModal();
  $("jSwitchQ").focus();
  findInSwitcher();
}

async function findInSwitcher() {
  const mine = ++switchToken;
  const words = $("jSwitchQ").value.trim();
  let found = [];
  try {
    const data = await api(`${API}?${new URLSearchParams(words ? { q: words } : {})}`);
    found = data.notes;
  } catch (err) {
    if (mine === switchToken) toast(err.message);
  }
  if (mine !== switchToken) return;
  options = found.slice(0, 8).map((n) => ({ label: n.title || UNTITLED, hint: n.pinned ? "Pinned" : "", href: `#journal/${n.id}` }));
  options.push({ label: "New note", hint: "n", href: "#journal/new" });
  chosen = 0;
  drawOptions();
}

function drawOptions() {
  const list = $("jSwitchList");
  list.replaceChildren();
  options.forEach((o, i) => {
    const li = document.createElement("li");
    li.className = "journal-option";
    li.id = "jOpt" + i;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(i === chosen));
    const label = document.createElement("span");
    label.textContent = o.label;
    const hint = document.createElement("span");
    hint.className = "small";
    hint.textContent = o.hint;
    li.append(label, hint);
    li.addEventListener("click", () => go(o));
    li.addEventListener("mousemove", () => { if (chosen !== i) { chosen = i; mark(); } });
    list.append(li);
  });
  mark();
}

function mark() {
  [...$("jSwitchList").children].forEach((li, i) => li.setAttribute("aria-selected", String(i === chosen)));
  $("jSwitchQ").setAttribute("aria-activedescendant", "jOpt" + chosen);
  $("jOpt" + chosen)?.scrollIntoView({ block: "nearest" });
}

function switcherKeys(ev) {
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    chosen = (chosen + (ev.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    mark();
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    if (options[chosen]) go(options[chosen]);
  }
}

function go(option) {
  switchReturn = null;
  $("jSwitch").close();
  location.hash = option.href;
}

// ---------------------------------------------------------------- keys

const TYPING = ["INPUT", "TEXTAREA", "SELECT"];

document.addEventListener("keydown", (ev) => {
  if (!root || root.offsetParent === null || ev.defaultPrevented) return; // not this tab
  const mod = (ev.metaKey || ev.ctrlKey) && !ev.altKey && !ev.shiftKey;
  const key = ev.key.toLowerCase();
  if (mod && key === "k") {
    ev.preventDefault();
    openSwitcher();
    return;
  }
  if ($("jSwitch").open) return;
  if (mod && key === "e" && mode !== "list") {
    ev.preventDefault();
    switchMode();
    return;
  }
  if (ev.key === "Escape" && mode !== "list") {
    location.hash = "#journal";
    return;
  }
  if (key === "n" && !ev.metaKey && !ev.ctrlKey && !ev.altKey && !TYPING.includes(ev.target.tagName) && mode !== "write") {
    ev.preventDefault();
    location.hash = "#journal/new";
  }
});

async function switchMode() {
  if (mode === "history") {
    location.hash = `#journal/${note.id}`;
    return;
  }
  if (mode === "read") {
    location.hash = `#journal/${note.id}/write`;
    return;
  }
  const saved = await write.leave();
  if (!saved.ok) {
    toast("Your last changes aren't saved yet: " + saved.message);
    return;
  }
  if (saved.id !== null) location.hash = `#journal/${saved.id}`;
  else toast("Write something first: there's nothing to read yet.");
}
