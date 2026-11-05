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
its own, because its `chess.js` and `stockfish.js` files aren't in the repo. Its Import view
is ported in M5 without its in-browser analysis: the server analyses.

---

## Status

_Last updated: 2026-11-05_

| Milestone | State | Notes |
|---|---|---|
| M0 Planning | Done | Roadmap, README, spec path fix |
| M1 Core | Done (9/9) | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Done (5/5) | SQLite, migrations, dedupe, `fen` command, backup + restore |
| M3 API + Log view | Done (4/4) | FastAPI, blunder routes, web shell, Log view, `serve` |
| M4 Re-test + Patterns | Done (4/4) | Scheduling, attempts, hints, both views |
| M5 Web import | In progress (2/3) | Shared import code, background job with progress, Import view |
| M6 Sync | Not started | Lichess and Chess.com adapters (recorded fixtures only), CLI `sync` |
| M7 Print + polish | Not started | A4 print page, `serve --open`, install docs |

**Next up:** M5.3 Import view.

In place so far: all of M1 to M4. `blunderbook import` reads a PGN file, finds your blunders
with Stockfish (both passes), suggests causes, and saves each game and its entries to the
database. Importing the same file again adds nothing. `blunderbook fen` logs a single position
you have no PGN of. The database is backed up once a day before `import` and `fen`, and
`blunderbook backup` / `restore` work by hand. `init` creates the database and `doctor` checks
it and the backups. `blunderbook serve` opens the web page on this computer: browse your
entries, step through the game, confirm causes and write your notes. Re-test shows each due
position facing your side: tap a piece and a square, take a hint or give up, and see the
answer, your lesson and the next date. Patterns shows your causes, time controls and re-test
history. All nine §12 fixtures flag their expected blunder under `uv run pytest -m engine`.

Scope (2026-11-05): the web page is for reading your blunders, writing notes, re-testing and
patterns, and from M5 for importing too. See Decided.

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
      caught too (CLAUDE.md §7.1). All nine §12 fixtures are in `tests/fixtures/pgn/`, each
      checked for its blunder move, side and ply.
      _Done when_ `multi_game.pgn` gives the good games plus one reported error (`Illegal move 2. Ke3`).
- [x] **1.5 Identity + source.** `core/identity.py`: `my_side()` (trimmed, case-insensitive exact
      match; `None` = needs side, also when both players match) and `fingerprint()` (site game id,
      else players, date and first 30 moves, plus the start FEN; CLAUDE.md §7.3–7.4).
      `core/source.py`: `detect_source()` gives the source, label, and the Lichess / Chess.com game
      id and URL (CLAUDE.md §7.5).
      _Done when_ unmatched names give `needs_side`, and lichess / chesscom / otb / pgn detection is tested.
