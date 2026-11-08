# Blunderbook Library

A Blunderbook extension: openings, traps and tactics to study and practise. It's a separate
package (CLAUDE.md §15). It can read your Log but never changes it, and it makes no network calls.

Status: 11.2 of the roadmap. It has its content, a checker, two commands and a tab. Practise
and the links to your Log come in 11.3 and 11.4.

## Install and turn on

From the Blunderbook folder:

```sh
uv tool install . --with ./extensions/library
blunderbook ext enable library
blunderbook library list       # the entries
blunderbook library check      # check every entry (or: check FOLDER)
```

## The tab

Restart `blunderbook serve` after `ext enable library`, and the page has a Library tab:

- `#library` lists the entries: openings, traps, then tactics.
- `#library/legal-trap` opens one at the end of its line, on a board facing the side you
  play: its idea, its moves (step through them with the buttons or ← → Home End), and its
  replies. A sound reply is green and one that loses is red. Press any move of a reply to
  play it out on the board.

The routes, at `/api/ext/library`:

| Route | Gives |
|---|---|
| `GET /entries` | Every entry: `id`, `kind`, `name`, `side`, `opening`, `eco` |
| `GET /entries/{id}` | The same, plus `idea`, `start_fen`, `moves` and `next` (each reply's `moves`, `says`, `loses`). Each move has its `label`, `san`, `uci`, `move_no`, `color` and the `fen` after it, so the page needs no chess logic. 404 for an unknown id. |

Practise positions and their answers are never sent here: they come with an attempt in 11.3.

## Content

Each entry is one TOML file in `blunderbook_library/content/`: `openings/`, `traps/` or
`tactics/`. The file's name is the entry's id: lowercase letters, digits and dashes
(`legal-trap.toml`).

```toml
kind = "trap"                 # opening | trap | tactic: must match the folder
name = "Légal's trap"
opening = "Philidor Defence"  # optional
eco = "C41"                   # optional
side = "black"                # the side you practise as; the board faces it
moves = "1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 g6 5. Nxe5"
idea = """
What's going on, in a few plain sentences."""

[[next]]                      # optional, any number: replies at the end of moves
move = "5... Bxd1"
line = "6. Bxf7+ Ke7 7. Nd5#" # optional: what follows the move
says = "Takes the queen. The bishop and both knights mate in two moves."
loses = true                  # optional: it falls into the trap, or throws the position away

[[practise]]                  # at least one: a position to find the move in
answers = ["dxe5"]            # every move counted as right
prompt = "Find the move that doesn't lose."   # optional

[[practise]]                  # another, earlier in the line
after = "2. Nf3"              # optional: after this move of `moves`; none = the end
answers = ["d6", "Nc6"]       # the line's own next move (d6) must be one of them
```

- **Moves** are SAN, written as python-chess writes them, check and mate signs included
  (`Bxf7+`, `Nd5#`). Move numbers are optional, and checked when they're there: `5.` before
  White's move and `5...` before Black's.
- **`fen`** instead of (or before) `moves` starts from another position. Tactics use it.
- **Practise positions** must have your `side` to move. When the line goes on after one, its
  next move must be among the answers. A move marked `loses` in `next` can't be an answer.
- Anything else is a problem: unknown fields, a bad ECO code, two entries with the same name.

`blunderbook library check` reads every file and plays every line:

```
Checked 15 entries: 5 openings · 6 traps · 4 tactics
Every line is legal, and every practise answer is a legal move.
```

A problem names the file and the place in it, and the command exits with 1:

```
traps/legal-trap.toml: next 1: 7. Nd6# isn't legal after 6... Ke7.
14 entries fine · 1 problem
```

## Tests

`uv run pytest` in the Blunderbook folder runs them with the app's own (the workspace installs
this package in the dev environment).
