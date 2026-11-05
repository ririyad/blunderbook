# CLAUDE.md — Blunderbook

Blunderbook is a personal, local-first **chess mistake library**. It imports my games, uses
Stockfish to find my blunders, fills in everything a machine can fill in, and leaves the
parts that make me improve (what I was thinking, the lesson) for me to write. It then
re-tests me on those positions with spaced repetition and shows the patterns behind my
mistakes.

It replaces a printed A4 "Blunder Log" diary page. The app must keep that page's spirit:
minimal, focused, honest about what was automated and what wasn't.

Owner: Rashed (backend engineer, 10+ yrs). Single user. Runs on his own computer.

---

## 1. Product principles (read before every change)

1. **PGN is the core format.** Every game enters the core as PGN. Lichess and Chess.com are
   *optional adapters* that download PGN. The core must never depend on either site.
   If a site changes its API, only that adapter breaks.
2. **Automate the mechanical, never the reflection.** The app fills in position, moves,
   evals, best line, game metadata, clock data and *suggested* causes. It never writes
   "What I was thinking" or "Lesson", and never confirms a cause on the user's behalf.
3. **Local-first and private.** All data lives in one SQLite file on the user's machine.
   No accounts, no telemetry, no cloud. Network calls only happen in sync adapters, and
   only when the user runs a sync. Backups are local files too: the app never uploads them.
   For an off-site copy, the user points the backup folder at a folder their cloud drive syncs.
4. **Degrade gracefully.** Missing headers, ratings or clock times are normal (OTB games,
   typed-up score sheets). Show "—", skip the features that need the missing data, never fail
   the import.
5. **Same engine, same rules for every source.** Always run our own Stockfish analysis,
   even if a PGN already contains `[%eval]` annotations, so blunders are judged the same
   way everywhere. Store the engine version and depth with each analysis.
6. **No build step for the frontend.** Plain HTML, CSS and ES modules served by the
   backend. No React, no bundler, no npm toolchain for the app itself.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| PGN | Portable Game Notation: a full game record (headers, moves, comments, clocks). |
| FEN | One position as a string. No history, no players, no clocks. |
| SAN / UCI | Move notations: `Nxd5` (SAN, for humans) / `c3d5` (UCI, for engines and storage). |
| Eval | Engine score, stored **from White's point of view**: centipawns (`cp`) or `mate` in N. |
| Winning chances | `w(cp) = 2 / (1 + exp(-0.00368208 * cp)) - 1`, range −1..1 (Lichess formula). |
| Swing | `(w_mover(before) - w_mover(after)) / 2`, range 0..1, from the mover's point of view. |
| MultiPV | Ask the engine for its top N moves instead of one. |
| Entry | One logged blunder (a row in `blunders`). |

---

## 3. Tech stack

- **Python 3.15+**, managed with **uv** (`uv sync`, `uv run`).
- **python-chess**: PGN parsing, move legality, SAN/UCI, and the UCI engine wrapper.
- **Stockfish 17+** as an external binary (user-installed; path from config or `PATH`).
- **FastAPI + Uvicorn**: local web server and JSON API.
- **SQLite** via the stdlib `sqlite3` module, plus plain numbered SQL migrations. No ORM.
- **Typer**: CLI.
- **httpx**: HTTP in sync adapters only.
- **platformdirs**: config and data locations.
- **pytest**, **ruff** (lint and format), **mypy** (strict on `blunderbook/core`).
- Frontend: vanilla HTML/CSS/JS (ES modules). No frontend dependencies: the API sends the
  positions and legal moves the pages need.

Ask before adding any dependency that isn't on this list.

---

## 4. Repository layout

