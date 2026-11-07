# Blunderbook: roadmap and decisions

How v1 was built, one slice at a time, and the decisions made along the way. For using
Blunderbook, see the [README](../README.md). The spec is [CLAUDE.md](../CLAUDE.md).

## Status

_Last updated: 2026-11-07_

| Milestone | State | Notes |
|---|---|---|
| M0 Planning | Done | Roadmap, README, spec path fix |
| M1 Core | Done (9/9) | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Done (5/5) | SQLite, migrations, dedupe, `fen` command, backup + restore |
| M3 API + Log view | Done (4/4) | FastAPI, blunder routes, web shell, Log view, `serve` |
| M4 Re-test + Patterns | Done (4/4) | Scheduling, attempts, hints, both views |
| M5 Web import | Done (3/3) | Shared import code, background job with progress, Import view |
| M6 Sync | Done (4/4) | Lichess and Chess.com adapters (recorded fixtures only), CLI `sync` |
| M7 Print + polish | Done (3/3) | A4 print page, `serve --open`, install docs |
| M8 AI explanations | Done (4/4) | Optional "Explain this blunder" via OpenRouter, your own key |
| M9 Extensions | Done (4/4) | Separate packages that add a tab, routes, commands and their own database |
| M10 Your games | In progress (2/3) | A Games tab: every game you imported, by import, with a game page |
| M11 Library | Not started | Extension: openings, traps and tactics to study and practise |
| M12 Collection | Not started | Extension: a collection of anyone's games, analysed |

**Next up:** 10.3, the Games tab: by import or by date, filters, the game page, and links from the Log and Import. Still to check
from M8: one real explanation with your key, and the Log and Re-test at 390 px wide. Before relying
on sync, try one real `blunderbook sync` and record the responses (the fixtures are still
hand-built, `TODO(verify)`).

In place: all of M1 to M9. `blunderbook import` reads a PGN file, finds your blunders
with Stockfish (both passes), suggests causes, and saves each game and its entries to the
database. Importing the same file again adds nothing. `blunderbook fen` logs a single position
you have no PGN of. The database is backed up once a day before `import` and `fen`, and
`blunderbook backup` / `restore` work by hand. `init` creates the database and `doctor` checks
it and the backups. `blunderbook serve` opens the web page on this computer: browse your
entries, step through the game, confirm causes and write your notes. Re-test shows each due
position facing your side: tap a piece and a square, take a hint or give up, and see the
answer, your lesson and the next date. Patterns shows your causes, time controls and re-test
history. All nine §12 fixtures flag their expected blunder under `uv run pytest -m engine`.
The Import tab imports a pasted or dropped PGN, or one FEN position, on the page.
`blunderbook sync` downloads your new Lichess and Chess.com games and imports them (tested
against hand-built responses only; no real download has been checked yet).
`blunderbook print` writes the A4 Blunder Log page, and `serve --open` opens the page for you.
"Explain this blunder" asks OpenRouter, with your own key, to put Stockfish's lines into words
(off until you turn it on). Extensions can be installed and turned on: each adds its own tab,
routes, commands and database, is backed up with yours, and can read your Log but never change
it. None ships yet: Library (M11) and Collection (M12) are the first.

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
- [x] **5.3 Import view.** The Import tab: paste box, choose/drop a .pgn, progress bar, the
      report with links to new entries, and FEN quick entry. The Log's empty state points to it.
      _Done:_ `views/import.js` sends the pasted text or the file's raw bytes as
      `application/x-chess-pgn` (so a cp1252 file is read by the server), checks the job every
      500 ms, and shows the summary once the job ends (the new entries come at the end). A reload
      picks the last job up again. The Re-test and Patterns empty states point to the tab too.
      Checked in a browser with the fake UCI engine, including at 390 px wide.

### M6 Sync (no network in tests)

