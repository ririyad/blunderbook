# Blunderbook Collection

A Blunderbook extension: collections of anyone's games, analysed by the same Stockfish and the
same rules as your own. It's a separate package (CLAUDE.md §15). Nothing here goes into your
Log, and it makes no network calls.

Status: 12.1 of the roadmap (M12). It has its database and two commands: `import` and
`list`. Stats (12.2), a tab with each collection, game and player (12.3), and importing on
the page with links to your Log (12.4) come next.

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
