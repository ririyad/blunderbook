# Blunderbook

A personal, local-first chess mistake library. It imports your games, uses Stockfish to find
your blunders, and fills in everything a machine can. What you were thinking and the lesson
are left for you to write. It then re-tests you on those positions with spaced repetition
and shows the patterns behind your mistakes.

It replaces the printed A4 "Blunder Log" diary page and keeps its spirit: minimal, focused,
and honest about what was automated and what wasn't.

- **PGN is the core format.** Lichess and Chess.com are optional adapters that only download PGN.
- **Automate the mechanical, never the reflection.** Causes are suggested and never confirmed for you.
- **Local-first and private.** One SQLite file on your machine. No accounts, no telemetry, no cloud.
- **Same engine, same rules for every source.** Every game gets its own Stockfish analysis.
- **No frontend build step.** Plain HTML, CSS and ES modules served by the backend.

The full spec is in [CLAUDE.md](CLAUDE.md). The approved UI prototype is
[docs/reference-demo.html](docs/reference-demo.html). It's a UI reference only and won't run on
its own, because its `chess.js` and `stockfish.js` files aren't in the repo.

---

## Status

_Last updated: 2026-11-05_

| Milestone | State | Notes |
|---|---|---|
| M0 Planning | Done | Roadmap, README, spec path fix |
| M1 Core | In progress (8/9) | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Not started | SQLite, migrations, dedupe, `fen` command, backup + restore |
| M3 API + Log view | Not started | FastAPI, blunder routes, web shell, Log view |
| M4 Re-test + Patterns | Not started | Scheduling, attempts, hints, both views |
| M5 Import view + jobs | Not started | Background jobs, side selection, FEN quick entry UI |
| M6 Sync | Not started | Lichess and Chess.com adapters (recorded fixtures only) |
| M7 Print + polish | Not started | A4 print page, `serve --open`, install docs |

**Next up:** M1.9 Importer + CLI.

In place so far: the scaffold (Python 3.15, tests, lint, types), shared types, time-control
parsing, config.toml, Stockfish setup, PGN reading with all nine §12 fixtures, side detection,
fingerprints, source detection, the blunder maths, engine analysis (both passes), and
suggested causes. The working commands are `blunderbook --version` and `blunderbook engine show|set|clear` (see
Usage).

---

## Roadmap

Each item is one small commit, with its tests in the same change. Every commit must pass
`uv run pytest`, `ruff check`, `ruff format --check`, and mypy (strict on `blunderbook/core`).

### M0 Planning

- [x] Review the spec and break the milestones into commit-sized slices
- [x] README with status and roadmap
- [x] Fix the reference-demo path in CLAUDE.md and add the README upkeep rule

### M1 Core: pure logic, no database

- [x] **1.1 Scaffold.** `pyproject.toml` (deps from CLAUDE.md §3 only), `.python-version` (3.15),
      `.gitignore`, `.gitattributes` (LF), package tree, ruff/mypy/pytest config, `engine` marker
      that skips when no Stockfish is found.
      _Done when_ `uv sync && uv run pytest` passes on an empty suite.
- [x] **1.2 Models + time control.** `core/models.py` (shared types, `CAUSES`, `Eval` with its JSON
      form, `TimeControl`) and `core/timecontrol.py` (parse, speed, label). Records like parsed games
      and findings arrive with the slices that fill them in.
      _Done when_ `180+2` → blitz / `"3+2"`, `1500+10` → classical / `"25+10"` (estimate 1900 s),
      and `-` / `?` / daily `1/86400` → unknown.
- [x] **1.3 Config + Stockfish path.** `config.py` (load/save config.toml with a small built-in
      writer, typed checks that name the bad key, token never shown) and Stockfish lookup:
      `--stockfish` option → `BLUNDERBOOK_STOCKFISH` → `stockfish_path` → `PATH`. A broken setting
      is reported, never skipped. Paths can be pasted with quotes, use `~` or env vars, or point at
      the unzipped folder. `core/engine.py` `probe()` checks that the program is Stockfish and reads
      its version. CLI `engine show|set|clear`.
      _Done when_ `engine set <folder>` finds the program, checks it, saves it, and `show` / `clear` work.
