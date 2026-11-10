# Blunderbook Collection

A Blunderbook extension: collections of anyone's games, analysed by the same Stockfish and the
same rules as your own. It's a separate package (CLAUDE.md §15). Nothing here goes into your
Log, and it makes no network calls.

Status: done (M12 of the roadmap). It has its database, four commands (`import`, `list`,
`stats` and `players`) and a tab with each collection, its players and each game, where you
can add games too. A game that reached a position from your own Log links to that entry.

## Install and turn on

```sh
blunderbook ext install collection   # installs it and turns it on
```

## Add games

```sh
blunderbook collection import classics.pgn --into Classics
```

```
Analysing with Stockfish 17.1 at depth 16.
Game 1 · Paul Morphy vs Duke Karl / Count Isouard · added
Game 2 · Adolf Anderssen vs Lionel Kieseritzky · added
Game 3 · Kermur de Légal vs Saint Brie · added
New collection: Classics.
3 games read · 3 added
Classics: 3 games.
```

- **Any PGN file**, read as your own imports are: several games in one file, a game that
  can't be read is reported and the rest still go in, and a file that isn't UTF-8 is read as
  Windows-1252.
- **No side to pick.** Every move of both players is scored.
- **Every position is scored once** at `engine_depth` (or `--depth N`), as pass 1 of your own
  imports is: the eval from White's side, Stockfish's move and its line. The engine and the
  depth are kept with each game.
- **A collection is made with its first game**, so `--into` a new name makes one. Names are
  up to 60 characters, and `Classics` and `classics` are the same collection.
- **Each game is analysed once.** It's kept by the same fingerprint as your imports, so
  importing the file again adds nothing ("Already in Classics — skipped"), and adding a game
  to a second collection doesn't analyse it again ("added (already analysed)").
- **Each game is saved as soon as it's analysed.** If Stockfish stops, or you press Ctrl+C,
  the games before it are kept, and importing the file again finishes the rest.
- Before it changes anything, it takes the daily backup, as `blunderbook import` does.

Your own games belong in `blunderbook import`, so their blunders reach your Log.

### On the page

