# Blunderbook Journal

A [Blunderbook](../../README.md) extension: fast chess notes in Markdown, kept like a blog
for yourself. It never goes online.

## Turn it on

```sh
blunderbook ext install journal
```

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

Coming in the next slices: the Journal tab with Writing and Reading modes, ```` ```pgn ````
and ```` ```fen ```` blocks and moves in sentences that play on a board, `[[log 12]]` /
`[[game 40]]` links to your Log, Analyse, and the history and export on the page.
