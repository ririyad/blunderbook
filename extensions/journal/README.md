# Blunderbook Journal

A [Blunderbook](../../README.md) extension: fast chess notes in Markdown, kept like a blog
for yourself. It never goes online. Analyse uses your own Stockfish, only when you press it.

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
- **Insert from a board** (beside the text box while writing): play moves on a board, from
  the usual start, a diagram in the note or the end of one of its games. **Insert moves**
  puts them at the cursor, for a sentence; **As a PGN block** and **This position** (a
  ```` ```fen ```` block) put them on lines of their own. Tap a piece, then a square; a
  pawn on the last rank becomes a queen.
- **Reading:** the note in a book typeface, with the board beside it (above it on a
  phone). Click a move, a diagram or a Log link and the board shows it; ← → Home End step
  through the line you're in, a variation included. "Flip the board" turns it round.
- **Under the reading board:**
  - **Copy FEN** copies the position shown; **Copy PGN up to here**, the moves from the
    line's start to it.
  - **Continue here** lets you play on from the position shown. Then **Copy line**, or
    **Insert as a variation**, which writes your line into the game's PGN block (when the
    board shows a game's move or its start) and saves the note, keeping the text before
    as a version. A line from the game's last move continues the game. **Back to the
    note** leaves it.
  - **Analyse** asks your Stockfish for its three best lines at your `engine_depth`, with
    a green arrow for the best move. Only when you press it, one position at a time.
- Ctrl/Cmd+E switches between Writing and Reading; Esc goes back to the list.
- **History** (beside Write and Read) lists a note's earlier versions, newest first. Pick
  one to see its text; **Bring this back** makes it the note's text again, and keeps the
  text you have now as a version first, so nothing is lost.
- **Export every note as a .zip of Markdown files**, under the list, downloads one `.md`
  file per note, exactly as you wrote it, like `blunderbook journal export`.
- **Pin** keeps a note at the top of the list. **Delete** asks first, on the page.

## Starter notes

`examples/` has 15 notes to start from: 5 openings, 6 traps and 4 tactics, each with its
idea, a ```` ```pgn ```` game with the replies that matter (and `??` on the one that
loses), a ```` ```fen ```` diagram for a tactic, and a "Try it" list of positions to find
the move in. They were the Library extension's entries, before the Journal replaced it.

Add one, from the Blunderbook folder:

```sh
blunderbook journal new --file extensions/journal/examples/traps/elephant-trap.md
```

Or all of them. On macOS and Linux:

```sh
for f in extensions/journal/examples/*/*.md; do blunderbook journal new --file "$f"; done
```

In PowerShell:

```powershell
Get-ChildItem extensions/journal/examples -Recurse -Filter *.md | ForEach-Object { blunderbook journal new --file $_.FullName }
```

Each one becomes your own note, to change as you like. Adding the same file twice makes
two notes.

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
  note are kept. Bringing one back always keeps the text it replaces.
- **Export.** Each note is a file named by its number and title
  (`3-the-elephant-trap.md`), with its ```` ```pgn ```` and ```` ```fen ```` blocks and its
  tags as you typed them, and the time it was last edited.

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