```
blunderbook/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── blunderbook/
│   ├── __init__.py
│   ├── cli.py                 # Typer app: init, doctor, engine, import, fen, sync, serve,
│   │                          #   print, backup, restore
│   ├── config.py              # load/save config.toml, paths via platformdirs, Stockfish lookup
│   ├── db/
│   │   ├── connection.py      # sqlite3 connection, PRAGMAs, migration runner
│   │   ├── migrations/        # 0001_init.sql, 0002_....sql (forward-only)
│   │   ├── backup.py          # VACUUM INTO snapshots, rotation, restore (see §6 [backup])
│   │   └── repo.py            # all data SQL lives here; returns dataclasses
│   ├── core/                  # pure logic, no I/O except the engine wrapper
│   │   ├── pgn.py             # split multi-game text, parse headers/moves/clocks
│   │   ├── timecontrol.py     # parse TimeControl, classify speed
│   │   ├── identity.py        # side detection from usernames, fingerprints
│   │   ├── source.py          # detect lichess / chesscom / otb / pgn from headers
│   │   ├── engine.py          # Stockfish wrapper (analyse position, MultiPV)
│   │   ├── detect.py          # winning chances, swing, judgment, blunder flagging
│   │   ├── hints.py           # suggested causes (time trouble, hung piece, ...)
│   │   ├── retest.py          # spaced-repetition scheduling
│   │   ├── patterns.py        # aggregates for the Patterns page
│   │   └── models.py          # dataclasses: Game, Blunder, Eval, Attempt, ...
│   ├── importer.py            # orchestrates: PGN text -> games -> analysis -> blunders
│   ├── sources/
│   │   ├── base.py            # SourceAdapter protocol: fetch_new_pgn(since) -> str
│   │   ├── lichess.py
│   │   └── chesscom.py
│   ├── api/
│   │   ├── app.py             # FastAPI app factory, static files mount
│   │   ├── routes_blunders.py
│   │   ├── routes_retest.py
│   │   ├── routes_patterns.py
│   │   └── schemas.py         # pydantic request/response models
│   └── web/                   # static frontend (no build)
│       ├── index.html
│       ├── css/app.css
│       ├── js/app.js          # router (hash-based: #log, #retest, #patterns)
│       ├── js/board.js        # board renderer (ported from the demo)
│       ├── js/views/*.js
│       └── print.html         # A4 print layout, 2 entries per page
├── tests/
│   ├── fixtures/pgn/          # sample games with known blunders (see §12)
│   ├── fixtures/http/         # recorded Lichess / Chess.com responses
│   └── test_*.py
└── docs/
    └── reference-demo.html    # the HTML demo built during planning (UI reference only)
```

`docs/reference-demo.html` is the approved UI prototype (Log, Re-test, Patterns,
Import). Port the Log, Re-test and Patterns views: their layout, copy, interactions and
board renderer. Its Import view is not part of v1 (imports run on the CLI). Don't copy its
storage or analysis code: the backend replaces those.

---

## 5. Data model (SQLite)