**Add games** (on the Collection tab, or on a collection's page, which fills in its name)
opens a form: the collection's name (a new one or one you have), and a PGN pasted, chosen or
dropped on the box. It runs on the server as `collection import` does, with the same rules
and the same report: a progress bar while Stockfish works, then each game's status, linked to
its game page, and the summary line.

- One import into a collection at a time; a second one waits ("Games are already being added
  to a collection"). It's separate from the Import tab's: one of each can run together, each
  with its own Stockfish.
- At most 10 MB of PGN. The depth is `engine_depth` from config.toml (there's no `--depth`).
- Stopping `blunderbook serve` stops the import between positions: the games added so far
  stay, and adding the same games again finishes the rest.

## See them

```sh
blunderbook collection list             # your collections
blunderbook collection list Classics    # the games in one
```

```
Classics · 3 games
  #1 Paul Morphy vs Duke Karl / Count Isouard · 1-0 · Paris · 1858 · C41 Philidor Defence · 17 moves
  ...
```

## Stats

```sh
blunderbook collection stats Classics                       # every game, both sides
blunderbook collection stats Classics --player "Adolf Anderssen"
blunderbook collection stats --color black --opening C4     # every collection
blunderbook collection players Classics                     # who played, and how well
```

```
Classics · 2 games · won 2 · drawn 0 · lost 0

                 Games  Moves  Accuracy  ACPL  ??  ?  ?!
Adolf Anderssen      2     47      84.7    41   4  1   2
Opponents            2     45      77.5    81   6  1   7

By phase (Adolf Anderssen's moves; the endgame is six pieces or fewer)
            Moves  ACPL  ??  ?  ?!
Opening        20    27   1  1   1
Middlegame     27    51   3  0   1
Endgame         0     —   0  0   0
```

Then the openings (games, score, accuracy) and each game (result, both sides' accuracy,
ACPL and marks). Without a name, `stats` and `players` cover every collection, each game
once.

**Filters:**

- `--player NAME` (ignoring case): their games, and their moves next to their opponents'.
- `--color white|black`: with `--player`, the colour they played; without, one side's moves.
- `--result`: `won` or `lost` (from `--player`'s side), `drawn`, or `white` / `black` for the side
  that won.
- `--opening`: an ECO code or its start (`C4` is C40 to C49), or part of the opening's name
  (`gambit`).
- `--phase opening|middlegame|endgame`: only the moves of that phase.

**How a move is judged**, the same way as your own (CLAUDE.md §7.6):

- **Marks:** `??` / `?` / `?!` come from the move's swing in winning chances and your
  `[thresholds]`. The engine's own move is never marked.
- **Accuracy** of a move is Lichess's formula on the mover's winning chances, from 0 to 100.
  A side's accuracy in a game is the average of the mean and the harmonic mean of its moves,
  so one bad move costs more than a plain average would show. Accuracy over several games is
  the mean of the games'.
- **ACPL** is the average centipawn loss: how far the mover's eval dropped, with evals capped
  at ±10 pawns (a mate counts as 10), so throwing away a won position doesn't swamp it.
- **Phases** are read from the position before the move. It's the endgame once there are six
  pieces or fewer besides kings and pawns, both sides together. Otherwise it's the opening up
  to move 10, then the middlegame.

Nothing about the marks is stored. They're worked out from the stored evals each time, so a
changed threshold applies at once.

**Stockfish with more than one thread** doesn't always give the same answer at the same
depth. With `engine_threads = 2`, Réti–Tartakower's 8... Nxe4 was scored as mate in 3 in
some runs and about +1 in others at depth 12. The default depth of 16, and one thread
(`engine_threads = 1`), gave the same answer in every run tried. It affects your own imports
the same way.

## The tab

Restart `blunderbook serve` after turning the Collection on, and it has a tab.

- **Collections:** each one with its number of games, and "All collections" (each game once)
  when you have more than one.
- **A collection:** the stats `collection stats` shows, with the same filters as menus
  (player, colour, result, opening, phase). Tiles for the games, the score, both sides'
  accuracy and centipawn loss, and the blunders; then the moves by phase, the openings, and
  every game with both sides' accuracy and marks. The filters are in the address
  (`#collection/1?player=Paul%20Morphy`), so a view can be bookmarked.
- **Players:** who played, with their games, colours, score and accuracy. Open one to see the
  collection's stats for them, their moves next to their opponents'.
- **A game:** the board, stepped with the buttons, the move list or the arrow keys (Home and
  End too); "next marked move"; an eval graph of White's winning chances, with each marked
  move as a dot (red `??`, amber `?`, blue `?!`), which you click to jump; both sides'
  accuracy, centipawn loss and marks; and for a marked move, Stockfish's move instead, its
  line, and the line after the move.
- **From your Log:** when a position of the game is the one before a move in your Log (the
  same pieces, side to move, castling and en passant; move numbers aside), the game lists
  that entry, linked to `#log/<id>`, with "Show it here" to step to that position.

Your thresholds are read from config.toml each time a page loads, so a changed threshold
shows at once. Adding games is the only thing on the tab that changes a collection, and
nothing on it changes your Log.

## collection.db

Next to Blunderbook's database, and in every `blunderbook backup` as `collection-….db`.

| Table | Holds |
|---|---|
| `collections` | Each collection's name. |
| `games` | Each game once: its headers (`?` is NULL), its PGN, the engine and depth. |
| `positions` | Every position of every game: its FEN, the move that led there (and the clock), the eval (White's side, JSON as in your Log), Stockfish's move and its line (up to 10 moves). |
| `members` | Which games are in which collection. |

Judgments (`??`, `?`, `?!`) aren't stored: they come from the evals and your thresholds, so
changing a threshold changes them everywhere.

## Tests

`uv run pytest` in the Blunderbook folder runs them with the app's own. Their fixtures are in
`tests/collection_fakes.py`, not a `conftest.py`: core's tests import their own `conftest` by
name.
