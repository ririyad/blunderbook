// Writing mode (ROADMAP 19.3): a plain monospace textarea. Nothing is drawn while you type:
// the text is saved 400 ms after you pause, one save at a time, in order, and the server
// reads it into the tree Reading mode draws. A new note is made by its first save.
//
// A pasted game (PGN headers, or moves on a line of their own) or position (a FEN on a line
// of its own) goes into its own ```pgn / ```fen block. Ctrl/Cmd+B and Ctrl/Cmd+I make the
// selection bold or italic.

import { api } from "/js/api.js";
import { plural } from "/js/format.js";

const API = "/api/ext/journal/notes";
const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
/** How the shortcuts are written here: "\u2318" on a Mac, "Ctrl+" elsewhere. */
export const MOD = MAC ? "\u2318" : "Ctrl+";
const SAVE_DELAY_MS = 400;
const FENCE = "```";

const PGN_HEADER = /^\s*\[[A-Za-z]\w*\s+"[^"\n]*"\]/;
const PGN_MOVES = /^\s*(?:\{[^}]*\}\s*)?\d{1,3}\.(?:\.\.)?\s*[KQRBNa-hO0]/;
const FEN_LINE = /^\s*[pnbrqkPNBRQK1-8]+(?:\/[pnbrqkPNBRQK1-8]+){7}(?:\s+[wb](?:\s[^\n]*)?)?\s*$/;
const NUMBERED = /(?:^|\s)\d{1,3}\.(?!\d)/g;

let id = null; // the note's id; null until a new note's first save
let area = null;
let hooks = null;
let unsaved = null; // text not sent yet, or null
let saving = Promise.resolve();
let timer = 0;
let failure = ""; // why the last save didn't work, or ""

const $ = (id) => document.getElementById(id);

/** Open `note` (or a new one, with null) for writing in `body`, with the hints in `panel`.
 *  hooks.status() is the save line; hooks.created(note) and hooks.saved(note) follow the
 *  saves. */
export function open(body, panel, note, opts) {
  id = note ? note.id : null;
  hooks = opts;
  unsaved = null;
  failure = "";
  body.innerHTML = `<div class="panel journal-write">
      <textarea class="journal-text" id="jwText" aria-label="Note text, in Markdown" spellcheck="true"
        placeholder="# A title&#10;&#10;Write in Markdown. Paste a game or a FEN and it goes into its own block."></textarea>
    </div>
    <p class="small journal-pasted" id="jwPasted" role="status"></p>
    <p class="small journal-syntax">
      <span># Heading</span><span>**bold** (${MOD}B)</span><span>_italic_ (${MOD}I)</span>
      <span>\`\`\`pgn … \`\`\`</span><span>\`\`\`fen … \`\`\`</span><span>#tag</span>
      <span>[[log 12]] · [[game 40]]</span><span>${MOD}E reads</span>
    </p>`;
  panel.innerHTML = `<div class="panel journal-hint">
      <strong>Writing is plain text, on purpose</strong>
      <p>Nothing is drawn while you type, so a long note stays smooth. It's saved when you pause.</p>
      <p>Read (${MOD}E) turns the blocks into boards. Moves in a sentence, like 6. Nxd5??, play from the game or diagram nearest them.</p>
    </div>`;
  area = $("jwText");
  area.value = note ? note.body : "";
  area.addEventListener("input", changed);
  area.addEventListener("paste", pasted);
  area.addEventListener("keydown", keys);
  status(note ? words(note.body) : "New note: it's saved once you type.");
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
}

/** Save what's unsaved before something else opens. Resolves to {ok, id, message}: ok is
 *  false when the text couldn't be saved (it's kept, and the save line says why). */
export async function leave() {
  await flush();
  if (unsaved !== null || failure) return { ok: false, id, message: failure || "it's still saving." };
  const left = { ok: true, id };
  area = null;
  return left;
}

/** Forget what's unsaved: the note is being deleted. */
export function discard() {
  clearTimeout(timer);
  unsaved = null;
  failure = "";
}

function changed() {
  unsaved = area.value;
  clearTimeout(timer);
  timer = setTimeout(flush, SAVE_DELAY_MS);
  if (!failure) status("Saving…");
}