- [x] **6.1 API docs check.** Read the current official Lichess and Chess.com docs, then note the
      endpoints and parameters at the top of each adapter.
      _Done:_ checked 2026-11-05 (the Lichess OpenAPI spec, Chess.com's Published-Data API page).
      Notes at the top of `sources/lichess.py` and `sources/chesscom.py`. Still `TODO(verify)`:
      whether Lichess `since` compares with a game's start or end, whether Chess.com usernames
      are case-sensitive in URLs, and the Link and clock headers in a real Chess.com download.
- [x] **6.2 Lichess adapter.** `sources/base.py` + `sources/lichess.py`: streaming PGN, `since`,
      clocks and openings, optional token (never logged), backs off on 429.
      _Done:_ `LichessAdapter.fetch_new_pgn(since)` hands over one game at a time while the
      download streams (`base.games_in` only cuts the text; `core.pgn` still parses it).
      - **Request:** oldest first (`sort=dateAsc`), so a sync that stops halfway keeps its
        progress. Standard chess only (`perfType`), `since` in milliseconds (a time with no
        zone is UTC), and the defaults sent explicitly.
      - **Token:** only in the `Authorization` header. It's not in the adapter's `repr`, and
        it's replaced with `[token]` in error messages.
      - **429:** waits 60 s (or a longer `Retry-After`) and tries again, three tries in all. A
        `Retry-After` over 5 minutes stops the sync instead of hanging it.
      - **Errors** are a `SyncError` with a plain message: unknown user, refused token, another
        status, or the network. Games handed over before a broken stream stay handed over.
      - **Tests** use `tests/fixtures/http/lichess_user_games.pgn` (hand-built,
        `TODO(verify)`) through httpx `MockTransport`. A new autouse guard in `conftest.py`
        makes any real request to a host other than this computer fail the test.
- [x] **6.3 Chess.com adapter.** Monthly archives, one request at a time, descriptive User-Agent.
      Only the months from the last synced month onward are downloaded; no HTTP cache.
      _Done:_ `ChesscomAdapter(username, contact).fetch_new_pgn(since)` reads the archive list,
      then each month's `/pgn` from the month of `since` (in UTC) onward, oldest first, one
      game per item.
      - **Requests:** one at a time, each answered before the next. The User-Agent is
        `Blunderbook/<version> (local chess mistake library; contact: <contact>)`. The sync
        needs `[chesscom] contact`; it's never filled in for you. Usernames go in lowercased
        (`TODO(verify)`).
      - **Answers:** redirects are followed, and a 410 month is skipped. A 429 waits 60 s (or a
        longer `Retry-After`), up to three tries, as for Lichess; that rule now lives in
        `sources/base.py`. A month's bytes are decoded like a PGN file (UTF-8, else cp1252).
      - **Errors** are a `SyncError`: unknown player, an archive list it can't read, another
        status (naming the URL path), the network. Games handed over before a failed month
        stay handed over.
      - **Tests** use three hand-built fixtures in `tests/fixtures/http/` (`TODO(verify)`),
        including a daily game. Also fixed a test that only passed on 2026-11-05: the re-test
        queue fixture now makes its entries due on the day the test runs.
- [x] **6.4 Wiring.** `sync` command (CLI only; runs the daily backup check), `sync_state`
      updates, and `init` asks for the Lichess and Chess.com usernames. HTTP fixtures are
      hand-built from the documented formats and marked `TODO(verify)`.
      _Done when_ a failed sync records `last_error` and leaves existing data untouched.
      - **`blunderbook sync [lichess|chesscom|all]`:** `all` (the default) is each site with a
        username in config.toml. Then the daily backup, then the database, then each site in
        turn: download, then import through the same code as `import` (`cli._analyse`). Games
        you already have are counted in the summary but not listed. Exit 1 when a site fails.
      - **How far it got:** `sync_state.last_synced` is when the newest game downloaded was
        played (`core.source.game_time`: Chess.com's `EndDate`/`EndTime`, else
        `UTCDate`/`UTCTime`). It only moves on after a run that worked, and never back. The
        next run asks for games from then on. Another username starts again from the
        beginning.
      - **A failed run** records `last_error` and prints it, and `last_synced` stays. A failed
        download imports nothing from that site. If analysis stops, the games saved so far
        stay, and the next run downloads the rest again. The other site still syncs. The
        token never appears in the output or the database.
      - **`init`** asks for the Lichess and Chess.com usernames (Enter skips), and for the
        Chess.com contact when you give a Chess.com username. The token stays in config.toml.
      - **`repo.get_sync_state` / `record_sync`**, `sources.adapter_for`, and a `SyncState`
        record. Tests (`test_cli_sync.py`) run the real adapters on `MockTransport` clients.

### M7 Print + polish

- [x] **7.1 Print.** `print.html` (A4, black and white, two entries per page, laid out like the paper log)
      and `print --ids / --due --out`.
      _Done:_ `blunderbook print --out FILE.html [--ids 3,12 | --due]` writes one HTML file that
      works on its own: `printing.render()` fills `web/print.html` and inlines
      `web/css/print.css`. Open it and print from the browser.
      - **Each entry** (half a page): the move and its mark, entry number, players, ratings and
        date; the board before your move from your side, with your move as an arrow (SVG from
        python-chess, greys only); I played with the refutation, Best was with the line;
        source, time control, result, opening, eval and your chances, clock and time on move
        (`—` when unknown); the twelve causes ticked, with suggestions marked "(suggested)"
        until you confirm any; What I was thinking and Lesson (ruled lines when empty, cut
        with "…" past 700 characters); "Re-tested on ___ ☐ Solved ☐ Missed again" and the
        current schedule.
      - **Which entries:** all of them in the Log's order, `--ids` in the order given, or
        `--due`. An unknown id, `--ids` with `--due`, no database or no entries writes nothing
        and exits 1. Printing never creates or changes the database; the file is written
        through a `.partial` and renamed.
      - **Checked by hand** in a browser on a sample of three entries: two per sheet, the
        board, causes, notes and the re-test line.
- [x] **7.2 Polish.** `serve --open`, empty states, clear error messages, check at 390 px wide.
      _Done:_
      - **`serve --open`** opens the page in your browser once the port is taken. The port
        already listens, so the browser's first request waits for the server. No browser
        found: it says so and keeps serving.
      - **A Stockfish that macOS blocked.** A download from the internet carries macOS's
        quarantine mark, and Gatekeeper stops the unsigned Stockfish release: a dialog
        appears and the program never answers. When a program fails to start and has that
        mark (read with `/usr/bin/xattr`), `init`, `engine set`, `doctor`, `import`, `fen`,
        `sync` and the web import say so and show three fixes: `brew install stockfish`
        then `blunderbook engine clear`, `xattr -d com.apple.quarantine PATH`, or Open
        Anyway in System Settings > Privacy & Security.
      - **Checked in a browser at 390 px** with a scratch database, empty and with entries:
        Log list and detail, Re-test, Patterns and Import. Nothing scrolls sideways. Every
        view already had its empty state. With the server stopped, each view says "Can't
        reach Blunderbook. Is blunderbook serve still running?"
- [x] **7.3 Install docs.** Stockfish install steps for macOS, Windows and Linux in this README,
      ending with `blunderbook engine set <program or folder>`. A "Moving to a new computer"
      section: install, `blunderbook init`, then `blunderbook restore <latest backup>` (settings
      aren't in backups).
      _Done:_ the Install section: Blunderbook with `uv tool install .` (checked into a scratch
      folder: the command, the web files and the migrations are all installed), Stockfish per
      system (Homebrew or the official archive and the Gatekeeper fix on macOS, the zip or winget
      on Windows, the archive or the distribution's package on Linux), then `init` and `doctor`,
      and Moving to a new computer. The download page was checked on 2026-11-06 (Stockfish 19,
      universal builds). The winget package isn't checked on Windows yet (`TODO(verify)`).

### M8 AI explanations (optional, off by default)

An "Explain this blunder" button that turns what Blunderbook already knows (the position,
Stockfish's lines, board facts from python-chess) into 3–4 plain sentences, through OpenRouter
with your own key and a model you choose. The model only explains the facts it's given; it
never writes your thinking or lesson and never confirms a cause.

- [x] **8.1 Config + CLI.** `[ai]` in config.toml (`enabled`, `model`, `key`), and
      `blunderbook ai show | set-key | model NAME | on | off`.
      _Done:_
      - **The key** is handled like the Lichess token: not in `repr`, never printed (`ai show`
        and `doctor` only say "set"), typed hidden by `ai set-key` so it isn't in your shell
        history. Empty input removes it.
      - **No default model:** you pick one. `ai model` saves it without a network check.
      - **`ai on`** refuses while the key or model is missing; `ai off` keeps both.
        `config.ai_problem()` gives the plain reason, for the CLI now and the API in 8.3.
      - **`doctor`** shows an AI row: off, or on with the model. On with no key or model is a
        problem. It never calls OpenRouter.
      - CLAUDE.md principle #3, §3, §6 and §9 now name the AI explanation as the one other place
        that makes a network call, only when you press its button.
- [x] **8.2 Facts + prompt.** `core/explain.py` (pure): the facts sent (refutation played out
      with each capture, pieces left hanging, mate threats, the best move, evals in words,
      clock) and the prompt. Never player names, ratings or your notes.
      _Done:_
      - **`Mistake`** holds only what may be sent; `explain.mistake(entry)` copies it out of
        an entry. A test fills every private field (names, ratings, site, notes, confirmed
        causes) with marker text and checks none of it reaches the prompt.
      - **`facts()`** plays out the stored lines with python-chess (`read_line` skips move
        numbers and stops at the first bad token): each capture with whose piece it was,
        checkmate or stalemate at the end, material against before your move. After your
        move it lists your pieces left attacked, and a forced mate against you.
      - **`build_prompt()`** gives the system and user messages. The user message is plain
        text, readable as it is, so the page can show it under "What's sent".
      - Checked on the §12 blunders with their known refutations: the Elephant (two captures
        and a queen trade, 2 points down mid-exchange), Scholar's mate and the back rank
        (mate in 1), and Légal's trap (a queen won, then mated).
      - CLAUDE.md §7.10 holds the rules.
- [x] **8.3 Client, storage, API.** `ai.py` (OpenRouter, checked against its docs), migration
      `0002_explanations.sql`, `GET /api/ai`, `GET|POST /api/blunders/{id}/explanation[/prompt]`.
      _Done:_
      - **OpenRouter docs checked 2026-11-07** and noted at the top of `ai.py`:
        `max_completion_tokens` (`max_tokens` is deprecated), `provider.data_collection =
        "deny"` so only providers that don't collect your data answer, no leaderboard
        headers, and errors that can arrive inside an HTTP 200. Each error gets a plain
        message with the key redacted. No automatic retry.
      - **Storage:** `0002_explanations.sql`, one row per entry, deleted with it. A v1
        database gets the `-pre-migrate` backup before it's upgraded (tested).
        `repo.get_explanation` / `save_explanation` (replaces the one before).
      - **API:** `GET /api/ai`, the "What's sent" prompt, and the POST that asks and saves.
        The entry detail and the Re-test attempt answer carry the explanation; the queue
        doesn't. `same_origin` moved to `api/common.py` for both POSTs.
      - Tests use hand-built OpenRouter responses (`tests/fixtures/http/openrouter_*.json`,
        `TODO(verify)`) on `MockTransport`. The "newer app" upgrade tests now add a made-up
        migration after the latest, via `conftest.with_next_migration`.
- [x] **8.4 Page.** The explanation block in the Log and on the Re-test result (after an
      attempt only), "What's sent", README.
      _Done:_
      - **`js/explain.js`**, shared by both views. It reads `/api/ai` each time, so `ai on` /
        `ai off` show at once. A saved explanation is an amber dashed box like a suggested
        cause, marked "auto", with the model and date and "It can be wrong". "Explain this
        blunder" (or mistake / inaccuracy) asks; "Explain again" replaces it. "What's sent"
        loads the exact prompt when opened.
      - **Log:** under I played / Best was. **Re-test:** on the result, after the attempt.
        The queue item has no explanation, and `test_web.py` checks the view only reads it
        from the attempt's answer.
      - **Checked in a browser** on a scratch config and database, with AI on and off and no
        call to OpenRouter: the saved text and its label, "What's sent" (no names or notes in
        it), the button on an entry with nothing saved, the Re-test result before and after an
        attempt, and with AI off the saved text without a button and nothing on the others.
        No console errors. Not checked at 390 px wide: the browser window couldn't be
        resized (`TODO(verify)`).
      - README: the AI explanations section (setup, what's sent and what isn't, who sees it,
        cost), the commands, settings, privacy and a troubleshooting line.

### M9 Extensions

Extensions are separate packages in `extensions/` (a uv workspace), found through the
`blunderbook.extensions` entry-point group when they're installed and turned on. Core never
imports one. Each may bring routes, a tab, commands and its own database, and may read your
Log but never change it. Turned on with `blunderbook ext enable NAME`, then a restart of
`serve`.

- [x] **9.1 Contract + discovery.** `blunderbook/ext.py`: `Extension`, `HOST_API`, `load()`,
      `[extensions] enabled` in config.toml, `ext list | enable | disable`, doctor.
      _Done:_
      - **`Extension`** names a slug, a tab title, the host API it was written for, and
        optionally a router, web folder, migrations and Typer commands. `HOST_API = 1`.
      - **`ext.load()`** never raises. An extension that's on but not installed, fails to
        import, isn't an `Extension`, has a name that doesn't match its entry point, uses a
        name Blunderbook needs (`log`, `import`, `ai`, …) or was made for another host API is
        left out with one plain reason; the others still load.
      - **`ext enable`** loads and checks the extension first, and changes nothing if it
        can't be used. `ext disable` keeps its data. `ext list` shows what's installed and on.
      - **Commands:** the program now starts through `cli.run()`, which adds
        `blunderbook NAME ...` for each extension that's on and has commands.
      - **`doctor`** lists the extensions that are on; a missing or broken one is a problem.
      - Tests load sample extensions (`tests/ext_samples.py`) through hand-made entry points.
      - Checked: uv 0.13.7 has `uv tool install --with <requirement>` (a local path works as
        a requirement) and `uv sync --all-packages`. The workspace itself arrives with the
        first extension package (11.1).
- [x] **9.2 Own databases.** `open_db(migrations=…)`, backups with a per-extension prefix,
      the daily backup, `-pre-migrate` and `restore` for extension databases.
      _Done:_
      - **`connection.Store`** names a database and its migrations. `CORE` is Blunderbook's
        own and the default everywhere, so core behaviour and messages are unchanged.
      - **`ext.open_db(extension, cfg)`** opens `<name>.db` next to the DB, creating and
        migrating it, with a `-pre-migrate` backup first when it has data; if that backup
        fails it isn't upgraded. A newer database names the extension.
      - **Backups** start with the database's name (`notes-…db`). Rotation, `keep` and the
        daily check count each name separately. `backup` and the daily backup cover every
        extension that's on and has a database (`ext.databases`, `ext.daily_backups`, shared
        by the CLI and the web import job); a failed one is a warning, as before.
      - **`restore`** picks the database from the file name, refuses a backup of an extension
        that's off, and compares the file's tables with the ones that database's migrations
        make, so a renamed file can't put one database's backup in place of another's.
      - Tests: `tests/test_ext_db.py`, with a sample `notes` extension that has a migration.
- [x] **9.3 Page + host API.** `GET /api/extensions`, `/ext/<name>/` files, a tab per
      extension loaded with `import()`, `ext_db` / `log_reader` (read-only) dependencies,
      `host.settings()` / `host.engine()`, page checks extensions can reuse.
      _Done:_
      - **The app:** `create_app(db, extensions)` mounts each one's router at
        `/api/ext/<name>` and its page folder at `/ext/<name>/`, with the page's own headers
        (CSP, `no-cache`, `.js` as `text/javascript`). `GET /api/extensions` lists those with
        a page.
      - **`serve`** loads the extensions that are on and opens their databases before the first
        request (with the `-pre-migrate` backup). One that can't be loaded, or whose database
        can't be used, is a warning; the app runs without it.
      - **Loading** also checks the files: a page folder on disk with a `view.js`, and a
        migrations folder that exists.
      - **The shell** adds a tab per extension before the first route, so `#notes/abc` works
        from a bookmark; its `view.js` loads on first visit.
      - **`blunderbook/host.py`**, the host API: `ExtDb` (its own database per request), `Log`
        (your Log through a `mode=ro` connection: a write fails in SQLite), `same_origin`,
        `settings()` (names, thresholds, engine settings; never a token or key), `engine()`,
        and `read_log()` / `open_db()` for commands.
      - **`blunderbook/webcheck.py`**: page checks (imports resolve, `/api` calls are routes, no
        inline scripts or handlers, nothing from elsewhere, `view.js` exports `show`), run on
        Blunderbook's own page and the sample's.
      - Checked in Chrome with the sample extension: the tab, a deep link, its styles, tab
        switching, an unknown route, no console or CSP errors. HTML in its data stays text.
      - Also removed dead code 9.2 left in `api/jobs.py`.
- [x] **9.4 End to end.** A test-only extension that uses all of it; CLAUDE.md §15.
      _Done:_
      - **`tests/fixtures/ext_demo`**: a demo package with routes, a page (with a module of
        its own), commands and a database, using only the host API. A `.dist-info` folder
        makes `importlib.metadata` find it for real when the folder is on `sys.path`.
      - **`tests/test_ext_e2e.py`** goes from `ext list` and `ext enable` through its
        command, `serve`, its routes, page files and checks, `backup` and `restore` of its
        database, to `ext disable`, with your Log read and never changed.
      - **`ext.boundary_problems(package)`** lists an extension's imports from Blunderbook
        outside the host API. A test checks core never imports an extension.
      - **CLAUDE.md §15** writes the contract down: what an extension declares, what it may
        use, and the rules it follows. Also §4, §12 and §13 (M9 to M12).

### M10 Your games

The Log lists blunders. A Games tab lists the games themselves, clean ones too: grouped by the
import they came from (a file, a paste, a sync) or by date, with filters, and a game page
that steps through the whole game with your blunders marked. No delete in this milestone.

- [x] **10.1 Storage: remember each import.** Migration 0003, `importer.run(batch=)`, the
      import's name from the CLI, sync and the page, `repo.list_games`.
      _Done:_
      - **0003_imports.sql**: an `imports` table (label, kind `file`/`paste`/`sync`, when) and
        `games.import_id`. Games saved before it keep NULL; the upgrade takes the usual
        `-pre-migrate` backup.
      - **`importer.run(..., batch=)`** remembers the import when its first game is saved, so
        one that adds nothing (all duplicates) leaves no empty group. FEN entries have none.
      - **Names:** `blunderbook import FILE` uses the file's name, `sync` "Lichess sync" /
        "Chess.com sync", and the page sends the chosen file's name in `X-Pgn-Name`
        (percent-encoded); pasted text is "Pasted PGN". Folders, control characters and
        anything past 200 characters are dropped (`importer.file_batch`).
      - **`repo.list_games`**: newest first (a game with no date by the day it was imported),
        each with its import and its entries by judgment; filters for source, result from
        your side, speed, clean or not, and a search of the opponent, opening and ECO that
        ignores case beyond ASCII. FEN entries aren't games, so they're left out.
        `repo.get_game_row` and `list_entries(game_id=)` for the game page.
- [x] **10.2 API.** `GET /api/games` (filters, each game with its import) and
      `GET /api/games/{id}` (the game, its moves with FENs, its entries).
      _Done:_
      - **`GET /api/games`**: each game with your side, the opponent and their rating, the
        result and its outcome from your side, the date played and the import time, the
        time control, the opening, its import (`batch`, or null for older games) and its
        entries by judgment. Filters: `source`, `result=won|lost|drawn`, `speed`,
        `blunders=with|clean`, `q` (opponent, opening, ECO; at most 100 characters). A bad
        value is a 422.
      - **`GET /api/games/{id}`**: the game with its whole mainline (each move with the FEN
        after it), its outcome, import and entries in move order. A FEN entry's game, or
        none, is a 404 "No game #N.".
      - The entry detail and the game page build the game the same way: `moves()` and
        `game_out()` moved from `routes_blunders.py` to `api/common.py` (a test checks both
        give the same game).
- [ ] **10.3 The Games view.** The tab, By import / By date, filters, the game page, links
      from the Log detail and the Import report, 390 px.

### M11 Library (extension)

- [ ] **11.1** Package, content format (one TOML per entry), validator, ~15 starter entries.
- [ ] **11.2** API, index and entry views (board through the mainline and each consequence).
- [ ] **11.3** Practise: quiz positions with spaced repetition, progress in `library.db`.
- [ ] **11.4** "Your entries in this opening", read from your Log.

### M12 Collection (extension)

- [ ] **12.1** Package, `collection.db`, import into collections, `engine.score_positions()`
      (pass 1).
- [ ] **12.2** Stats: accuracy, ACPL, judgments, phases, repertoire, per player or any filter.
- [ ] **12.3** API, collection / game / player views with filters and an eval graph.
- [ ] **12.4** Import on the page, and links to your Log.

**Later (not v1):** a side picker for web imports, FEN board editor in the browser, settings
page, more AI helpers (reflection questions, cause suggestions from your notes, a monthly
digest), Anki / Lichess-study export, mobile PWA.

---

## Development notes

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
- **2026-11-04: Stockfish lookup and Python 3.15+.** See Install and Usage.
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
- **2026-11-06: A clearer board.** The Unicode pieces looked dim and changed with each
  system's font, and the grey-brown squares blended with them. The board now draws
  python-chess's SVG pieces (the print page's set; the server makes them at `/pieces/wK.svg`,
  so no image files are copied in) on cream and blue squares (`#ebe9d8` / `#4c688d`). The move
  highlights are a little stronger so they show on blue. (CLAUDE.md §11)
- **2026-11-06: A polish pass on the page.** Same colours and design rules (CLAUDE.md §11),
  one consistent set of buttons, fields, dropdowns and chips, and hairline panels. The header,
  the Log list and the Log board stay in view while you scroll, so you can see the position
  while you write. List entries have the same three lines (move, opponent, time control and
  date), and the list shows how many entries match. The game's details are one hairline
  table, the eval row puts your winning chances first, and the entry ends with its re-test
  status and Delete. Re-test shows how far through the session you are. Checked by hand at
  1300 px and 390 px.
- **2026-11-06: The README is a user guide.** It now explains what Blunderbook is (and the
  paper Blunder Log it replaces), how to install and use it, with real example output, how
  blunders are judged, the settings and the commands. The status, roadmap and decisions moved
  here, to `docs/ROADMAP.md`. Screenshots are in `docs/images/`. (CLAUDE.md §4, §14)
- **2026-11-07: AI explanations (M8).**
  - Optional and off by default, through OpenRouter with your own key, so any model works by
    changing one string. Set up on the CLI (`blunderbook ai …`); the page has no settings.
  - The model gets engine facts only: the position, the moves, Stockfish's lines, evals, the
    clock and board facts python-chess works out. Never player names, ratings or your notes.
  - It explains; it doesn't analyse. It's told to use only the lines it's given.
  - One saved explanation per entry, so each is paid for once. "Explain again" replaces it.
  - Shown in the Log, and on the Re-test result only after your attempt.
  - The page shows exactly what will be sent ("What's sent") before you press the button.
    No confirm dialog.
  - (CLAUDE.md §1.3, §6, §9)
- **2026-11-07: Extensions (M9).**
  - Big features that aren't about your own mistakes, a game collection and a library of
    openings and tactics, are extensions, not core.
  - They live in this repo as their own packages (`extensions/library`, `extensions/collection`,
    a uv workspace) and are found through Python entry points: no new dependency.
  - Each keeps its own SQLite file, which the backups include.
  - They can read your Log, never change it.
  - Turned on with `blunderbook ext enable NAME`, seen after `serve` restarts. Not loaded
    while it runs: a small gain for much more complexity.
  - The game collection is general, for anyone's games, so it's not "GM analysis". On
    2026-11-07 it was renamed Collection, as Games became a core tab (below).
  - (CLAUDE.md §1.7, §15)
- **2026-11-07: A Games tab in core (M10).**
  - Your own imported games are about your own mistakes, so they're core, not an extension.
  - Grouped by the import they came from, which the database now remembers (`imports`), or
    by date; filters; a game page. Games saved before have no import and are grouped by day.
  - FEN quick entries aren't games: they stay in the Log only.
  - No delete yet: deleting a game would delete its entries and let it be imported again,
    which deserves its own decision.
  - The extension for anyone's games is now **Collection**, so there aren't two "Games".
  - (CLAUDE.md §5, §10, §11)