All timestamps are ISO-8601 UTC strings. Dates the user sees (game date, due date) are
local `YYYY-MM-DD`. Use `PRAGMA foreign_keys = ON` and `journal_mode = WAL`.
`PRAGMA user_version` holds the number of the last applied migration. Opening a database
with a higher number than the app knows fails with a plain message ("made by a newer
Blunderbook"). It never runs against it.

```sql
CREATE TABLE games (
  id              INTEGER PRIMARY KEY,
  fingerprint     TEXT NOT NULL UNIQUE,      -- see §7.4
  source          TEXT NOT NULL CHECK (source IN ('lichess','chesscom','pgn','otb','fen')),
  site_label      TEXT,                       -- e.g. "Over the board · Dhaka Chess Club"
  external_id     TEXT,                       -- site game id/URL when known
  white           TEXT, black TEXT,
  white_elo       INTEGER, black_elo INTEGER,
  my_color        TEXT NOT NULL CHECK (my_color IN ('white','black')),
  result          TEXT,                       -- '1-0' | '0-1' | '1/2-1/2' | '*'
  played_on       TEXT,                       -- YYYY-MM-DD, NULL if unknown
  time_control    TEXT,                       -- raw header, e.g. "180+2"
  tc_base_s       INTEGER, tc_inc_s INTEGER,
  speed           TEXT,                       -- bullet|blitz|rapid|classical|NULL
  opening         TEXT, eco TEXT,
  start_fen       TEXT NOT NULL,
  pgn             TEXT NOT NULL,              -- original text, verbatim
  has_clocks      INTEGER NOT NULL DEFAULT 0,
  analysis_status TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|error
  engine_name     TEXT, engine_depth INTEGER,
  imported_at     TEXT NOT NULL
);

CREATE TABLE blunders (
  id              INTEGER PRIMARY KEY,
  game_id         INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply             INTEGER NOT NULL,           -- 0-based index of my move in the game
  move_no         INTEGER NOT NULL,           -- fullmove number shown to the user
  fen_before      TEXT NOT NULL,
  played_uci      TEXT NOT NULL, played_san TEXT NOT NULL,
  best_uci        TEXT NOT NULL, best_san   TEXT NOT NULL,
  best_line_san   TEXT NOT NULL,              -- e.g. "6. e3 Be7 7. Bd3 c6"
  refutation_san  TEXT,                       -- engine line after my move
  accept_uci      TEXT NOT NULL,              -- JSON array of moves accepted in re-test
  eval_before     TEXT NOT NULL,              -- JSON {"cp":36} | {"mate":-2}, White POV
  eval_after      TEXT NOT NULL,
  swing           REAL NOT NULL,
  judgment        TEXT NOT NULL,              -- blunder|mistake|inaccuracy (FEN entries may log any)
  clock_left_s    REAL, time_spent_s REAL,
  auto_causes     TEXT NOT NULL DEFAULT '[]', -- JSON array, suggestions only
  causes          TEXT NOT NULL DEFAULT '[]', -- JSON array, confirmed by the user
  other_cause     TEXT,                       -- free text when "Other" is chosen
  thinking        TEXT NOT NULL DEFAULT '',
  lesson          TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','solved','missed')),
  streak          INTEGER NOT NULL DEFAULT 0,
  due_on          TEXT NOT NULL,              -- YYYY-MM-DD
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  UNIQUE (game_id, ply)
);

CREATE TABLE retest_attempts (
  id           INTEGER PRIMARY KEY,
  blunder_id   INTEGER NOT NULL REFERENCES blunders(id) ON DELETE CASCADE,
  attempted_at TEXT NOT NULL,
  move_uci     TEXT,                          -- NULL when the user gave up
  solved       INTEGER NOT NULL,
  used_hint    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX retest_attempts_blunder ON retest_attempts (blunder_id);  -- SQLite doesn't index FKs

CREATE TABLE sync_state (
  source        TEXT PRIMARY KEY,             -- 'lichess' | 'chesscom'
  username      TEXT NOT NULL,
  last_synced   TEXT,                         -- ISO time of newest game fetched
  last_run_at   TEXT,
  last_error    TEXT
);
```

There is no settings table. Every §6 setting lives in config.toml and nowhere else.

FEN quick entries get a synthetic `games` row (`source='fen'`, `pgn` = a one-move PGN with
`[SetUp "1"] [FEN "..."]`, `my_color` = side to move) so every blunder has a game.

The fixed cause list (keep this order everywhere: UI chips, print page, Patterns):

```python
CAUSES = [
    "Hung a piece", "Missed their threat", "Missed my tactic", "Miscalculated a line",
    "Time trouble", "Moved too fast", "Wrong plan", "Opening gap",
    "Endgame technique", "Overconfident / tilt", "Skipped blunder check", "Other",
]
```

---

## 6. Configuration

`config.toml` in `platformdirs.user_config_dir("blunderbook")`; the DB in
`user_data_dir("blunderbook")/blunderbook.db`. Created by `blunderbook init`.

**config.toml is the single source of truth for settings.** The CLI reads and writes this
file (through `config.load` / `config.save`). The web app has no settings page in v1. The DB
never stores these values.

```toml
my_names = ["Rashed"]                 # names/usernames used to detect my side
stockfish_path = ""                   # empty = look on PATH
engine_depth = 16                     # pass-1 depth per position
engine_threads = 2
engine_hash_mb = 128

[thresholds]                          # swing values, 0..1
inaccuracy = 0.05
mistake = 0.10
blunder = 0.15                        # only >= blunder is logged from imports
accept_margin_cp = 60                 # re-test accepts moves within this of best

[lichess]
username = ""
token = ""                            # optional personal token; never commit, never log

[chesscom]
username = ""
contact = ""                          # used in the User-Agent header Chess.com asks for

[backup]
dir = ""                              # empty = <data folder>/backups; may be a synced folder
keep = 14                             # newest backups kept (1 or more)
auto = true                           # back up once a day before commands that change data
```

Never print the Lichess token, never write it to the DB, and redact it from error messages.

The app writes config.toml from a fixed, commented template (stdlib `tomllib` can only read).
Your own comments aren't kept, and strings are written as TOML literal strings when possible,
so Windows paths stay readable.

**Stockfish lookup** (first match wins): `--stockfish PATH` option → `BLUNDERBOOK_STOCKFISH`
env var → `stockfish_path` → `stockfish` on `PATH`. A setting that is present but broken is an
error naming that setting. It never falls through to the next one. Paths accept surrounding
quotes, `~` and env vars. A relative `stockfish_path` is relative to the config folder. A
folder is searched, plus one level down, for a single `stockfish*` program (the unzipped
release). The program must identify as Stockfish over UCI. Older than 17 gives a warning, not
an error. `blunderbook engine set` checks a path before saving it.

**Backups** (`db/backup.py`):
- **Snapshot.** Use `VACUUM INTO`, never a file copy: with WAL, recent changes can sit in
  `-wal`. Write the snapshot to a temp file in the data folder and pass `PRAGMA
  integrity_check`. Then copy it into the backup folder as
  `blunderbook-YYYY-MM-DD_HHMMSSZ[-reason].db.partial` (UTC) and rename it to `.db`. Close
  every connection (`contextlib.closing`).
- **Rotation.** Delete only files whose names match that generated pattern, oldest first,
  beyond `keep`. Never touch other files in the folder. Rotate only after the new backup
  succeeded.
- **Automatic.** If `auto` is on, back up before a command that changes data (`serve` start,
  `import`, `fen`, `sync`) when the newest backup is over 24 h old. Read that age from the file
  names. A failed automatic backup prints one warning and never blocks the command. Always back
  up before migrating a database that has data (`-pre-migrate`).
- **Restore.** Check the file's integrity and that its `user_version` isn't newer than the app.
  Back up the current DB (`-pre-restore`). Then copy the file in with SQLite's backup API
  (`Connection.backup`), never by replacing the file (a stale `-wal` would corrupt it), and
  migrate.
- **What's not included.** Backups hold the DB only. config.toml (and the token) is never
  backed up. On a new computer, run `init`, then `restore`.
- **Folder.** The live DB never goes in a synced folder; only backups do. `backup.dir` accepts
  quotes, `~` and env vars, like `stockfish_path`.

---

## 7. Core logic (exact rules)

### 7.1 PGN parsing (`core/pgn.py`)
- Accept multi-game text. Split with python-chess (`chess.pgn.read_game` in a loop over a
  `StringIO`), not with regexes.
- Normalize line endings. Accept a bare move list with no headers.
- Collect per game: headers, mainline moves (ignore variations), `before`/`after` FEN for
  each ply, and the `[%clk h:mm:ss(.f)]` value from each move's comment.
- A game that fails to parse goes into the import report with a reason. Never abort
  the whole file because of one bad game.
- Standard chess only. Variants (Chess960, Atomic, unknown ones) and null moves (`--`) are
  rejected with a plain reason, e.g. "Chess960 isn't supported, only standard chess."
- python-chess skips tokens that don't look like SAN, so check each game's mainline text:
  - A token that was only skipped (`Ke9`, `resigns`) keeps the game, with a warning:
    "Skipped unreadable text 'Ke9' at 2."
  - A token that was misread (`♘f3` read as the pawn move `f3`) rejects the game:
    "Couldn't read '♘f3' at 2."
  - An illegal move after skipped text names both: "Illegal move 2. Nc6 (after unreadable
    text 'O-0')".
  - Symbols such as `±` are left alone.