/** Send the text, after any save already on its way. Resolves when it's done. */
function flush() {
  clearTimeout(timer);
  if (unsaved === null) return saving;
  const body = unsaved;
  unsaved = null;
  saving = saving.then(async () => {
    try {
      const created = id === null;
      const note = created
        ? await api(API, { method: "POST", body: { body } })
        : await api(`${API}/${id}`, { method: "PATCH", body: { body } });
      id = note.id;
      failure = "";
      if (created) hooks.created(note);
      hooks.saved(note);
      if (unsaved === null) status("Saved · " + words(body));
    } catch (err) {
      if (unsaved === null) unsaved = body;
      failure = err.message;
      status("Not saved: " + err.message, true);
    }
  });
  return saving;
}

// Closing the page: send what's left without waiting.
window.addEventListener("pagehide", () => {
  clearTimeout(timer);
  if (unsaved === null) return;
  const send = id === null
    ? api(API, { method: "POST", body: { body: unsaved }, keepalive: true })
    : api(`${API}/${id}`, { method: "PATCH", body: { body: unsaved }, keepalive: true });
  send.catch(() => {});
  unsaved = null;
});

const words = (body) => plural((body.match(/\S+/g) || []).length, "word", "words");

/** The save line: "Saving…", then "Saved", or in red with "Try again". */
function status(message, failed = false) {
  const line = hooks && hooks.status();
  if (!line) return;
  line.textContent = message;
  line.classList.toggle("journal-fail", failed);
  if (!failed) return;
  const again = document.createElement("button");
  again.type = "button";
  again.className = "btn ghost";
  again.textContent = "Try again";
  again.addEventListener("click", () => {
    failure = "";
    status("Saving…");
    flush();
  });
  line.append(" ", again);
}

// ---------------------------------------------------------------- typing help

function keys(ev) {
  const mod = (ev.metaKey || ev.ctrlKey) && !ev.altKey && !ev.shiftKey;
  const key = ev.key.toLowerCase();
  if (mod && (key === "b" || key === "i")) {
    ev.preventDefault();
    surround(key === "b" ? "**" : "_");
  }
}

/** Put `mark` on both sides of the selection, keeping it selected. */
function surround(mark) {
  const { selectionStart: from, selectionEnd: to } = area;
  const inner = area.value.slice(from, to);
  insert(mark + inner + mark);
  area.setSelectionRange(from + mark.length, from + mark.length + inner.length);
}

/** Type `text` over the selection, so Undo takes it back. */
function insert(text) {
  area.focus();
  if (!document.execCommand("insertText", false, text)) {
    area.setRangeText(text, area.selectionStart, area.selectionEnd, "end");
    changed();
  }
}

/** "pgn", "fen" or null: what a paste is, when it should get its own block. */
export function blockFor(pasted, before) {
  if (pasted.includes(FENCE) || insideBlock(before)) return null;
  const atLineStart = before === "" || before.endsWith("\n");
  if (PGN_HEADER.test(pasted)) return "pgn";
  if (!atLineStart) return null; // moves in a sentence stay in the sentence
  if (FEN_LINE.test(pasted)) return "fen";
  if (PGN_MOVES.test(pasted) && (pasted.match(NUMBERED) || []).length >= 3) return "pgn";
  return null;
}

const insideBlock = (before) => ((before.match(/^\s{0,3}```/gm) || []).length % 2) === 1;

function pasted(ev) {
  const text = ev.clipboardData && ev.clipboardData.getData("text/plain");
  if (!text) return;
  const before = area.value.slice(0, area.selectionStart);
  const kind = blockFor(text, before);
  if (!kind) return;
  ev.preventDefault();
  const lead = before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  insert(`${lead}${FENCE}${kind}\n${text.trim()}\n${FENCE}\n`);
  $("jwPasted").textContent = kind === "pgn"
    ? `The pasted game is in a \`\`\`pgn block. Read (${MOD}E) plays it.`
    : `The pasted position is in a \`\`\`fen block. Read (${MOD}E) shows it.`;
}