- [x] **1.4 PGN parsing.** `core/pgn.py`: multi-game split with `chess.pgn.read_game`, mainline only
      (variations skipped unparsed), FEN before/after each ply, `[%clk]` in seconds, each game's own
      verbatim text, plain reasons for unreadable games, and nothing logged to the console.
      `decode()` reads UTF-8, falling back to cp1252 (CLAUDE.md §7.1). `parse_date` / `parse_int`
      for headers. Read-only headers use the 3.15 `frozendict`. Text python-chess skips silently is
      caught too (see Open decisions 7). All nine §12 fixtures are in `tests/fixtures/pgn/`, each
      checked for its blunder move, side and ply.
      _Done when_ `multi_game.pgn` gives the good games plus one reported error (`Illegal move 2. Ke3`).
- [x] **1.5 Identity + source.** `core/identity.py`: `my_side()` (trimmed, case-insensitive exact
      match; `None` = needs side, also when both players match) and `fingerprint()` (site game id,
      else players, date and first 30 moves, plus the start FEN; see Open decisions 8–9).
      `core/source.py`: `detect_source()` gives the source, label, and the Lichess / Chess.com game
      id and URL (see Open decisions 10).
      _Done when_ unmatched names give `needs_side`, and lichess / chesscom / otb / pgn detection is tested.