- Keep the original PGN text verbatim in `games.pgn`.
- Read PGN files as `utf-8-sig`. If that fails, decode as `cp1252` with undecodable bytes
  replaced, and add "Read as Windows-1252" to the import report. Never fail an import over
  encoding. (ChessBase and older OTB files are often cp1252.)

### 7.2 Time control (`core/timecontrol.py`)
- Parse `"180"`, `"180+2"`, `"1500+10"`. `"-"`, `"?"`, or missing → `None`.
- Speed from the estimate `base + 40 * inc` (seconds):
  `< 180` bullet, `< 480` blitz, `< 1500` rapid, else classical.
- Display label in minutes: `180+2` → `"3+2"`, `1500+10` → `"25+10"`.

### 7.3 Side detection (`core/identity.py`)
- Case-insensitive, trimmed match of the `White`/`Black` headers against `my_names`
  (plus the configured Lichess/Chess.com usernames).
- No match, or both players match (two of my accounts, a game against myself) → the game is
  `needs_side`. The import report lists it, and `import --side` fills it in. Never guess.
- `--side` never overrides a name match. It only fills games that need a side.

### 7.4 Fingerprint / dedupe
- If the PGN has a site game URL (`[Site "https://lichess.org/abcd1234"]`, Chess.com
  `[Link "..."]`), fingerprint = `sha1(source + ":" + game_id)`.
- Otherwise fingerprint = `sha1(lower(white) | lower(black) | date | first 30 SAN moves)`.
  A game that doesn't start from the standard position adds its start FEN, so two typed-up
  positions with no names or date and the same first move don't collide.
- An already-known fingerprint is reported as "Already imported — skipped". The same game
  twice in one file: the second is "Same game as game N — skipped". Importing the same file
  twice must add nothing.
- Every analysed game is saved, even with no blunders, so it's skipped next time. Deleting an
  entry keeps its game, so a deleted blunder doesn't come back on the next import. Games that
  need a side, games that fail to parse, and a game whose analysis stopped are not saved, so
  importing them again works.

