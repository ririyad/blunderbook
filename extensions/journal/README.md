# Blunderbook Journal

A [Blunderbook](../../README.md) extension: fast chess notes in Markdown, kept like a blog
for yourself. It never goes online.

## Turn it on

```sh
blunderbook ext install journal
```

## The tab

- **The list:** New note at the top (or press `n`), then search, your tags and your notes,
  pinned first. Ctrl/Cmd+K finds a note from anywhere in the tab.
- **Writing:** a plain monospace text box. It's saved 400 ms after you pause, and the save
  line says so. A game (PGN headers, or a line of numbered moves) or a FEN you paste on a
  line of its own goes into its own block. Ctrl/Cmd+B and Ctrl/Cmd+I make the selection
  bold or italic.
- **Reading:** the note in a book typeface, with the board beside it (above it on a
  phone). Click a move, a diagram or a Log link and the board shows it; ← → Home End step
  through the line you're in, a variation included. "Flip the board" turns it round.
- Ctrl/Cmd+E switches between Writing and Reading; Esc goes back to the list.
- **Pin** keeps a note at the top of the list. **Delete** asks first, on the page.

## Commands

- `blunderbook journal new "# Title ..."` writes a new note. `--file NOTE.md` takes it from
  a file, and text piped in works too (`pbpaste | blunderbook journal new`).
- `blunderbook journal list` lists your notes, pinned first, then the latest edited.
  `--search WORDS` keeps the notes with every word (also as the start of a longer word), in
  the title, the text, or a PGN block's players, event, opening and ECO. `--tag NAME` keeps
  one tag's notes.
- `blunderbook journal show ID` prints a note's text as you wrote it.
- `blunderbook journal export FOLDER` writes every note to FOLDER as `ID-title.md`, made if
  missing. Exporting again replaces those files and touches nothing else in the folder.

## Notes

A note is plain Markdown, kept exactly as you typed it, in `journal.db` next to your
database and backed up with it.

- **The title** is the note's first line of text, without its `#`.
- **Tags** are words starting with `#` and a letter: `#traps`, `#caro-kann`. `# Heading`,
  `Qxf7#` and anything inside a ```` ``` ```` block aren't tags.
- **Versions.** Saving keeps the text it replaces when the newest kept version is over
  5 minutes old, so a long session leaves a version every few minutes. The newest 30 per
  note are kept.

## Chess in a note

Reading mode plays these on a board:

- A ```` ```pgn ```` block: a game, with its variations, `{comments}` and `$` marks.
  Headers may share a line.
- A ```` ```fen ```` block: a diagram. The position goes on the first line, then arrows
  and highlights as Lichess writes them (`{[%cal Rc3d5][%csl Rd5]}`) and a caption.
- Moves in a sentence: "after 5. cxd5 exd5 6. Nxd5?? the queen goes". A run starts with a
  numbered move. It plays from the nearest game or diagram above it that reaches that
  move, or from the nearest one below when there's none above, and shares that game's
  moves where it follows them. A run from 1. plays from the start. One that can't be
  played stays as text.
- A PGN or FEN that can't be read is shown as you wrote it, with the reason.
- `[[log 12]]` and `[[game 40]]` link to your Log. In a sentence they read as the move or
  the result and the opponent; on a line of their own they're a "From your Log" card with
  the re-test status and "Open →". A link to something that's no longer in your Log says
  so. The Journal only reads your Log, never changes it.

Coming in the next slices: playing on a board to insert moves, Copy FEN, Copy PGN up to
here, Continue here, Analyse, and the history and export on the page.