- [x] **1.6 Detection maths.** `core/detect.py`: winning chances, swing (checked against the
      demo's numbers for every fixture blunder), judgment, flagging, accepted re-test moves
      (pure part of pass 2), and `best_line_san` (6 plies) / `refutation_san` (5 plies), which
      stop at an illegal PV move. `Thresholds` moved to `core/models.py` so core never imports
      `config`. config.toml now rejects thresholds that don't go up. See Open decisions 11.
      _Done when_ thresholds and Black-start move numbering (`5... Nxe5 6. Be2`) are tested.
- [x] **1.7 Engine analysis.** `core/engine.py`: `Engine` (a context manager; checks it's
      Stockfish and applies Threads and Hash), `analyse_game()` (pass 1 on every position, then
      MultiPV 3 on flagged ones), `terminal_line()` (finished positions never go to the
      engine), and scores turned to White's point of view. Each flagged move becomes a
      `Finding` holding everything the engine fills in for a blunder entry. `probe()` now uses
      `Engine`. Tests use a scripted analyser and the fake UCI engine, which now plays legal
      moves and can crash on demand. Two tests run against real Stockfish. See Open decisions 12.
      _Done when_ the engine always closes, even on errors.
- [x] **1.8 Suggested causes.** `core/hints.py`: `suggest()` returns the suggested causes (in
      the fixed cause order) plus the clock left and time spent, ready for `clock_left_s` /
      `time_spent_s`. Rules: time trouble, moved too fast, missed their threat, and hung a piece
      (6 plies of the refutation). The §12 fixtures give their expected hints, including
      `back_rank` "Time trouble" and `scholars_mate` "Missed their threat" (also against real
      Stockfish). See Open decisions 5 and 13.
      _Done when_ every rule is tested with a stubbed engine, including "no clocks → skip".
- [ ] **1.9 Importer + CLI.** `importer.py`, CLI `init` (asks for your names and the Stockfish path,
      Enter = PATH, checked like `engine set`), `doctor` (includes the `engine show` report) and
      `import` (prints the report and doesn't save it yet). `--stockfish` option on `import` and
      `doctor`. Engine tests for the nine §12 fixtures (the files arrived in 1.4).
      _Done when_ every fixture flags its expected move under `uv run pytest -m engine`.

### M2 Storage

- [ ] **2.1 Connection + migrations.** `db/connection.py` (WAL, foreign keys, forward-only runner),
      `0001_init.sql` from §5. `PRAGMA user_version` records the last migration. A DB made by a
      newer app is refused. _Done when_ running migrations twice is a no-op.
- [ ] **2.2 Repository.** `db/repo.py`: all SQL lives here, parameterised, returns dataclasses.
- [ ] **2.3 Persisting imports.** Importer saves games and blunders, dedupes by fingerprint,
      supports `--side`, and prints the summary line. `init` creates the DB.
      _Done when_ importing the same file twice adds nothing.
- [ ] **2.4 `fen` command.** Synthetic `source='fen'` game row. Logs the move with its judgment,
      even below the blunder line. Takes `--stockfish` too.
- [ ] **2.5 Backup + restore.** `db/backup.py` (CLAUDE.md §6 Backups), `[backup]` in config.toml,
      `backup [--to FOLDER]` and `restore FILE` commands. A daily automatic backup runs before
      `import` and `fen`, and a safety copy before migrations and restores. `init` asks for the
      folder (suggests OneDrive when it's set up), and `doctor` shows the last backup.
      _Done when_ backup → change → restore gives back the old data, a corrupt or newer-schema
      file is refused, and rotation never deletes a file you named yourself.

### M3 API + Log view

- [ ] **3.1 API.** App factory, pydantic schemas, `GET/PATCH/DELETE /api/blunders`. Detail includes
      the FEN for each ply (see Open decisions). Tested with `TestClient` and a temp DB.
- [ ] **3.2 Web shell.** `index.html`, `css/app.css` ported from the demo, hash router, `board.js`
      ported from the demo's `renderBoard`, vendored `chess.js` (version and licence recorded).
- [ ] **3.3 Log view.** Filters, list, detail board with arrows and step controls, I played /
      Best was, eval bar, metadata grid, cause chips (auto ones dashed), autosaving notes.
- [ ] **3.4 `serve`.** Binds to `127.0.0.1` only, and runs the daily backup check at start.
      _Done when_ you can browse and annotate imported blunders.

### M4 Re-test + Patterns

- [ ] **4.1 Scheduling.** `core/retest.py`: intervals `[1, 3, 7, 14, 30, 60]`, accept matching, queue order.
- [ ] **4.2 Re-test API.** Queue, attempt and hint routes.
      _Done when_ a test proves the queue never includes `best_uci`, `accept_uci`, the played move or the lesson.
- [ ] **4.3 Patterns.** `core/patterns.py` (confirmed vs suggested counts, tiles, by speed/source,
      biggest leak) and `GET /api/patterns`.
- [ ] **4.4 Views.** Re-test (tap to move, hint, "I don't know", result panel, empty state) and
      Patterns (tiles, solid/striped bars, insight line).

### M5 Import view + jobs

- [ ] **5.1 Jobs.** `jobs.py`: in-process background queue, progress as positions done / total.
- [ ] **5.2 Import API.** `/api/import/*`, `/api/fen/check`, `/api/fen/add`, `/api/settings`
      (reads and writes config.toml; the token is write-only), and `GET/PUT /api/engine` (same
      lookup and check as `engine show` / `engine set`).
- [ ] **5.3 Import view.** Paste / file picker / drag-and-drop, names field, per-game queue statuses,
      side picker, depth selector, links to found blunders. Files use the same decoding as the CLI
      (strict UTF-8 `TextDecoder`, then `windows-1252`). The "Engine: …" line in the queue header
      shows the engine name and path, with a **Change** control (enter a path, "Check and save").
- [ ] **5.4 FEN quick entry.** Board editor with tap-to-move, engine verdict, opponent and date, Add to log.

### M6 Sync (no network in tests)

- [ ] **6.1 API docs check.** Read the current official Lichess and Chess.com docs, then note the
      endpoints and parameters at the top of each adapter.
- [ ] **6.2 Lichess adapter.** `sources/base.py` + `sources/lichess.py`: streaming PGN, `since`,
      clocks and openings, optional token (never logged), backs off on 429.
- [ ] **6.3 Chess.com adapter.** Monthly archives, one request at a time, descriptive User-Agent,
      past months cached by URL/ETag.
- [ ] **6.4 Wiring.** `sync` command (runs the daily backup check), `sync_state` updates,
      `POST /api/sync/{source}`, Sync buttons.
      _Done when_ a failed sync records `last_error` and leaves existing data untouched.

### M7 Print + polish

- [ ] **7.1 Print.** `print.html` (A4, black and white, two entries per page, laid out like the paper log)
      and `print --ids / --due --out`.
- [ ] **7.2 Polish.** `serve --open`, empty states, clear error messages, check at 390 px wide.
- [ ] **7.3 Install docs.** Stockfish install steps for macOS, Windows and Linux in this README,
      ending with `blunderbook engine set <program or folder>`. A "Moving to a new computer"
      section: install, `blunderbook init`, then `blunderbook restore <latest backup>` (settings
      aren't in backups).

**Later (not v1):** opt-in LLM "coach" explanation, Anki / Lichess-study export, mobile PWA.

---

## Requirements

- **Python 3.15+**, managed with [uv](https://docs.astral.sh/uv/). `uv sync` downloads it if needed (uv 0.13.7+ knows 3.15 final).
- **Stockfish 17+**, installed by you. Then tell Blunderbook where it is:

  ```sh
  blunderbook engine set "C:\Users\you\Downloads\stockfish"   # the program, or the unzipped folder
  blunderbook engine show                                     # which Stockfish, and where that came from
  blunderbook engine clear                                    # forget it; look on PATH again
  ```

  If `stockfish` is already on `PATH`, you don't need to set anything. Without Stockfish, the
  app can't analyse games and engine tests are skipped.

Full install steps arrive in M7.

## Usage

Settings live in `config.toml` in your user config folder (on Windows,
`%LOCALAPPDATA%\blunderbook\config.toml`). Stockfish is looked up in this order:

1. `--stockfish PATH` on the command
2. the `BLUNDERBOOK_STOCKFISH` environment variable
3. `stockfish_path` in config.toml (set by `engine set`)
4. `stockfish` on `PATH`

If one of these is set but broken, you get an error saying which one. The app never quietly
uses the next one.

| Command | Does | Status |
|---|---|---|
| `blunderbook engine show\|set PATH\|clear` | Show, check and save, or clear the Stockfish path | Done (1.3) |
| `blunderbook init` | Create config (and the DB from M2), ask for your names and Stockfish | Planned (1.9 / M2) |
| `blunderbook doctor [--stockfish PATH]` | Check Stockfish, DB migrations and config | Planned (1.9) |
| `blunderbook import PATH [--side white\|black] [--depth N] [--stockfish PATH]` | Import a PGN file | Planned (1.9 report / M2 saved) |
| `blunderbook fen "FEN" --move e2e4 [--opponent X] [--date YYYY-MM-DD]` | Log a single position | Planned (M2) |
| `blunderbook serve [--port 8732] [--open]` | Start the web app on `127.0.0.1` | Planned (M3 / M7) |
| `blunderbook sync [lichess\|chesscom\|all]` | Download new games, then import them | Planned (M6) |
| `blunderbook print [--ids 1,2] [--due] --out FILE.html` | Write the A4 print page | Planned (M7) |
| `blunderbook backup [--to FOLDER]` | Take a verified snapshot of the DB now | Planned (2.5) |
| `blunderbook restore FILE [--yes]` | Bring back a backup (keeps a copy of the current DB) | Planned (2.5) |

## Development

```sh
uv sync                                   # install deps into .venv
uv run pytest                             # all tests (engine tests skip without Stockfish)
uv run pytest -m engine                   # engine tests only
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # whole package; strict on blunderbook/core
```

Engine tests (`@pytest.mark.engine`) find Stockfish the same way the app does (environment
variable, then your config.toml, read only, then `PATH`). So `blunderbook engine set PATH` once
is enough. To point the tests at a different binary for one run:

```sh
BLUNDERBOOK_STOCKFISH="C:/path/to/stockfish.exe" uv run pytest -m engine          # Git Bash
$env:BLUNDERBOOK_STOCKFISH = "C:\path\to\stockfish.exe"; uv run pytest -m engine   # PowerShell
```

Tests that only check how the engine is started and identified use a fake UCI engine
(`tests/fixtures/fake_uci.py`), so they run without Stockfish. Tests never call Lichess or
Chess.com. Sync tests use files in `tests/fixtures/http/`.

python-chess 1.11.2 uses asyncio APIs that Python 3.16 will remove. That's harmless on 3.15,
and the warnings are filtered in `pyproject.toml`. Check for a newer python-chess before
moving to 3.16.

## Open decisions

These are flagged against the spec and need your confirmation or a change.

1. **M1/M2 boundary.** §13 puts `init` and `import` in M1, but the database is M2. The plan:
   in M1, `init` writes only the config and `import` prints its report without saving. M2 adds
   the DB and persistence.
2. **HTTP cache table.** Chess.com months are cached "by URL/ETag", but §5 has no table for
   that. The proposal is a `0002_http_cache.sql` migration in M6.
3. **Positions and legal moves from the API.** §3 limits `chess.js` to the board editor and FEN
   entry. So `GET /api/blunders/{id}` would return the FEN for each ply (for step controls), and
   each re-test queue item would return `legal_uci` for tap-to-move. Legal moves don't give away
   the answer, and the server checks every attempt.
4. **Recorded HTTP fixtures.** Development never calls the sites, so the M6 fixtures will be
   built by hand from the documented formats and marked `TODO(verify)` until you record real ones.
5. **Time spent on the first move of a game that starts from a FEN (affects 1.8).** §7.7 says
   my first move's time is `base − clock + inc`. That's wrong when the game starts midway.
   `back_rank.pgn` starts at move 32 with 9 s left, which gives 180 − 9 + 2 = 173 s. Proposal:
   for games with a `FEN` header, that first move's time is unknown, so "Moved too fast" skips
   it. "Time trouble" still works, because it only needs the clock. _Built this way in 1.8
   (any game not from the standard start). Say if you want the §7.7 formula instead._
6. **Variants and null moves are rejected (done in 1.4).** Chess960, Atomic and other variants,
   unknown variants, and null moves (`--`) become problems with a plain reason, such as
   "Chess960 isn't supported, only standard chess." Stockfish can analyse Chess960
   (`UCI_Chess960`), so it could be added later if you play it.
7. **Movetext python-chess skips silently (done in 1.4; proposed addition to §7.1).** python-chess
   ignores any token that doesn't look like SAN. So a typo in a typed-up score sheet can vanish,
   or be misread: `♘f3` becomes the pawn move `f3`. Blunderbook now checks each game's mainline
   text:
   - If a token was only skipped (`Ke9`, `resigns`), the game is kept with a warning, such as
     "Skipped unreadable text 'Ke9' at 2."
   - If a token was misread, the game is rejected: "Couldn't read '♘f3' at 2."
   - If an illegal move follows skipped text, the reason names it: "Illegal move 2. Nc6
     (after unreadable text 'O-0')".
   - Symbols such as `±` are left alone.
8. **Both players match your names (done in 1.5).** §7.3 only covers "no match". If White and
   Black are both yours (two of your accounts, or a training game against yourself), the game
   also comes back as needing a side. Picking White would be a guess.
9. **Fingerprint of a game that starts from a FEN (done in 1.5; proposed addition to §7.4).**
   Without a site game id, the fingerprint is players | date | first 30 moves. Two typed-up
   positions with no names or date and the same first move (say `Ra8+`) would match, and the
   second would be skipped as "Already imported". When the game doesn't start from the standard
   position, the start FEN is added to the fingerprint. Standard games use the §7.4 formula
   exactly.
10. **Source detection details (done in 1.5; proposed wording for §7.5).**
    - "chess.com" must be a whole name. `playchess.com` (ChessBase's server) contains that text
      but is a different site, so it counts as a PGN file.
    - A Site with a dot but a capitalised ending, like `St.Louis`, counts as a place, so it's over
      the board. `playchess.com` and `www.chess24.com/en` count as websites.
    - The Lichess game id is the first 8 characters of the Site path. A 12-character player link
      is cut to 8, and `/white` or `/black` is ignored. Pages such as `/study/...`, `/broadcast/...`
      and `/analysis` give no id, so those games use the content fingerprint.
    - The Chess.com id comes from `Link`, then `Site`, and keeps the game type: `live/140512345678`
      or `daily/…`. It's marked `TODO(verify)`. I couldn't check the older `/live/game/<id>` form,
      so both forms are accepted.
    - ChessBase and some databases write `Site "INT"` or `"Internet"` for online games. The rule
      makes those "Over the board · INT". That's left as it is. Retype the header if it matters.
11. **Detection details §7.6 doesn't spell out (done in 1.6).**
    - **The move you blundered with is never an accepted re-test answer.** A deeper pass-2 look
      can rate it close to the best move. Without this rule, replaying your own blunder could
      count as solved.
    - **Mates count as ±10000 for the accept margin too**, as they do in the winning-chance
      maths. So when the best move mates, every mating move in the top 3 is accepted (mate in 4
      as well as mate in 1), and a +9 move isn't.
    - **The margin is measured from the top MultiPV line.** A move exactly
      `accept_margin_cp` away is accepted.
    - **Swing is never below 0.** If the engine likes your move better than its own choice, the
      swing is 0, matching the documented range 0..1.
    - **A position where you're already checkmated** (`mate 0`) counts as lost for whoever is to
      move. The demo scored it as 0 (level).
    - **Lines use `5... Nxe5` with a space after the dots**, as in §7.6. The demo wrote
      `5...Nxe5`.
    - **config.toml must have `inaccuracy <= mistake <= blunder`.** Otherwise loading it fails
      with an error naming the rule.
12. **Analysis details §7.6 doesn't spell out (done in 1.7).**
    - **"Best was" comes from pass 1.** That's the move that triggered the flag. Pass 2 only
      decides which re-test answers are accepted. Its top line can differ slightly, and showing
      it could make "Best was" disagree with the reason the move was flagged.
    - **Finished positions.** Checkmate, stalemate and draws that end the game by themselves
      (insufficient material, 75 moves, fivefold repetition) are scored without the engine.
      Threefold repetition and the 50-move rule only matter if someone claims them, so those
      positions still go to the engine.
    - **Each position is sent with the game's moves**, so Stockfish sees repetitions. Each game
      starts with `ucinewgame`.
    - **Progress** counts positions. The total starts at N + 1 and grows by the number of
      flagged moves once pass 1 ends.
    - **No time limit per position.** The analysis stops at a depth only, so an engine that
      hangs would hang the import. Proposal: M5's job queue gets a Cancel button, which closes
      the engine.
13. **Suggested-cause details §7.7 doesn't spell out (done in 1.8).**
    - **Clocks that don't add up give no time spent.** If previous − now + increment is
      negative (for example the opponent gave you time on Lichess), the time spent is unknown
      rather than 0. That keeps "Moved too fast" from firing on bad data.
    - **"Hung a piece" compares with the position before your move.** It plays out up to 6
      plies of the refutation, so a capture you made with the blunder counts in your favour.
      The Elephant trap (6. Nxd5??) gets no suggestion: it loses a piece for a pawn, a net 2,
      under the 3-point line. You pick the cause yourself.
    - **"Missed their threat" wins over "Hung a piece"**, as §7.7 says. The time rules can
      appear alongside either. `back_rank` gets both "Missed their threat" and "Time trouble".
    - **Both time rules need a `TimeControl` header,** as §7.7 says. Clocks with no time control
      still give "clock left", but no time causes.

### Decided

- **2026-11-04: Settings live in config.toml only.** The CLI, `/api/settings` and `/api/engine`
  all read and write it. The Lichess token is write-only (the API only says whether one is set).
  The DB `settings` table holds UI preferences only. (CLAUDE.md §5, §6, §10)
- **2026-11-04: PGN encoding.** Read as `utf-8-sig`. If that fails, read as `cp1252` with bad
  bytes replaced, and say "Read as Windows-1252" in the import report. An import never fails
  over encoding. (CLAUDE.md §7.1)
- **2026-11-04: Stockfish lookup and Python 3.15+.** See Usage and Requirements.
  (CLAUDE.md §3, §6)
- **2026-11-05: Backups (slice 2.5).**
  - **How a backup is made.** A verified `VACUUM INTO` snapshot, never a plain file copy, which
    could miss changes still in the WAL. It's written locally first, then copied into the
    backup folder and renamed, so a sync client never sees a half-written file. The last 14 are
    kept.
  - **When.** Automatically once a day before commands that change data, and always before a
    migration or a restore.
  - **Where.** By default a local `backups` folder. Point `backup.dir` at a synced folder (for
    example OneDrive) for an off-site copy. The live DB never goes there.
  - **Restore** uses SQLite's backup API, so there are no `-wal`/`-shm` files to clean up.
  - **What's not in it.** Backups don't include config.toml or the token. There's no `.dump`
    text copy.
  - (CLAUDE.md §1.3, §4, §5, §6, §9, §14)