### 7.5 Source detection (`core/source.py`)
- `Site` or `Event` contains `lichess` → `lichess`; contains `chess.com` → `chesscom`.
  "chess.com" must be a whole name: `playchess.com` (ChessBase's server) is a PGN file.
- `Site` present and not a URL/domain → `otb`, label `"Over the board · {Site}"`. A dot with a
  capitalised ending (`St.Louis`) is a place; `playchess.com` and `www.chess24.com/en` are
  websites. `Site "INT"` / `"Internet"` stays "Over the board · INT".
- Otherwise `pgn`, label `"PGN file"`.
- Lichess game id: the first 8 characters of the Site path (a 12-character player link is cut
  to 8; `/white` or `/black` is ignored). Pages such as `/study/...`, `/broadcast/...` and
  `/analysis` give no id, so those games use the content fingerprint.
- Chess.com game id: from `Link`, then `Site`, keeping the game type (`live/140512345678`,
  `daily/…`). Both `/game/live/<id>` and the older `/live/game/<id>` are accepted.

### 7.6 Analysis and blunder detection (`core/engine.py`, `core/detect.py`)
- **Pass 1:** analyse every position in the game once at `engine_depth`
  (positions 0..N, where position i+1 is after ply i). Cache `{score, best, pv}` per position.
  Each position is sent with the game's moves (so Stockfish sees repetitions), and each game
  starts with `ucinewgame`. Depth is the only limit; there is no time limit per position.
  - Terminal positions are not sent to the engine: checkmate → `mate 0` (lost for the side
    to move); stalemate and draws that end the game by themselves (insufficient material,
    75 moves, fivefold repetition) → `cp 0`. Threefold and the 50-move rule only count when
    claimed, so those positions still go to the engine.
  - Convert engine scores to **White POV** before storing.
  - Mate scores map to ±10000 cp for winning-chance maths only. Store them as `{"mate": n}`.
- For each of **my** plies i:
  `swing = (w(sign*cp(before_i)) - w(sign*cp(after_i))) / 2`, with `sign = +1` for White,
  `−1` for Black, and never below 0. Flag when `swing >= thresholds.blunder` **and** the
  played move ≠ the engine's best move.
- "Best was" (`best_uci`, `best_line_san`) comes from pass 1: the move that triggered the flag.
- **Pass 2** (flagged positions only): MultiPV 3 at the same depth. It only decides
  `accept_uci`: moves whose mover-POV cp is within `accept_margin_cp` of the top line
  (inclusive; mates count as ±10000 here too). Always include the best move. Never include the
  move I played.
- `best_line_san`: first 6 plies of the best PV with move numbers
  (`"6. e3 Be7 7. Bd3"`, Black start `"5... Nxe5 6. Be2"`).
  `refutation_san`: first 5 plies of the PV from the position after my move. Both stop at an
  illegal PV move.
- Judgment labels: `>= 0.15` blunder, `>= 0.10` mistake, `>= 0.05` inaccuracy.
  config.toml must have `inaccuracy <= mistake <= blunder`.
- Analysis runs during the import. Report progress as positions done / total: the total starts
  at N + 1 and grows by the number of flagged moves when pass 1 ends. The CLI shows it as a
  percentage.
- One engine process per import. Always close it, even on errors or Ctrl+C (context manager).

### 7.7 Suggested causes (`core/hints.py`)
Suggestions only (dashed "auto" chips in the UI). The user confirms them.
- **Time trouble:** clock left `< 10%` of base or `< 20 s`. Needs clocks and a time control.
- **Moved too fast:** time spent `<= 3 s` while clock left `> 30%` of base. Time spent =
  my previous clock − my clock now + increment (for my first move, base − clock + inc).
  - A game that doesn't start from the standard position: the first move's time is unknown
    (the game started midway).
  - A negative result (e.g. the opponent added time) is unknown, not 0.
- **Missed their threat:** eval after my move is a forced mate against me. It wins over
  "Hung a piece"; the time rules can appear alongside either.
- **Hung a piece:** not the mate case, and my material balance drops by `>= 3` after playing
  out up to 6 plies of the refutation PV (P=1, N=B=3, R=5, Q=9), compared with the position
  before my move.
- No clock data or no `TimeControl` → skip the time rules silently. Clocks without a time
  control still give the clock left. The report says "No clock times in this PGN".

### 7.8 Re-test scheduling (`core/retest.py`)
- New entries are due the day they're created.
- Solved → `streak += 1`, `due_on = today + INTERVALS[min(streak-1, 5)]`,
  with `INTERVALS = [1, 3, 7, 14, 30, 60]` days. Status `solved`.
- Missed or gave up → `streak = 0`, `due_on = tomorrow`, status `missed`.
- A move counts as solved if its first 4 UCI chars match any move in `accept_uci`
  (promotion defaults to queen).
- Using the hint is recorded (`used_hint`) but doesn't change scheduling in v1.
- Queue order: oldest `due_on` first, then most recent game.

### 7.9 Patterns (`core/patterns.py`)
- Cause counts: confirmed causes, plus auto-causes for entries with no confirmed causes yet,
  returned separately (`confirmed`, `suggested`) so the UI can draw solid and striped bars.
- Tiles: total entries (per source), due today, % currently solved among re-tested entries,
  "played in ≤3 s" among entries with clock data, entries with < 30 s on the clock.
- By speed, by source, and "biggest leak" = the cause with the highest total.

---

## 8. Sources

All adapters implement:

```python
class SourceAdapter(Protocol):
    name: str                                     # 'lichess' | 'chesscom'
    def fetch_new_pgn(self, since: datetime | None) -> Iterator[str]: ...
```

They return **PGN text only**. The importer does everything else.

- **Lichess:** user games export endpoint, streaming PGN, with clocks and opening names
  enabled, filtered by `since`. Optional bearer token. Respect HTTP 429: back off and retry.
- **Chess.com:** published-data API. List the monthly archives, then download each needed
  month as PGN. Requests strictly one at a time. Send a descriptive `User-Agent` that
  includes `chesscom.contact`. Past months never change, so download only the months from the
  last synced month onward. No HTTP cache table.
- Before implementing either adapter, **check the current official API docs** and note the
  exact endpoints and parameters in a comment at the top of the file. Don't rely on memory.
- Store progress in `sync_state`. A failed sync records `last_error` and doesn't touch
  existing data.
- Sync runs from the CLI only (`blunderbook sync`). The web app has no Sync buttons in v1.
- Tests use recorded responses from `tests/fixtures/http/`. **Tests never call the
  network.** (The cloud dev environment can't reach these sites anyway.) Until real responses
  are recorded, the fixtures are hand-built from the documented formats and marked
  `TODO(verify)`.

---

## 9. CLI (`blunderbook ...`)

| Command | Does |
|---|---|
| `init` | Create config and DB, ask for names, the Stockfish path (Enter = PATH) and the backup folder (suggests `%OneDrive%\Blunderbook` when set; Enter = local default), check Stockfish. |
| `doctor [--stockfish PATH]` | Check Stockfish path and version, DB integrity and schema version, last backup (warns after 7 days or if the folder is missing), config sanity. Reports only; changes nothing. |
| `engine show` | Which Stockfish is used, its version, and where the setting came from. |
| `engine set PATH` | Resolve a program or folder, check it's Stockfish, save it as `stockfish_path`. Saves nothing if the check fails. |
| `engine clear` | Set `stockfish_path = ""` (look on PATH again). |
| `import PATH [--side white\|black] [--depth N] [--stockfish PATH]` | Import a PGN file. `--side` applies to games with no name match; otherwise they're listed as needing a side. |
| `fen "FEN" --move e2e4 [--opponent X] [--date YYYY-MM-DD] [--stockfish PATH]` | Quick entry for one position. Logs it even below the blunder line, with its judgment. |
| `sync [lichess\|chesscom\|all]` | Run adapters, then import. |
| `serve [--port 8732] [--open]` | Start the web app on `127.0.0.1` only. |
| `print [--ids 1,2] [--due] --out FILE.html` | Write the A4 print page (2 entries per page). |
| `backup [--to FOLDER]` | Take a verified snapshot now and rotate old ones (see §6 Backups). |
| `restore FILE [--yes]` | Replace the DB with a backup after checking it; keeps a `-pre-restore` copy. Asks to confirm and that the web app is stopped. |

Every command prints a short, readable summary, e.g.
`2 games read · 1 skipped (duplicate) · 1 needs side · 3 blunders added`.

Exit codes: `import` exits 1 only when it can't run (the file can't be read, it holds no
games, there's no Stockfish while some game is ready, or the engine fails; in that last case
the games done so far are reported first). A report with needs-side games or errors exits 0.
`doctor` exits 1 when it finds a problem.

---

## 10. HTTP API (JSON, `/api`)

Bind to `127.0.0.1` only. No auth (single local user).

```
GET    /api/blunders?source=&status=&cause=&due=1     list (summary fields)
GET    /api/blunders/{id}                             full entry + game metadata + move list
                                                      + the FEN for each ply (step controls)
PATCH  /api/blunders/{id}                             {causes?, other_cause?, thinking?, lesson?}
DELETE /api/blunders/{id}

GET    /api/retest/queue          due entries (position, side to move, move no., legal moves)
POST   /api/retest/{id}/attempt   {move_uci|null, used_hint} -> solved, best, lesson, next due
GET    /api/retest/{id}/hint      the from-square only

GET    /api/patterns
```

Imports, FEN entries, settings, the engine path and syncs go through the CLI only. There are
no routes for them in v1.

The list is newest first (one game's entries in move order). `cause=` matches entries where
the cause is confirmed, or where nothing is confirmed yet and it's suggested, as in the demo.

Re-test queue responses must **not** include `best_uci`, `accept_uci`, the played move or
the lesson. Each item does carry its legal moves (`legal_uci`) for tap-to-move: they don't
give the answer away. The answer comes only from the attempt endpoint, and the server checks
every attempt.

---

## 11. Frontend (port the reference demo)

Views (hash routes): `#log`, `#retest`, `#patterns`. Header: brand and tabs, with a
due-count badge on Re-test. Games are added on the CLI (`blunderbook import`), so there is no
Import view or add button in v1.

- **Log:** filter bar (source, status, cause) and list. Detail panel has the board with
  red arrow and highlight for my move, an optional green arrow for the best move, step
  controls (start / back / forward / jump to the blunder), "I played" and "Best was" boxes
  with the refutation and best line, an eval bar with winning chances before → after, a
  metadata grid (source, time control, result, ratings, clock left, time on move), cause
  chips (auto suggestions dashed with an "AUTO" tag), "What I was thinking" and "Lesson"
  textareas with autosave (debounced PATCH, "Saved" message), and the re-test status.
  Step controls use the per-ply FENs from the API. The empty state says "Import a PGN with
  `blunderbook import FILE.pgn`".
- **Re-test:** board facing my side, "White/Black to move — find the best move", tap a piece
  then tap a square (only the legal moves from the API), "Show a hint" (from-square), "I don't
  know — show me". The result panel shows solved or missed, the best line, what I played in
  the game, my lesson, and the next due date. An empty state offers "Practise all anyway".
- **Patterns:** four tiles, cause bars (solid = confirmed, striped = suggested), by time
  control, re-test history, a one-line "biggest leak" insight.
- **Print page** (`print.html`): A4, black and white, two entries per page, laid out like
  the original paper Blunder Log (board diagram, game info, I played / Best was, causes
  ticked, thinking, lesson, "Re-tested on ___ ☐ Solved ☐ Missed again"). Printed through the
  browser's print dialog.

Design language (from the demo and the paper template):
- Neutral paper background `#f7f5f0`, white panels, ink `#1b1b1b`, muted text `#5c5c5c`
  (keep contrast ≥ 4.5:1), hairlines `#e3dfd6`.
- Accents only with meaning: red `#b83227` = my move / blunder, green `#1d7a52` = best /
  solved, amber `#9a6412` = due / suggested, blue `#2a5d9f` = new / info.
- Title in Georgia/serif, everything else system sans. No gradients, no emoji, no drop
  shadows beyond 1px.
- Board: light `#ece6d9`, dark `#a99f8b`, Unicode chess glyphs with `︎`, coordinates
  in the corners, SVG arrows with polygon heads. Board faces the side I played.
- Accessibility: real `<button>`s (board squares in interactive mode are buttons with
  `aria-label` like "e4 white pawn"), visible focus, `aria-live` for saved and feedback
  messages, works at 390 px wide.

---

## 12. Testing

- `uv run pytest` must pass before every commit. `uv run ruff check . && uv run ruff format --check .` too.
- Tests needing Stockfish are marked `@pytest.mark.engine` and skipped when no binary is
  found. Engine tests use a fixed depth (12, one thread) and assert **which move gets
  flagged**, never exact centipawn values. Where the table names a best move, the test checks
  it's an accepted re-test answer, not the engine's first choice. Some fixtures have extra
  real blunders (4. Nxe5 in `blackburne_shilling`, 4... g6 in `legal_trap`); the tests
  require the listed move, not only that move.
- Fixtures in `tests/fixtures/pgn/` (known blunders, engine-verified during planning):

| File | My side | Expected blunder | Notes |
|---|---|---|---|
| `qgd_elephant.pgn` | White | `6. Nxd5??` (best `e3`) | 1.d4 d5 2.c4 e6 3.Nc3 Nf6 4.Bg5 Nbd7 5.cxd5 exd5 6.Nxd5 |
| `scholars_mate.pgn` | Black | `3... Nf6??` → mate in 1 | 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6; hint "Missed their threat" |
| `legal_trap.pgn` | Black | `5... Bxd1??` (best `dxe5`) | 1.e4 e5 2.Nf3 d6 3.Bc4 Bg4 4.Nc3 g6 5.Nxe5 Bxd1 |
| `blackburne_shilling.pgn` | White | `5. Nxf7??` (best `O-O`) | 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nd4 4.Nxe5 Qg5 5.Nxf7 |
| `back_rank.pgn` | White | `32. Rc7??` → mate in 1 | `[FEN "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"]`, clocks with ~9 s left; hint "Time trouble" |
| `petroff_trap.pgn` | Black | `4... Nf6??` (best `Qe7`) | 1.e4 e5 2.Nf3 Nf6 3.Nxe5 Nxe4 4.Qe2 Nf6 |
| `otb_club_no_clocks.pgn` | White ("Rashed") | `13. Nc3??` (best `h3`) | Site "Dhaka Chess Club", no clocks → OTB, no time hints |
| `chesscom_unmatched_name.pgn` | Black ("rashed_blitz", not in names) | `5... Ngf6??` | Caro-Kann, 6.Nd6#; must come back as `needs_side` |
| `multi_game.pgn` | — | — | Several games, one deliberately broken; report shows it, others import |

- Unit tests (no engine): time-control parsing and speed, clock parsing, time-spent maths
  with increment, side detection, fingerprints and dedupe, source detection, the
  winning-chance and swing maths, judgment thresholds, re-test intervals, accept matching,
  hint rules (with a stubbed engine), patterns aggregation.
- API tests with FastAPI `TestClient` and a temp DB. Assert that the re-test queue never
  leaks the answer.
- Sync adapter tests use recorded HTTP fixtures (httpx `MockTransport`).

---

## 13. Milestones (one focused session each)

1. **Core:** repo scaffold, config, `core/` modules, engine wrapper, `importer.py`, CLI
   `init/doctor/import`. Done when all §12 fixtures give the expected blunders.
2. **Storage:** migrations, `repo.py`, dedupe, `fen` command, import report, backup and
   restore. Done when importing the same file twice adds nothing, and backup → change →
   restore gives back the old data.
3. **API + Log view:** FastAPI app, blunder routes, frontend shell plus Log view ported
   from the demo, autosave notes.
4. **Re-test + Patterns:** scheduling, attempt and hint endpoints, both views.
5. **Sync:** Lichess and Chess.com adapters against recorded fixtures, `sync` command.
6. **Print + polish:** print page, `serve --open`, README with install steps (Stockfish on
   macOS/Windows/Linux), empty states, error messages.

Future (not v1): web import (paste or drop a PGN, side picker, progress), FEN board editor in
the browser, settings page, optional "coach" explanation of a blunder via an LLM API (opt-in,
off by default, key in config), Anki/Lichess-study export, mobile-friendly PWA.

---

## 14. Working rules for Claude Code

- Read this file and the relevant view in `docs/reference-demo.html` before starting a task.
- Work on one milestone at a time. Keep commits small, with messages like `core: swing maths + tests`.
- When a roadmap slice is finished, tick it in `README.md`, update the Status table and
  "Next up", and move any resolved Open decisions out.
- Write or update tests in the same change as the code.
- Keep `core/` pure and typed (mypy strict). I/O belongs in `db/`, `sources/`, `api/` and `cli.py`.
- All data SQL goes in `db/repo.py`. Maintenance SQL (PRAGMAs, migrations, `VACUUM INTO`,
  the backup API) lives in `db/connection.py` and `db/backup.py`. Use parameterized queries only.
- Connections are opened in SQLite's autocommit mode (`connection.connect` / `open_db`). Writes
  that belong together go in `connection.transaction(conn)`. Close connections with
  `contextlib.closing`. Migrations never contain `BEGIN` or `COMMIT`.
- Never call Lichess or Chess.com in tests or during development runs unless explicitly asked.
- Don't add dependencies, frameworks or a frontend build step without asking.
- Don't "improve" the product rules in §7 silently. If a rule looks wrong, flag it and
  propose a change.
- User-facing copy: short, plain, second person ("You played…"). No exclamation marks except
  the chess "??" notation.
- If something can't be verified (e.g. an API parameter), leave a `TODO(verify):` comment
  and mention it in your summary.
