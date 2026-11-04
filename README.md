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

_Last updated: 2026-11-04_

| Milestone | State | Notes |
|---|---|---|
| M0 Planning | Done | Roadmap, README, spec path fix |
| M1 Core | In progress (3/9) | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Not started | SQLite, migrations, dedupe, `fen` command |
| M3 API + Log view | Not started | FastAPI, blunder routes, web shell, Log view |
| M4 Re-test + Patterns | Not started | Scheduling, attempts, hints, both views |
| M5 Import view + jobs | Not started | Background jobs, side selection, FEN quick entry UI |
| M6 Sync | Not started | Lichess and Chess.com adapters (recorded fixtures only) |
| M7 Print + polish | Not started | A4 print page, `serve --open`, install docs |

**Next up:** M1.4 PGN parsing.

In place so far: the scaffold (Python 3.15, tests, lint, types), shared types, time-control
parsing, config.toml, and Stockfish setup. The working commands are `blunderbook --version`
and `blunderbook engine show|set|clear` (see Usage).

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
- [ ] **1.4 PGN parsing.** `core/pgn.py`: multi-game split with `chess.pgn.read_game`, mainline only,
      FEN before/after each ply, `[%clk]` values, per-game errors, verbatim text. Files are read as
      UTF-8 with a cp1252 fallback that's noted in the report (CLAUDE.md §7.1).
      _Done when_ `multi_game.pgn` gives the good games plus one reported error.
- [ ] **1.5 Identity + source.** `core/identity.py` (side detection, fingerprints), `core/source.py`.
      _Done when_ unmatched names give `needs_side`, and lichess / chesscom / otb / pgn detection is tested.
- [ ] **1.6 Detection maths.** `core/detect.py`: winning chances, swing, judgment, flagging,
      `best_line_san` and `refutation_san` formatting.
      _Done when_ thresholds and Black-start move numbering (`5... Nxe5 6. Be2`) are tested.
- [ ] **1.7 Engine analysis.** Builds on `probe()` in `core/engine.py`: pass 1, MultiPV 3 pass 2,
      terminal positions without the engine, scores stored from White's point of view.
      _Done when_ the engine always closes, even on errors.
- [ ] **1.8 Suggested causes.** `core/hints.py`: time trouble, moved too fast, missed their threat,
      hung a piece. _Done when_ every rule is tested with a stubbed engine, including "no clocks → skip".
- [ ] **1.9 Importer + CLI.** `importer.py`, CLI `init` (asks for your names and the Stockfish path,
      Enter = PATH, checked like `engine set`), `doctor` (includes the `engine show` report) and
      `import` (prints the report and doesn't save it yet). `--stockfish` option on `import` and
      `doctor`. All nine §12 PGN fixtures.
      _Done when_ every fixture flags its expected move under `uv run pytest -m engine`.

### M2 Storage

- [ ] **2.1 Connection + migrations.** `db/connection.py` (WAL, foreign keys, forward-only runner),
      `0001_init.sql` from §5. _Done when_ running migrations twice is a no-op.
- [ ] **2.2 Repository.** `db/repo.py`: all SQL lives here, parameterised, returns dataclasses.
- [ ] **2.3 Persisting imports.** Importer saves games and blunders, dedupes by fingerprint,
      supports `--side`, and prints the summary line. `init` creates the DB.
      _Done when_ importing the same file twice adds nothing.
- [ ] **2.4 `fen` command.** Synthetic `source='fen'` game row. Logs the move with its judgment,
      even below the blunder line. Takes `--stockfish` too.

### M3 API + Log view

- [ ] **3.1 API.** App factory, pydantic schemas, `GET/PATCH/DELETE /api/blunders`. Detail includes
      the FEN for each ply (see Open decisions). Tested with `TestClient` and a temp DB.
- [ ] **3.2 Web shell.** `index.html`, `css/app.css` ported from the demo, hash router, `board.js`
      ported from the demo's `renderBoard`, vendored `chess.js` (version and licence recorded).
- [ ] **3.3 Log view.** Filters, list, detail board with arrows and step controls, I played /
      Best was, eval bar, metadata grid, cause chips (auto ones dashed), autosaving notes.
- [ ] **3.4 `serve`.** Binds to `127.0.0.1` only. _Done when_ you can browse and annotate imported blunders.

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
- [ ] **6.4 Wiring.** `sync` command, `sync_state` updates, `POST /api/sync/{source}`, Sync buttons.
      _Done when_ a failed sync records `last_error` and leaves existing data untouched.

### M7 Print + polish

- [ ] **7.1 Print.** `print.html` (A4, black and white, two entries per page, laid out like the paper log)
      and `print --ids / --due --out`.
- [ ] **7.2 Polish.** `serve --open`, empty states, clear error messages, check at 390 px wide.
- [ ] **7.3 Install docs.** Stockfish install steps for macOS, Windows and Linux in this README,
      ending with `blunderbook engine set <program or folder>`.

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

### Decided

- **2026-11-04: Settings live in config.toml only.** The CLI, `/api/settings` and `/api/engine`
  all read and write it. The Lichess token is write-only (the API only says whether one is set).
  The DB `settings` table holds UI preferences only. (CLAUDE.md §5, §6, §10)
- **2026-11-04: PGN encoding.** Read as `utf-8-sig`. If that fails, read as `cp1252` with bad
  bytes replaced, and say "Read as Windows-1252" in the import report. An import never fails
  over encoding. (CLAUDE.md §7.1)
- **2026-11-04: Stockfish lookup and Python 3.15+.** See Usage and Requirements.
  (CLAUDE.md §3, §6)
