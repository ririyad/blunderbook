// History (ROADMAP 19.5): a note's earlier texts. Saving keeps the text it replaces when
// the newest kept one is over 5 minutes old, and the newest 30 stay. Pick one to see its
// text; "Bring this back" makes it the note's text again, and the text it replaces is kept
// first, so nothing is lost.
//
// Every text goes in with textContent.

import { api } from "/js/api.js";
import { fmtDate, localDay, plural } from "/js/format.js";

const NOTES = "/api/ext/journal/notes";

let note = null;
let hooks = null;
let versions = [];
let chosen = null; // a version id, or null for the text as it is now
let mine = 0; // only the newest listing is drawn

const $ = (id) => document.getElementById(id);

function el(tag, cls, content) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (content !== undefined) node.textContent = content;
  return node;
}

/** "Today, 14:05", "12 Nov, 14:05". */
export function when(timestamp) {
  const day = localDay(timestamp);
  const time = new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${day === localDay(new Date().toISOString()) ? "Today" : fmtDate(day)}, ${time}`;
}

/** Draw the history of `current` into `body`. hooks.restored(note) follows a bring-back;
 *  hooks.status(text) is the line in the bar. */
export async function open(body, current, opts) {
  note = current;
  hooks = opts;
  chosen = null;
  versions = [];
  const asked = ++mine;
  body.innerHTML = `<div class="journal-history">
      <div class="panel journal-versions">
        <p class="small journal-historyhelp" id="jhHelp"></p>
        <ul class="journal-versionlist" id="jhList" aria-label="Versions"></ul>
      </div>
      <div class="panel journal-preview" id="jhPreview" aria-live="polite"></div>
    </div>`;
  $("jhHelp").textContent = "Loading the versions…";
  let listing;
  try {
    listing = await api(`${NOTES}/${note.id}/versions`);
  } catch (err) {
    if (asked === mine) $("jhHelp").textContent = "The versions couldn't be loaded: " + err.message;
    return;
  }
  if (asked !== mine) return;
  versions = listing.versions;
  $("jhHelp").textContent = versions.length
    ? `When you pause for 5 minutes or more, the text before is kept here. The newest ${listing.kept} stay.`
    : "No earlier versions yet. When you edit after a pause of 5 minutes or more, the text before is kept here.";
  hooks.status(versions.length ? plural(versions.length, "earlier version", "earlier versions") : "");
  drawList();
  pick(versions.length ? versions[0].id : null, false);
}

function drawList() {
  const list = $("jhList");
  list.replaceChildren();
  const row = (id, title, detail) => {
    const li = el("li");
    const b = el("button", "journal-version");
    b.type = "button";
    b.dataset.id = id === null ? "now" : String(id);
    b.append(el("strong", "", title), el("span", "small", detail));
    b.addEventListener("click", () => pick(id, true));
    li.append(b);
    list.append(li);
  };
  row(null, "Now", `${plural(words(note.body), "word", "words")} · the note as it is`);
  for (const v of versions) row(v.id, when(v.saved_at), `${plural(v.words, "word", "words")} · ${v.title || "Untitled"}`);
}

const words = (text) => (text.trim() ? text.trim().split(/\s+/).length : 0);

async function pick(id, focus) {
  chosen = id;
  for (const b of $("jhList").querySelectorAll(".journal-version")) {
    b.setAttribute("aria-pressed", String(b.dataset.id === (id === null ? "now" : String(id))));
  }
  const box = $("jhPreview");
  if (id === null) {
    drawText(box, "The note as it is now", note.body, null);
    return;
  }
  const asked = ++mine;
  let shown;
  try {
    shown = await api(`${NOTES}/${note.id}/versions/${id}`);
  } catch (err) {
    if (asked === mine) box.replaceChildren(el("p", "journal-error", err.message));
    return;
  }
  if (asked !== mine) return;
  drawText(box, `From ${when(shown.saved_at)} · ${plural(shown.words, "word", "words")}`, shown.body, shown);
  if (focus) $("jhRestore")?.focus();
}

function drawText(box, heading, text, version) {
  box.replaceChildren();
  const head = el("div", "journal-previewhead");
  head.append(el("strong", "", heading));
  if (version) {
    if (version.body === note.body) {
      head.append(el("span", "small", "The same text as now."));
    } else {
      const b = el("button", "btn primary", "Bring this back");
      b.type = "button";
      b.id = "jhRestore";
      b.addEventListener("click", () => restore(version, b));
      head.append(b);
    }
  }
  box.append(head);
  if (version && version.body !== note.body) {
    box.append(el("p", "small", "Bringing it back keeps the text you have now as a version first."));
  }
  box.append(el("pre", "journal-versiontext", text || "(empty)"));
}

async function restore(version, button) {
  button.disabled = true;
  button.textContent = "Bringing it back…";
  let saved;
  try {
    saved = await api(`${NOTES}/${note.id}/versions/${version.id}/restore`, { method: "POST" });
  } catch (err) {
    button.disabled = false;
    button.textContent = "Bring this back";
    $("jhPreview").append(el("p", "journal-error", "Not brought back: " + err.message));
    return;
  }
  hooks.restored(saved, when(version.saved_at));
}