- [x] **1.6 Detection maths.** `core/detect.py`: winning chances, swing (checked against the
      demo's numbers for every fixture blunder), judgment, flagging, accepted re-test moves
      (pure part of pass 2), and `best_line_san` (6 plies) / `refutation_san` (5 plies), which
      stop at an illegal PV move. `Thresholds` moved to `core/models.py` so core never imports
      `config`. config.toml now rejects thresholds that don't go up (CLAUDE.md §7.6).
      _Done when_ thresholds and Black-start move numbering (`5... Nxe5 6. Be2`) are tested.
- [x] **1.7 Engine analysis.** `core/engine.py`: `Engine` (a context manager; checks it's
      Stockfish and applies Threads and Hash), `analyse_game()` (pass 1 on every position, then
      MultiPV 3 on flagged ones), `terminal_line()` (finished positions never go to the
      engine), and scores turned to White's point of view. Each flagged move becomes a
      `Finding` holding everything the engine fills in for a blunder entry. `probe()` now uses
      `Engine`. Tests use a scripted analyser and the fake UCI engine, which now plays legal
      moves and can crash on demand. Two tests run against real Stockfish (CLAUDE.md §7.6).
      _Done when_ the engine always closes, even on errors.
- [x] **1.8 Suggested causes.** `core/hints.py`: `suggest()` returns the suggested causes (in
      the fixed cause order) plus the clock left and time spent, ready for `clock_left_s` /
      `time_spent_s`. Rules: time trouble, moved too fast, missed their threat, and hung a piece
      (6 plies of the refutation). The §12 fixtures give their expected hints, including
      `back_rank` "Time trouble" and `scholars_mate` "Missed their threat" (also against real
      Stockfish). See CLAUDE.md §7.7.
      _Done when_ every rule is tested with a stubbed engine, including "no clocks → skip".
- [x] **1.9 Importer + CLI.** `importer.py`: `prepare()` queues each game as ready, needs side,
      duplicate (already known, or repeated in the same file) or error. `analyse()` adds the
      engine findings and suggested causes. `summary()` prints the §9 line. CLI commands:
      - `init` asks for your names and the Stockfish path (Enter = PATH; a bad path is asked
        again).
      - `doctor` checks config, names, Stockfish, analysis settings and the DB (not used yet),
        and exits 1 on a problem.
      - `import` prints the report: each game, its blunders with best line, refutation, swing,
        clock and suggested causes, then the summary. It saves nothing yet. It takes `--side`,
        `--depth` and `--stockfish`. `doctor` takes `--stockfish` too.

      The nine §12 fixtures run through the whole pipeline at depth 12 with one thread (about
      9 s). See CLAUDE.md §9 (exit codes) and §12.
      _Done when_ every fixture flags its expected move under `uv run pytest -m engine`.

### M2 Storage

- [x] **2.1 Connection + migrations.** `db/connection.py`:
      - `open_db()` turns on foreign keys and WAL, then runs the forward-only migrations. Each
        migration and its `user_version` bump share one transaction, so a failed one changes
        nothing.
      - It refuses a DB from a newer app, a SQLite file from another app (tables but no
        version) and a file that isn't SQLite, without touching them. It never creates a file
        unless asked.
      - `check()` is read-only: schema version and `PRAGMA integrity_check`.
      - Connections use SQLite's autocommit mode, and `transaction()` groups writes.

      `0001_init.sql` is §5 (no `settings` table), plus an index on
      `retest_attempts.blunder_id`. A test checks §5 and the migrated schema agree. `init` now
      creates the DB (moved here from 2.3), and `doctor` shows its path, schema version and
      integrity without creating or upgrading it. Tests never touch your real DB: each one gets
      its own path.
      _Done when_ running migrations twice is a no-op.
- [x] **2.2 Repository.** `db/repo.py` holds all data SQL, with every value a parameter.
      Records in `core/models.py`: `NewGame` / `NewBlunder` (what an import writes), `Game` /
      `Blunder` (plus ids, your notes, the re-test schedule, timestamps) and `Entry` (a blunder
      with its game).
      - `add_game()` saves a game and its blunders in one transaction. A known fingerprint
        writes nothing. Games with no blunders are saved too, so they're skipped next time.
        New entries are due today.
      - `list_entries()` is the Log: newest first, filtered by source, status, cause
        (confirmed, or suggested while none is confirmed) and due date.
      - `update_notes()` changes only the fields given, keeps your text exactly, and stores
        causes once each in the fixed order. `delete_blunder()` keeps the game, so the entry
        doesn't come back on the next import.
      - Also `known_fingerprints()`, `get_game()`, `get_entry()`. Re-test, sync and Patterns
        queries arrive with M4 and M5.

      _Done when_ games and entries round-trip unchanged, and the filters, notes and deletes
      are tested against a real database.
- [x] **2.3 Persisting imports.** `blunderbook import` saves what it finds:
      - It opens the database, creating it if it's missing. A database it can't use stops the
        import before Stockfish starts.
      - Games already saved are "Already imported — skipped", and Stockfish doesn't start if
        nothing is left to analyse.
      - Each game is saved, with its entries, as soon as it's analysed. If Stockfish stops,
        the games before it are kept, and importing the file again finishes the rest.
      - Games that need a side aren't saved. Run again with `--side` to save them.
      - The report shows each new entry's id (`entry #12`), and the summary says
        "N blunders added".

      `importer.new_game()` / `new_blunder()` turn an analysis into database records, and
      `importer.save()` stores them. `repo.add_game()` now also returns the new entry ids.
      Checked end to end with Stockfish 19: `back_rank.pgn` saved `32. Rc7??` as entry #1, and
      the second import skipped it.
      _Done when_ importing the same file twice adds nothing.
- [x] **2.4 `fen` command.** `blunderbook fen "FEN" --move Rc7 [--opponent X] [--date D]`
      logs one position, for games you have no PGN of. You're the side to move.
      - **Input:** the move is UCI or SAN (`e7e8` promotes to a queen). The FEN must include
        the side to move, because filling it in would be a guess. Impossible positions,
        finished games and illegal moves get a plain reason, before anything is opened.
      - **What's logged:** anything from an inaccuracy up, marked `??` / `?` / `?!`, with
        the best line, refutation and suggested causes. A move under the inaccuracy line, or
        Stockfish's own choice, isn't logged, since a re-test would have no wrong answer.
      - **Storage:** it's saved as the §5 synthetic one-move game (`[SetUp "1"] [FEN …]`,
        "FEN entry", your first name vs `--opponent`, today unless `--date`). The same
        position, move, opponent and date again says "already logged (entry #N)" without
        starting Stockfish.

      The core change is `flag_at` on `analyse_game()` / `is_flagged()`: imports flag from
      the blunder line, a FEN entry from the inaccuracy line. Checked with Stockfish 19: the
      back-rank `Rc7` and the Elephant `Nxd5` were logged as blunders, `h3` as an inaccuracy,
      and `e3` (the best move) was not logged.
