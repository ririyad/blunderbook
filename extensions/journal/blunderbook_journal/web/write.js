// Writing mode (ROADMAP 19.3): a plain monospace textarea. Nothing is drawn while you type:
// the text is saved 400 ms after you pause, one save at a time, in order, and the server
// reads it into the tree Reading mode draws. A new note is made by its first save.
//
// A pasted game (PGN headers, or moves on a line of their own) or position (a FEN on a line
// of its own) goes into its own ```pgn / ```fen block. Ctrl/Cmd+B and Ctrl/Cmd+I make the
// selection bold or italic.
//
// "Insert from a board" (19.4): play moves on a board, from the usual start, a diagram in
// the note or the end of one of its games, and put them in the text at the cursor: as moves
// in a sentence, as a ```pgn block, or the position as a ```fen block.

import { api } from "/js/api.js";
import { plural } from "/js/format.js";
import { toast } from "/js/ui.js";
import { player } from "./play.js";

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
let tree = null; // the note's tree as last saved, for the board's starting positions
let board = null; // the insert-from-board player, once it's opened
const STANDARD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

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
  tree = note ? note.doc : null;
  board = null;
  panel.innerHTML = `<div class="journal-insert">
      <button class="journal-toggle" type="button" id="jwToggle" aria-expanded="false" aria-controls="jwBox">
        <span>Insert from a board</span><span aria-hidden="true" id="jwChevron">+</span>
      </button>
      <div class="panel journal-insertbox" id="jwBox" hidden>
        <label class="journal-from">Start from <select id="jwFrom"></select></label>
        <div class="board" id="jwBoard"></div>
        <p class="journal-mono" id="jwLine" aria-live="polite"></p>
        <div class="journal-tools">
          <button class="btn primary" type="button" id="jwMoves">Insert moves</button>
          <button class="btn ghost" type="button" id="jwPgn">As a PGN block</button>
          <button class="btn ghost" type="button" id="jwFen">This position</button>
        </div>
        <div class="journal-tools">
          <button class="btn ghost" type="button" id="jwUndo">Take back</button>
          <button class="btn ghost" type="button" id="jwReset">Start again</button>
        </div>
      </div>
    </div>
    <div class="panel journal-hint">
      <strong>Writing is plain text, on purpose</strong>
      <p>Nothing is drawn while you type, so a long note stays smooth. It's saved when you pause.</p>
      <p>Read (${MOD}E) turns the blocks into boards. Moves in a sentence, like 6. Nxd5??, play from the game or diagram nearest them.</p>
    </div>`;
  $("jwToggle").addEventListener("click", toggleBoard);
  $("jwFrom").addEventListener("change", () => board.reset($("jwFrom").value));
  $("jwUndo").addEventListener("click", () => board.takeBack());
  $("jwReset").addEventListener("click", () => board.reset($("jwFrom").value));
  $("jwMoves").addEventListener("click", () => insertMoves(board.state.line));
  $("jwPgn").addEventListener("click", () => {
    insertBlock("pgn", board.state.pgn);
    toast("The moves are in your note, as a PGN block.");
  });
  $("jwFen").addEventListener("click", () => {
    insertBlock("fen", board.fen);
    toast("The position is in your note, as a FEN block.");
  });
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
      tree = note.doc;
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

// ---------------------------------------------------------------- insert from a board

const short = (text) => (text.length > 40 ? text.slice(0, 40).replace(/\s+\S*$/, "") + "\u2026" : text);

/** The positions the board can start from: the usual start, each diagram, and the end of
 *  each game's main line, from the note as last saved. */
function starts() {
  const found = [{ label: "The starting position", fen: STANDARD }];
  if (!tree) return found;
  let diagrams = 0, games = 0;
  for (const block of tree.blocks) {
    if (block.t === "fen" && block.playable) {
      diagrams += 1;
      found.push({ label: `Diagram ${diagrams}` + (block.caption ? `: ${short(block.caption)}` : ""), fen: tree.starts[block.start] });
    } else if (block.t === "pgn") {
      games += 1;
      const main = block.items.filter((item) => "move" in item);
      const last = main.length ? tree.moves.find((m) => m.id === main[main.length - 1].move) : null;
      found.push({ label: `The end of game ${games}`, fen: last ? last.fen : tree.starts[block.start] });
    }
  }
  return found;
}

async function toggleBoard() {
  const open = $("jwBox").hidden;
  $("jwBox").hidden = !open;
  $("jwToggle").setAttribute("aria-expanded", String(open));
  $("jwChevron").textContent = open ? "\u2212" : "+";
  if (!open) return;
  const select = $("jwFrom");
  const kept = select.value;
  select.replaceChildren();
  for (const start of starts()) {
    const option = document.createElement("option");
    option.value = start.fen;
    option.textContent = start.label;
    select.append(option);
  }
  if ([...select.options].some((o) => o.value === kept)) select.value = kept;
  if (!board) {
    board = player({
      board: $("jwBoard"),
      orient: () => (board && board.state && board.state.start.split(" ")[1] === "b" ? "black" : "white"),
      changed: boardChanged,
      failed: (message) => toast("That move can't be played: " + message),
    });
    await board.reset(select.value);
  } else if (board.state && board.state.start !== select.value && !board.state.moves.length) {
    await board.reset(select.value);
  }
}

function boardChanged() {
  const { state } = board;
  const side = state.fen.split(" ")[1] === "w" ? "White" : "Black";
  $("jwLine").textContent = state.moves.length
    ? state.line + (state.over ? ` (${state.over.toLowerCase()})` : "")
    : `${side} to move. Tap a piece, then a square.`;
  $("jwMoves").disabled = $("jwPgn").disabled = $("jwUndo").disabled = !state.moves.length;
}

/** Moves at the cursor, in the sentence you're writing. */
function insertMoves(text) {
  const before = area.value.slice(0, area.selectionStart);
  insert((before && !/\s$/.test(before) ? " " : "") + text);
  toast("The moves are in your note.");
}

/** A ``` block at the cursor, on lines of its own. */
function insertBlock(kind, text) {
  const before = area.value.slice(0, area.selectionStart);
  const lead = before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  insert(`${lead}${FENCE}${kind}\n${text.trim()}\n${FENCE}\n`);
}

function pasted(ev) {
  const text = ev.clipboardData && ev.clipboardData.getData("text/plain");
  if (!text) return;
  const before = area.value.slice(0, area.selectionStart);
  const kind = blockFor(text, before);
  if (!kind) return;
  ev.preventDefault();
  insertBlock(kind, text);
  $("jwPasted").textContent = kind === "pgn"
    ? `The pasted game is in a \`\`\`pgn block. Read (${MOD}E) plays it.`
    : `The pasted position is in a \`\`\`fen block. Read (${MOD}E) shows it.`;
}
