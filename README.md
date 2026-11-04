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
| M1 Core | Not started | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Not started | SQLite, migrations, dedupe, `fen` command |
| M3 API + Log view | Not started | FastAPI, blunder routes, web shell, Log view |
| M4 Re-test + Patterns | Not started | Scheduling, attempts, hints, both views |
| M5 Import view + jobs | Not started | Background jobs, side selection, FEN quick entry UI |
| M6 Sync | Not started | Lichess and Chess.com adapters (recorded fixtures only) |
| M7 Print + polish | Not started | A4 print page, `serve --open`, install docs |

**Next up:** M1.1 Scaffold.

There's no application code yet. None of the commands below work so far.

---

## Roadmap

Each item is one small commit, with its tests in the same change. Every commit must pass
`uv run pytest`, `ruff check`, `ruff format --check`, and mypy (strict on `blunderbook/core`).

### M0 Planning

- [x] Review the spec and break the milestones into commit-sized slices
- [x] README with status and roadmap
- [x] Fix the reference-demo path in CLAUDE.md and add the README upkeep rule

### M1 Core: pure logic, no database

- [ ] **1.1 Scaffold.** `pyproject.toml` (deps from CLAUDE.md §3 only), `.python-version` (3.12),
      `.gitignore`, package tree, ruff/mypy/pytest config, `engine` marker that skips when no
      Stockfish is found.
      _Done when_ `uv sync && uv run pytest` passes on an empty suite.
- [ ] **1.2 Models + time control.** `core/models.py`, `core/timecontrol.py` (parse, speed, label).
      _Done when_ `180+2` → blitz / `"3+2"`, `1500+10` → rapid / `"25+10"`, and `-` / `?` → none.
- [ ] **1.3 PGN parsing.** `core/pgn.py`: multi-game split with `chess.pgn.read_game`, mainline only,
      FEN before/after each ply, `[%clk]` values, per-game errors, verbatim text.
      _Done when_ `multi_game.pgn` gives the good games plus one reported error.
- [ ] **1.4 Identity + source.** `core/identity.py` (side detection, fingerprints), `core/source.py`.
      _Done when_ unmatched names give `needs_side`, and lichess / chesscom / otb / pgn detection is tested.
- [ ] **1.5 Detection maths.** `core/detect.py`: winning chances, swing, judgment, flagging,
      `best_line_san` and `refutation_san` formatting.
      _Done when_ thresholds and Black-start move numbering (`5... Nxe5 6. Be2`) are tested.
- [ ] **1.6 Engine wrapper.** `core/engine.py`: Stockfish context manager, pass 1, MultiPV 3 pass 2,
      terminal positions without the engine, scores stored from White's point of view.
      _Done when_ the engine always closes, even on errors.
- [ ] **1.7 Suggested causes.** `core/hints.py`: time trouble, moved too fast, missed their threat,
      hung a piece. _Done when_ every rule is tested with a stubbed engine, including "no clocks → skip".
- [ ] **1.8 Importer + CLI.** `config.py`, `importer.py`, CLI `init` / `doctor` / `import` (prints the
      report and doesn't save it yet), all nine §12 PGN fixtures.
      _Done when_ every fixture flags its expected move under `uv run pytest -m engine`.

### M2 Storage

- [ ] **2.1 Connection + migrations.** `db/connection.py` (WAL, foreign keys, forward-only runner),
      `0001_init.sql` from §5. _Done when_ running migrations twice is a no-op.
- [ ] **2.2 Repository.** `db/repo.py`: all SQL lives here, parameterised, returns dataclasses.
- [ ] **2.3 Persisting imports.** Importer saves games and blunders, dedupes by fingerprint,
      supports `--side`, and prints the summary line. `init` creates the DB.
      _Done when_ importing the same file twice adds nothing.
- [ ] **2.4 `fen` command.** Synthetic `source='fen'` game row. Logs the move with its judgment,
      even below the blunder line.

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
- [ ] **5.2 Import API.** `/api/import/*`, `/api/fen/check`, `/api/fen/add`, `/api/settings`.
- [ ] **5.3 Import view.** Paste / file picker / drag-and-drop, names field, per-game queue statuses,
      side picker, depth selector, links to found blunders.
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
- [ ] **7.3 Install docs.** Stockfish install steps for macOS, Windows and Linux in this README.

**Later (not v1):** opt-in LLM "coach" explanation, Anki / Lichess-study export, mobile PWA.

---

## Requirements

- **Python 3.12**, managed with [uv](https://docs.astral.sh/uv/). `uv sync` downloads 3.12 if needed.
- **Stockfish 17+**, installed by you. Put it on `PATH` or set `stockfish_path` in `config.toml`.
  Without it, the app can't analyse games and engine tests are skipped.

Full install steps arrive in M7.

## Usage (planned, not implemented yet)

| Command | Does | Lands in |
|---|---|---|
| `blunderbook init` | Create config (and the DB from M2), ask for your names, check Stockfish | M1 / M2 |
| `blunderbook doctor` | Check Stockfish, DB migrations and config | M1 |
| `blunderbook import PATH [--side white\|black] [--depth N]` | Import a PGN file | M1 (report) / M2 (saved) |
| `blunderbook fen "FEN" --move e2e4 [--opponent X] [--date YYYY-MM-DD]` | Log a single position | M2 |
| `blunderbook serve [--port 8732] [--open]` | Start the web app on `127.0.0.1` | M3 / M7 |
| `blunderbook sync [lichess\|chesscom\|all]` | Download new games, then import them | M6 |
| `blunderbook print [--ids 1,2] [--due] --out FILE.html` | Write the A4 print page | M7 |

## Development

```sh
uv sync                                   # install deps into .venv
uv run pytest                             # all tests (engine tests skip without Stockfish)
uv run pytest -m engine                   # engine tests only
uv run ruff check . && uv run ruff format --check .
uv run mypy blunderbook/core
```

Tests never call Lichess or Chess.com. Sync tests use files in `tests/fixtures/http/`.

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