- [x] **2.5 Backup + restore.** `db/backup.py` (CLAUDE.md §6 Backups), `[backup]` in config.toml,
      `backup [--to FOLDER]` and `restore FILE` commands. A daily automatic backup runs before
      `import` and `fen`, and a safety copy before migrations and restores. `init` asks for the
      folder (suggests OneDrive when it's set up), and `doctor` shows the last backup.
      _Done when_ backup → change → restore gives back the old data, a corrupt or newer-schema
      file is refused, and rotation never deletes a file you named yourself.
      - **Snapshot:** `VACUUM INTO` a temp file next to the database, `integrity_check`, copy
        to `blunderbook-YYYY-MM-DD_HHMMSSZ[-reason].db.partial` in the backup folder, rename.
        A test proves changes still in the `-wal` file are in the backup.
      - **Rotation** keeps the newest `keep` files with that exact name pattern. Other files,
        `.partial` leftovers and look-alike names are never touched.
      - **Daily:** before `import` and `fen` (and `serve` / `sync` when they arrive), when the
        newest backup's name is over 24 h old and the database has data. A failure is one
        warning; the command carries on.
      - **Before an upgrade:** `open_db(before_migrate=…)` runs when a database with data needs
        migrating. The CLI takes a `-pre-migrate` backup there, even with `auto = false`. If
        that backup fails, the upgrade doesn't happen.
      - **Restore:** checks the file (SQLite, integrity, a Blunderbook schema no newer than this
        app, not empty, not the live database), shows what the backup and your database hold,
        and asks. Then a `-pre-restore` copy, `Connection.backup` into the live file, and
        migrate. A bare file name is looked up in the backup folder.
      - **Config:** `[backup] dir / keep / auto`. `dir` takes quotes, `~` and variables; an unset
        variable (say `%OneDrive%` on a computer without it) is an error, not a stray folder.
      - **Checked by hand** with Stockfish 19 on a scratch database: import → daily backup →
        `backup` → import → `restore` of the first backup gave back 1 game · 1 entry, with a
        `-pre-restore` copy of the 3 games · 5 entries.

### M3 API + Log view

- [x] **3.1 API.** App factory, pydantic schemas, `GET/PATCH/DELETE /api/blunders`. Detail includes
      the FEN for each ply, for the step controls. Tested with `TestClient` and a temp DB.
      - **`api/app.py`:** `create_app(db_path)`. Each request opens its own connection. A
        database that can't be opened is a 503 with the reason. Only `Host: 127.0.0.1` or
        `localhost` is answered, and the `/docs` pages (CDN scripts) are off.
      - **List:** `GET /api/blunders?source=&status=&cause=&due=1`, newest first. Each item has
        your move (`6. Nxd5`), judgment, status, due date, opponent, date and `3+2` time
        control. `status` can be repeated. Unknown filter values are a 422.
      - **Entry:** `GET /api/blunders/{id}`: the machine's part, your notes, the schedule, and
        your winning chances before and after (`core/detect.chances`, so the swing is their
        difference). The game comes with its metadata and the whole mainline, each move with
        the FEN after it, read again from the stored PGN.
      - **Notes:** `PATCH` with any of `causes`, `other_cause`, `thinking`, `lesson`. A field
        that's left out or `null` stays. Text is kept exactly, and causes are kept once each in
        the fixed order. An unknown cause or any other field (say `best_uci`) is a 422, and
        nothing changes.
      - **Delete:** `DELETE` answers 204. The game stays, so it isn't imported again.
      - **Checked by hand** with Stockfish 19 and a real uvicorn server on a scratch database:
        list, entry (18 moves, chances 0.52 → 0.10), notes, cause filter and delete over HTTP.
        Another `Host` got a 400. After the delete, importing the same file again still
        skipped the game.
- [x] **3.2 Web shell.** `index.html`, `css/app.css` ported from the demo, hash router
      (`#log`, `#retest`, `#patterns`), `board.js` ported from the demo's `renderBoard`. No
      `chess.js` and no other frontend dependencies.
      - **Page:** the demo's header and its CSS, without the Import view, "+ Add games", sync
        and the demo note. The tabs are links. The Re-test badge counts entries due today or
        earlier (new ones too) and is hidden at 0. A problem reaching the API shows as one red
        line above the views. The three views are placeholders for now.
      - **`js/`:**
        - `app.js` is the router. `#log/12` gives the view `12`, and an unknown route goes to
          the Log.
        - `api.js` does fetch and JSON, and passes on the server's message.
        - `ui.js` has `esc()`, the toast and the error line.
        - `board.js` draws a FEN from either side, with highlights, red and green arrows, and
          buttons labelled "e4 white pawn" when it's interactive.
      - **Served by the app:** `web/` at `/`, after the API routes, with a Content-Security-
        Policy that allows only the page's own files, plus `no-cache` and `nosniff`. `.js` is
        always sent as `text/javascript`. The wheel includes `web/`.
      - **Tests** (`test_web.py`):
        - every file is served with its type and the headers;
        - nothing loads from another site;
        - no inline scripts;
        - every `import` names a file that exists;
        - the §11 palette is in the CSS;
        - `/api` still comes first;
        - other hosts get a 400.
      - **Checked by hand** with headless Chrome against a scratch database: the header, the
        tabs and a badge of 1. Boards from both sides with the Elephant's red and green arrows,
        and 64 labelled buttons. The shell at 390 px.
- [x] **3.3 Log view.** Filters, list, detail board with arrows and step controls, I played /
      Best was, eval bar, metadata grid, cause chips (auto ones dashed), autosaving notes. The
      empty state says "Import a PGN with `blunderbook import FILE.pgn`". No "Add games" button.
      - **List:** newest first. Each row has its mark (`??` / `?` / `?!`), status pill, source
        tag, opponent, time control and date. Filters:
        - source;
        - status ("Due for re-test" means due and re-tested before, as in the demo);
        - cause.
      - **Detail:** opens on the position before your move.
        - The board has a red arrow for your move and the best move in green (toggle).
        - The step controls go through the whole game, with labels like "After 6... Nxd5".
        - Then I played / Best was, the eval bar (your winning chances from the API), the
          details grid and the "No clock times" note.
      - **Your part:** cause chips, with suggestions dashed and tagged AUTO. Confirming
        "Other" shows a box for what it was. Then the "What I was thinking" and "Lesson"
        boxes, the re-test status, and "Delete this entry", which asks first.
      - **Saving:** text after a 400 ms pause, causes at once, one save at a time.
        - Unsaved text goes out before you switch entries, and when the page closes.
        - A failed save says so in red and tries again when you type.
        - `#log/12` opens entry 12, and picking an entry updates it.
      - **Modules:**
        - `views/log.js` is the view.
        - `format.js` holds pure helpers: evals, clocks, dates, Win / Draw / Loss.
        - `causes.js` is the fixed list, and a test checks it against `CAUSES`.
      - **Tests:** `test_web.py` checks that every field `log.js` reads exists in the API's
        schemas, that every `/api` path it calls exists, and that no HTML in the scripts uses
        `onclick=`.
      - **Checked by hand** in headless Chrome, driven over the DevTools protocol, with seven
        real Stockfish entries:
        - Lichess, PGN, OTB and a FEN-entry inaccuracy, from both sides.
        - Stepping to the end of the game, and the best-move arrow.
        - Confirming causes and "Other"; notes saved, including when you switch entries
          before the pause; still there after a reload.
        - Every filter, and delete with the badge going 7 → 6.
        - A failed save shows its message.
        - A note holding `</textarea><script>` stayed plain text.
        - No sideways scroll at 390 px.
- [x] **3.4 `serve`.** Binds to `127.0.0.1` only, and runs the daily backup check at start.
      _Done when_ you can browse and annotate imported blunders.
      - **Start-up order:**
        1. config.toml;
        2. the port, so a busy one changes nothing;
        3. the daily backup;
        4. the database: created if it's missing, or upgraded after a `-pre-migrate` backup,
           before any request comes in.
      - **The port:** `--port` (default 8732, 1–65535). On Windows it's held exclusively.
        uvicorn's own binding would let a second server share it there. A busy port says "Is
        Blunderbook already running?" and suggests the next port.
      - **Stopping:** Ctrl+C stops it cleanly with exit 0 ("Stopped."), not Click's
        "Aborted!". uvicorn and FastAPI load only for `serve`, so the other commands start as
        before. No access log.
      - **Tests** (`test_cli_serve.py`): 127.0.0.1 and the default port; bad ports; Ctrl+C; a
        busy port touching nothing; a bad config; the daily backup once a day, or off; an
        upgrade backed up first; no start without that copy. One test runs the real server in
        a thread and fetches the page, the API, and a refused other host.
      - **Checked by hand:**
        - The real `blunderbook serve` on a scratch database served the page and the API on
          127.0.0.1 and localhost.
        - A second `serve` on the same port exited 1 with the "already in use" message.
        - SIGINT, as Ctrl+C sends, printed "Stopped." with exit 0.
        - In headless Chrome, through `serve`: the Log listed 5 entries, and a lesson and a
          confirmed cause were saved.

### M4 Re-test + Patterns

- [x] **4.1 Scheduling.** `core/retest.py`: intervals `[1, 3, 7, 14, 30, 60]`, accept matching, queue order.
      `after_attempt()` gives the new status, streak and due date. `is_solved()` matches the
      from- and to-square, so `e7e8` and `e7e8q` are the same answer. `queue_key()` puts the oldest
      due date first, then the most recent game (unknown dates last, as in the Log), then move order.
- [x] **4.2 Re-test API.** Queue, attempt and hint routes. Each queue item carries its legal
      moves (`legal_uci`) for tap-to-move; the server checks every attempt.
      _Done when_ a test proves the queue never includes `best_uci`, `accept_uci`, the played move or the lesson.
      The queue is `{items, total, next_due_on}` (for the empty state), and `?all=1` gives every
      entry for "Practise all anyway". An attempt must be a legal move (a bare `e7e8` promotes to
      a queen); it's recorded in `retest_attempts` and rescheduled in one transaction, then the
      answer comes back. Shared route helpers moved to `api/common.py`.
- [x] **4.3 Patterns.** `core/patterns.py` (confirmed vs suggested counts, tiles, by speed/source,
      biggest leak) and `GET /api/patterns`.
      Causes come back in the fixed cause order (CLAUDE.md §5), not sorted by count as the demo
      does; a tied biggest leak goes to the earlier cause. The response also has the re-test
      history (re-tested entries, most recent first, with their number of tries).
- [x] **4.4 Views.** Re-test (tap to move, hint, "I don't know", result panel, empty state) and
      Patterns (tiles, solid/striped bars, insight line).
      Tap-to-move only offers the legal moves the API sent; a promotion is a queen. After you
      move, the attempt answer includes the new position (`move_fen`), so the page still has no
      chess logic. History entries link to the Log. Checked in a browser, also at 390 px.

### M5 Web import

- [x] **5.1 Shared import runner.** Move the CLI's analyse-and-save loop into
      `importer.run(...)` and its FEN outcome into `importer.log_fen(...)`, so the page and the
      CLI share them. No behaviour change: the CLI tests pass unchanged.
      `run()` takes a per-game progress context and a `should_stop()` check (between
      positions), and returns the engine's error instead of raising it. `find_logged()` checks
      a FEN entry before Stockfish runs.
- [x] **5.2 Import jobs + API.** `api/jobs.py` (one background import at a time, progress,
      stop on shutdown) and `api/routes_import.py`: `POST /api/import` (raw PGN bytes),
      `GET /api/import/{job_id}`, `POST /api/fen`. Origin and content-type checks, a 10 MB cap.
      _Done when_ importing the same bytes twice adds nothing, and stopping mid-game keeps the
      games before it.
      Imports and FEN entries share one engine slot (409 while it's taken). No Stockfish is a
      503 before anything starts. Each game row has its status (waiting, analysing, imported,
      not analysed, needs side, duplicate, error), reason and new entries. Stockfish version
      warnings and your names now come from `engine.version_note()` and `config.all_names()`,
      shared with the CLI. Checked end to end under uvicorn with the fake UCI engine.
- [ ] **5.3 Import view.** The Import tab: paste box, choose/drop a .pgn, progress bar, the
      report with links to new entries, and FEN quick entry. The Log's empty state points to it.

### M6 Sync (no network in tests)

- [ ] **6.1 API docs check.** Read the current official Lichess and Chess.com docs, then note the
      endpoints and parameters at the top of each adapter.
- [ ] **6.2 Lichess adapter.** `sources/base.py` + `sources/lichess.py`: streaming PGN, `since`,
      clocks and openings, optional token (never logged), backs off on 429.
- [ ] **6.3 Chess.com adapter.** Monthly archives, one request at a time, descriptive User-Agent.
      Only the months from the last synced month onward are downloaded; no HTTP cache.
- [ ] **6.4 Wiring.** `sync` command (CLI only; runs the daily backup check), `sync_state`
      updates, and `init` asks for the Lichess and Chess.com usernames. HTTP fixtures are
      hand-built from the documented formats and marked `TODO(verify)`.
      _Done when_ a failed sync records `last_error` and leaves existing data untouched.

### M7 Print + polish

- [ ] **7.1 Print.** `print.html` (A4, black and white, two entries per page, laid out like the paper log)
      and `print --ids / --due --out`.
- [ ] **7.2 Polish.** `serve --open`, empty states, clear error messages, check at 390 px wide.
- [ ] **7.3 Install docs.** Stockfish install steps for macOS, Windows and Linux in this README,
      ending with `blunderbook engine set <program or folder>`. A "Moving to a new computer"
      section: install, `blunderbook init`, then `blunderbook restore <latest backup>` (settings
      aren't in backups).

**Later (not v1):** a side picker for web imports, FEN board editor in the browser, settings page, opt-in LLM "coach" explanation, Anki / Lichess-study export, mobile
PWA.

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
`%LOCALAPPDATA%\blunderbook\config.toml`). Your games and notes live in one file,
`blunderbook.db`, in your user data folder (on Windows, the same folder). `blunderbook doctor`
shows both paths. Stockfish is looked up in this order:

1. `--stockfish PATH` on the command
2. the `BLUNDERBOOK_STOCKFISH` environment variable
3. `stockfish_path` in config.toml (set by `engine set`)
4. `stockfish` on `PATH`

If one of these is set but broken, you get an error saying which one. The app never quietly
uses the next one.

| Command | Does | Status |
|---|---|---|
| `blunderbook engine show\|set PATH\|clear` | Show, check and save, or clear the Stockfish path | Done (1.3) |
| `blunderbook init` | Create config and the DB, ask for your names, Stockfish and the backup folder | Done (1.9, 2.1, 2.5) |
| `blunderbook doctor [--stockfish PATH]` | Check config, Stockfish, the DB and the last backup (changes nothing) | Done (1.9, 2.1, 2.5) |
| `blunderbook import PATH [--side white\|black] [--depth N] [--stockfish PATH]` | Import a PGN file, save your blunders, and print the report | Done (1.9, 2.3) |
| `blunderbook fen "FEN" --move e2e4 [--opponent X] [--date YYYY-MM-DD] [--stockfish PATH]` | Log a single position and the move you played | Done (2.4) |
| `blunderbook serve [--port 8732]` | Start the web app on `127.0.0.1`: read your blunders, write your notes | Done (3.4); `--open` in 7.2 |
| `blunderbook sync [lichess\|chesscom\|all]` | Download new games, then import them | Planned (M6) |
| `blunderbook print [--ids 1,2] [--due] --out FILE.html` | Write the A4 print page | Planned (M7) |
| `blunderbook backup [--to FOLDER]` | Take a verified snapshot of the DB now | Done (2.5) |
| `blunderbook restore FILE [--yes]` | Bring back a backup (keeps a copy of the current DB) | Done (2.5) |

### The web page

```sh
blunderbook serve              # then open http://127.0.0.1:8732/ in your browser
blunderbook serve --port 8733  # if 8732 is taken
```

It runs on this computer only (127.0.0.1): nothing else on your network can reach it, and it
loads nothing from the internet. The Log lists your entries, newest first.
- **Pick an entry:** see the position before your move, with your move and the best move as
  arrows. Step through the whole game.
- **Your part:** confirm the causes (dashed ones are suggestions) and write what you were
  thinking and the lesson. Everything saves as you type.
- **Stop it** with Ctrl+C. Keep importing with `blunderbook import` while it runs, and reload
  the page to see the new entries.

### Backups

Backups are copies of `blunderbook.db`, named like `blunderbook-2026-11-05_081756Z.db` (UTC).
By default they go to a `backups` folder next to the database. For a copy off your computer,
use a folder your cloud drive syncs: answer `%OneDrive%\Blunderbook` when `init` asks, or set
it in config.toml:

```toml
[backup]
dir = '%OneDrive%\Blunderbook'   # empty = the local backups folder
keep = 14                         # newest backups kept
auto = true                       # once a day, before import, fen and serve
```

- **Daily:** `import`, `fen` and `serve` back up first when the newest backup is over a day
  old.
- **By hand:** `blunderbook backup`, or `blunderbook backup --to E:\USB` for a one-off copy.
- **Safety copies:** before a restore (`-pre-restore`) and before an upgrade to a newer schema
  (`-pre-migrate`). They count towards `keep` like any other backup.
- **Restore:** stop `blunderbook serve`, then `blunderbook restore FILE`. FILE can be a full
  path, or just a name from the backup folder. It shows what the backup holds and asks first.
- **What's not backed up:** config.toml (and your Lichess token). On a new computer, install,
  run `blunderbook init`, then `blunderbook restore` the newest backup.

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
moving to 3.16. Starlette's TestClient warns that it prefers `httpx2`. `httpx`, already a
dependency, still works, so that warning is filtered too.

## Open decisions

None open.

### Decided

- **2026-11-04: Settings live in config.toml only.** The CLI reads and writes it. The DB never
  stores settings. (On 2026-11-05 the settings and engine API routes and the DB `settings` table
  were dropped from v1.) (CLAUDE.md §5, §6)
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
  - **Settled while building it:**
    - The daily check skips a database with no rows, so a fresh database doesn't use a slot.
    - If the `-pre-migrate` copy fails, the database isn't upgraded.
    - The `-pre-restore` copy doesn't rotate, so a restore never deletes the file it reads.
      The next backup rotates.
    - Two backups in the same second: the second takes the next second's name.
    - A relative `backup.dir` is relative to the config folder, like `stockfish_path`. An unset
      variable in it is an error.
    - `doctor` warns (old backup, missing folder) without failing. Only problems exit 1.
    - `init` won't use the database's own folder for backups.
- **2026-11-05: The Log's API (slice 3.1).**
  - The server works out your winning chances for the eval bar, so the maths lives in one
    place.
  - The step controls get the whole game, not only the moves up to the blunder.
  - The Log's entry doesn't include the accepted re-test moves.
  - PATCH leaves out-or-`null` fields alone, and `other_cause: ""` clears it.
  - The API answers only `Host: 127.0.0.1` / `localhost` (no login, so this stops DNS
    rebinding). `/docs` is off because it loads scripts from a CDN.
  - The demo's "Re-tested N×" count arrives with the re-test attempts in M4.
  - (CLAUDE.md §10)
- **2026-11-05: The page shell (slice 3.2).**
  - The brand reads "Blunderbook".
  - The tabs are links (`aria-current`), not `role="tab"` buttons: they change the address.
  - The badge is hidden at 0 rather than showing a red 0.
  - A strict Content-Security-Policy: the page only runs its own script files, so text in a
    PGN or a note can't run as code. Views never use inline scripts or `onclick=`.
  - `.js` is always sent as `text/javascript`, whatever the Windows registry says.
  - (CLAUDE.md §4, §11)
- **2026-11-05: The Log view (slice 3.3).** Where it differs from the demo:
  - The step controls go through the whole game, not only up to your move. Positions are
    labelled "After 4. Bg5" rather than "Move 7 of the game".
  - Each entry shows its own mark (`??`, `?`, `?!`), since FEN entries can be mistakes or
    inaccuracies.
  - "Delete this entry", which asks first: the API has it, and the page is the only place to
    use it.
  - A text box for "Other" (`other_cause`).
  - Dates show the year when it isn't this year.
  - "Re-test this one now" and "Re-tested N×" come with M4.
  - (CLAUDE.md §11, §12)
- **2026-11-05: `serve` (slice 3.4).**
  - The port is taken before anything else, so a busy port changes nothing.
  - On Windows the port is held exclusively.
  - A missing database is created at start, so the page shows the empty state, not an
    error.
  - Ctrl+C exits 0.
  - No access log.
  - `--open` stays in 7.2 (6.2 before web import became M5).
  - (CLAUDE.md §9)
  - (CLAUDE.md §1.3, §4, §5, §6, §9, §14)
- **2026-11-05: Keep it simple.** The goal is to find your blunders after a game and not
  repeat them in the next one. Import stays on the CLI. The web page is for the Log (notes),
  Re-test and Patterns. Dropped from v1: the web Import view and its background jobs, the
  browser FEN board editor, the settings and engine pages, web Sync buttons, `chess.js`, the DB
  `settings` table and the Chess.com HTTP cache. (CLAUDE.md §3, §4, §5, §6, §8, §10, §11, §13)
  The web Import view came back the same day, below.
- **2026-11-05: Web import in v1 (M5).** You want to paste a game straight from a site's
  Share → PGN panel. The Import tab takes pasted text, a chosen or dropped .pgn, or a FEN and
  your move. It runs the CLI's own import code in one background job at a time, with a
  progress bar. Games with no name match are listed with what to do; a side picker stays for
  later. It comes after M4, so Sync is now M6 and Print + polish M7. (CLAUDE.md §4, §9, §10,
  §11, §13)
- **2026-11-05: The 14 former open decisions.** Each built choice stays as built; each proposal
  that added machinery was dropped. The rules are now in CLAUDE.md.
  1. **M1/M2 boundary:** M1 prints the import report, M2 saves it.
  2. **Chess.com cache:** none. Sync downloads only the months from the last synced month on. (§8)
  3. **Positions from the API:** the blunder detail sends each ply's FEN, and each re-test item
     sends its legal moves. No `chess.js`. (§10)
  4. **HTTP fixtures:** hand-built from the documented formats, marked `TODO(verify)`. (§8)
  5. **First move of a game from a FEN:** its time spent is unknown. (§7.7)
  6. **Variants and null moves:** rejected with a plain reason. (§7.1)
  7. **Unreadable movetext:** skipped text gives a warning, misread text rejects the game. (§7.1)
  8. **Both players match your names:** needs side. (§7.3)
  9. **Fingerprint of a FEN-start game:** the start FEN is added. (§7.4)
  10. **Source detection:** whole-name "chess.com", place vs website, Lichess and Chess.com ids. (§7.5)
  11. **Detection:** your blunder is never accepted, mates count ±10000 in the margin, swing is at
      least 0, `mate 0` is lost, thresholds must go up. (§7.6)
  12. **Analysis:** "Best was" comes from pass 1; finished positions skip the engine. No Cancel
      button: there's no job queue, and Ctrl+C closes the engine. (§7.6)
  13. **Suggested causes:** a negative time spent is unknown; "Hung a piece" compares with the
      position before your move. (§7.7)
  14. **Import:** duplicates within one file, `--side` never overrides a name match, exit codes,
      engine tests at depth 12. (§7.3, §7.4, §9, §12)
