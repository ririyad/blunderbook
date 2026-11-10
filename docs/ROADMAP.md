# Blunderbook: roadmap and decisions

How v1 was built, one slice at a time, and the decisions made along the way. For using
Blunderbook, see the [README](../README.md). The spec is [CLAUDE.md](../CLAUDE.md).

## Status

_Last updated: 2026-11-09_

| Milestone | State | Notes |
|---|---|---|
| M0 Planning | Done | Roadmap, README, spec path fix |
| M1 Core | Done (9/9) | Pure logic + engine + `init` / `doctor` / `import` (no DB yet) |
| M2 Storage | Done (5/5) | SQLite, migrations, dedupe, `fen` command, backup + restore |
| M3 API + Log view | Done (4/4) | FastAPI, blunder routes, web shell, Log view, `serve` |
| M4 Re-test + Patterns | Done (4/4) | Scheduling, attempts, hints, both views |
| M5 Web import | Done (3/3) | Shared import code, background job with progress, Import view |
| M6 Sync | Done (4/4) | Lichess and Chess.com adapters (recorded fixtures only), CLI `sync` |
| M7 Print + polish | Done (4/4) | A4 print page, `serve --open`, install docs |
| M8 AI explanations | Done (4/4) | Optional "Explain this blunder" via OpenRouter, your own key |
| M9 Extensions | Done (4/4) | Separate packages that add a tab, routes, commands and their own database |
| M10 Your games | Done (3/3) | A Games tab: every game you imported, by import, with a game page |
| M11 Library | Done (4/4) | Extension: openings, traps and tactics to study and practise |
| M12 Collection | In progress (2/4) | Extension: a collection of anyone's games, analysed |
| M13 Missed wins | In progress (2/3) | Log a mate or a big gain you didn't take, even when you stay winning |

**Next up:** 13.3, missed wins on the page: a "Missed win" pill in the Log, Games
("1 missed"), Re-test, Patterns and Import. Then back to 12.3, the Collection's tab: its routes, and a page for each
collection, game (with an eval graph) and player, with 12.2's filters. Still
to check from M8: one real explanation with your key, and Re-test at 390 px wide (the Log was
measured at 390 px in 10.3). Before relying
on sync, try one real `blunderbook sync` and record the responses (the fixtures are still
hand-built, `TODO(verify)`).

In place: all of M1 to M10. `blunderbook import` reads a PGN file, finds your blunders
with Stockfish (both passes), suggests causes, and saves each game and its entries to the
database. Importing the same file again adds nothing. `blunderbook fen` logs a single position
you have no PGN of. The database is backed up once a day before `import` and `fen`, and
`blunderbook backup` / `restore` work by hand. `init` creates the database and `doctor` checks
it and the backups. `blunderbook serve` opens the web page on this computer: browse your
entries, step through the game, confirm causes and write your notes. Re-test shows each due
position facing your side: tap a piece and a square, take a hint or give up, and see the
answer, your lesson and the next date. Patterns shows your causes, time controls and re-test
history. All ten §12 fixtures flag their expected move under `uv run pytest -m engine`.
The Import tab imports a pasted or dropped PGN, or one FEN position, on the page.
The Games tab lists every game you imported, by import or by date, and steps through any of them.
`blunderbook sync` downloads your new Lichess and Chess.com games and imports them (tested
against hand-built responses only; no real download has been checked yet).
`blunderbook print` writes the A4 Blunder Log page, and `serve --open` opens the page for you.
"Explain this blunder" asks OpenRouter, with your own key, to put Stockfish's lines into words
(off until you turn it on). Extensions can be installed and turned on: each adds its own tab,
routes, commands and database, is backed up with yours, and can read your Log but never change
it. The first, Library (M11), has its content, its `check` and `list` commands, a tab
that steps through each entry and its replies, and practise with spaced repetition, kept in
`library.db`, and each entry lists your own Log entries from games that reached its position.
The second, Collection (M12), adds anyone's games to collections on the CLI
(`blunderbook collection import FILE --into NAME`), every position scored once, in
`collection.db`, and shows their stats (`collection stats`, `collection players`); its tab
is next.

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
- [x] **7.4 `update` and `ext install`.** One command to bring an installed copy up to date,
      and one to add an extension, instead of remembering the uv command and every `--with`.
      _Done:_
      - **`blunderbook update [--check]`** (`update.py`): finds the git folder from the
        install's own record (PEP 610 `direct_url.json`, no setting), refuses local changes,
        no upstream or a diverged branch, fetches and lists the new commits, fast-forwards,
        then reinstalls with one `--with` per installed extension. `--check` stops after the
        list.
      - **`blunderbook ext install NAME`**: the same reinstall plus `extensions/NAME`, then
        `ext enable`. Already installed: it only turns it on.
      - **Windows:** a new PowerShell window waits for the command, its launcher and any
        running `serve` of the same install, runs uv, and stays open until you press Enter.
        Checked on this PC with a stand-in command: the wait, success and failure lines.
      - **Tests:** real git on temp repos (a bare remote and clones; no network), uv and the
        window stubbed, and PowerShell's parser on the script. A first real update on an
        installed copy is still to do (it needs this change pushed first).

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
- [x] **10.3 The Games view.** The tab, By import / By date, filters, the game page, links
      from the Log detail and the Import report, 390 px.
      _Done:_
      - **Games tab** (`js/views/games.js`), between Log and Re-test:
        - filters for source, result, time control, with or without blunders, and a search;
        - By import (a header per import with its games and blunders) or By date;
        - each row with the result, side, opponent, marks or "Clean", time control, opening
          and date.
      - **Game page** (`#games/<id>`):
        - the board from your side, with step controls, "next mistake" and the arrow keys;
        - the details and the import;
        - your entries, linking to the Log;
        - the move list, your mistakes in red.
        "← All games" keeps the filters and the scroll position.
      - **Links:**
        - The Log detail has "See the whole game" (not for FEN entries).
        - The Import report links each saved game, and adds "See these games in Games".
        - The page sends the chosen file's name in `X-Pgn-Name` (`api()` takes `headers`).
      - `localDay()` moved to `js/format.js`, shared with `explain.js`.
      - `test_web.py`: the view's fields against `GameSummary` and the game detail, the
        `/api/games` routes, the empty-state copy, the links both ways.
      - **Checked in Chrome** on a scratch database:
        - the grouped list, By date, the filters, search and the empty message;
        - the game page, next mistake and the keys;
        - Log → game → Log, and an unknown id ("No game #999.");
        - a pasted import's report links, and a dropped file named
          "Friday blitz — café.pgn" labelled as such.
        No console errors.
      - **At 390 px**, measured through the DevTools protocol (headless Chrome won't go
        below 500 px otherwise): no sideways scroll on `#games`, `#games/<id>`, `#log/<id>`
        and `#import`.

### M11 Library (extension)

- [x] **11.1** Package, content format (one TOML per entry), validator, ~15 starter entries.
      _Done:_
      - **The package:** `extensions/library/`, its own `pyproject.toml` with the
        `blunderbook.extensions` entry point. The repo is now a uv workspace: the dev
        environment installs it, so `uv run pytest` runs its tests (`testpaths`) and mypy
        checks it (strict on `content.py`). It imports only the host API (a test checks).
        No new third-party dependency.
      - **The format** (`extensions/library/README.md`): one TOML file per entry in
        `content/openings`, `traps` or `tactics`, its name the entry's id. `kind`, `name`,
        `side` (the side you practise as), `opening` and `eco` (optional), `idea`, then
        `moves` and/or a start `fen`; `[[next]]` replies at the end of the line (`move`,
        `line`, `says`, `loses`); at least one `[[practise]]` (`after`, `answers`, `prompt`).
      - **The checker** (`content.py`, pure): plays every line with python-chess. Moves must
        be legal and written as python-chess writes them (`Bxf7+`, `Nd5#`, so a mate claim is
        checked too). Move numbers are optional, and checked when given. Each practise
        position has your side to move, its answers are legal, the line's own next move is one
        of them, and no move marked `loses` is. Unknown fields, a bad ECO code or FEN, a file in
        the wrong folder or a repeated name are problems too. Each problem names the file and
        the place: "traps/legal-trap.toml: next 1: 7. Nd6# isn't legal after 6... Ke7."
      - **15 starter entries:** 5 openings (Italian, QGD, Petrov, Philidor, Caro-Kann), 6 traps
        (Légal, Blackburne Shilling, Elephant, Petrov's queen trap, Scholar's mate, Caro-Kann
        smothered mate: each is a blunder from a §12 fixture game, for 11.4) and 4 tactics
        (back-rank mate, pin, knight fork, smothered mate).
      - **Checked with Stockfish** (depth 18, by hand, not in the tests): every answer is
        sound and every `loses` move loses or throws the position away. That took out
        5. Ng4 (−4.9) from the Blackburne Shilling answers and 5... e6 (−0.7) from the
        smothered mate's, gave the knight fork three pawns (it was a drawn ending), and made
        the Petrov line's text say White is a little better.
      - **Commands:** `blunderbook library check [FOLDER]` (exit 1 on a problem) and
        `blunderbook library list`. No page yet, so no tab: `/api/extensions` lists only
        extensions with a page.
      - **Checked by hand:** `uv tool install . --with ./extensions/library` in a scratch
        tool folder, then `ext list`, `ext enable library` and both commands.
- [x] **11.2** API, index and entry views (board through the mainline and each consequence).
      _Done:_
      - **Routes** (`blunderbook_library/routes.py`, at `/api/ext/library`): `GET /entries`
        (the index, in kind order) and `GET /entries/{id}` (the idea, the start position,
        the moves and each reply played out from the end of the line). Every move carries
        the FEN after it (`content.positions()`, now public), so the page has no chess
        logic, as in core. An unknown id is a 404. The content is read and checked once.
      - **No practise answer is sent.** Practise positions and their answers come with an
        attempt in 11.3, the same rule as core's Re-test queue. A test checks that no
        response has an answer that isn't already a move of the line.
      - **The tab** (`web/view.js`, `view.css`): the index in Openings / Traps / Tactics, and
        an entry's page. The board faces the side you play. A trap or tactic opens at the end
        of its line, where the replies start; an opening at its first move (changed after
        review, 2026-11-08). It has the game page's step controls and keys (← → Home
        End) and its move list. Each reply is a card, red when it loses and green when it's
        sound, and its moves play it out on the board, with the reply's arrow in the same
        colour. It reuses the page's shared classes (panel, board, step controls, move
        buttons); its own start with `library-`.
      - **Tests** (`test_library_api.py`): the index, the FENs move by move, the replies
        (Légal's ends in checkmate), a tactic from a FEN, every entry opening, the 404, no
        answers, the tab in `/api/extensions`, and `webcheck` on the page.
      - **Checked in Chrome** over the DevTools protocol on a scratch database: the index,
        Légal's trap, the Italian Game, the back-rank mate (a FEN start), an unknown id, both
        replies played out to the mate, the keys and the move buttons. No sideways scroll at
        1300 or 390 px, and no console errors besides the unknown id's 404.
- [x] **11.3** Practise: quiz positions with spaced repetition, progress in `library.db`.
      _Done:_
      - **`library.db`** (`migrations/0001_progress.sql`): `progress`, one row per position
        you've tried (status, streak, due date), and `attempts`, every try with its move and
        whether you took the hint. A position is named by its entry's id and its FEN, so
        positions added to an entry or reordered keep their progress. An untried one has no
        row: it's new, and due today. It's backed up and restored with Blunderbook's (9.2).
      - **Scheduling is core's Re-test** (`core.retest`, CLAUDE.md §7.8): a solve moves it
        out by 1, 3, 7, 14, 30, then 60 days; a miss or giving up brings it back tomorrow; the
        hint is recorded and changes nothing. A move counts when it's any of the entry's
        answers (a bare promotion is a queen). `progress.py` holds the Library's SQL; the
        try and the new schedule are one transaction (`host.transaction`, new in the host
        API).
      - **Routes:** `GET /practise` (due today, new ones included, the oldest due first;
        `?all=1` every position; `?entry=ID` one entry's), `POST /practise/{id}/{n}/attempt`
        (refuses another site's `Origin`), `GET /practise/{id}/{n}/hint` (the square the
        answer starts from). The queue never sends an answer, a reply or the entry's idea,
        which explains the answer; a test checks each item's fields. The attempt answers
        with the answers, what the entry says about your move and about the answer ("5...
        Bxd1 falls into it: 6. Bxf7+ Ke7 7. Nd5#"), the line's own move when you found
        another right one, the idea, and the next date. The index and each entry carry your
        counts (positions, tried, solved, due).
      - **The page:** `#library/practise` (what's due), `/all` and `/<entry>`, in Re-test's
        layout (`web/practise.js`): tap to move with dots, a hint, "I don't know — show me",
        and the result with the idea. The index has a Practise panel ("26 positions to
        practise today", or the next date and "Practise all anyway") and a pill per entry
        (New, Due, Solved, "0 of 1 solved"); each entry has "Practise these 3 positions".
      - **The checker** now refuses `practise` and `all` as entry ids (the page's own
        addresses) and the same position practised twice in one entry (it would share
        progress).
      - **Also, after 11.2's review:** openings open at their first move, and the page's
        shared CSS classes are written down in CLAUDE.md §15 (`webcheck.SHARED_CLASSES`).
        A test checks app.css keeps them, and `webcheck.problems(..., prefix=name)` checks
        an extension's page uses only those and its own (`library-…`). That caught two of
        11.2's: the reply cards' `loses` / `sound` are now `library-loses` / `library-sound`.
      - **Tests** (`test_library_practise.py`): the queue (all new at first, the order, no
        answers), solving, falling into a trap, another right answer, giving up, the 1 → 3 →
        back-to-tomorrow schedule, the hint, an illegal move recording nothing, 404s, another
        site's `Origin`, and `library.db` in `blunderbook backup` (and not in your Log).
      - **Checked in Chrome** over the DevTools protocol on a scratch database: Légal's trap
        solved, the Elephant trap fallen into, a hint then giving up on Scholar's mate, Nc6
        in the Philidor ("Also right: d6"), the finished session, the index's counts and
        pills afterwards, a due session from the index. No sideways scroll at 390 px on the
        index, an entry, a position or a result, and no console errors.
- [x] **11.4** "Your entries in this opening", read from your Log.
      _Done:_
      - **Matched by position** (`yours.py`, pure and mypy-strict): a Log entry belongs to a
        Library entry when its game reaches the position at the end of the entry's line,
        compared without the move counters. So a typed-up OTB game with no ECO header counts,
        and so does another move order (1... d6 2. Nf3 e5 for Légal's trap). Each game is
        read again from its stored PGN with `core.pgn`, as core's game page does, and its
        positions are cached (a saved game's text never changes).
      - **Marked:** "Fell into it" when you played one of the entry's losing replies there,
        and "On this line" when the mistake was on the entry's line itself. Each of the §12
        trap games finds its own blunder (Légal's, Scholar's mate, the Elephant, Petrov's
        queen trap, the Blackburne Shilling).
      - **Route:** `GET /entries/{id}/log`, through `host.Log`, so your Log is only read (a
        test checks it's unchanged). Newest first, in the Log's order. Its own route, asked
        for after the entry is drawn, so the Log can never keep an entry from showing.
      - **The page:** "From your Log" at the end of each entry: how many entries, how often
        you fell into it, and each entry with its mark, the opponent and date, linking to
        `#log/<id>`. None: "None of your Log entries come from a game that reached this
        position."
      - **Checked in Chrome** on a scratch database seeded with three §12 games: Légal's trap
        (g6 on the line, Bxd1 fell into it), the Elephant and Scholar's mate, the Italian and
        a tactic with none, and a click through to the Log entry. No sideways scroll at
        390 px, no console errors.

### M12 Collection (extension)

- [x] **12.1** Package, `collection.db`, import into collections, `engine.score_positions()`
      (pass 1).
      _Done:_
      - **Core:** `engine.score_positions()` is pass 1 on its own (every position once, with
        the game's moves, finished positions without the engine), and `analyse_game` uses it,
        so a collection's game is scored exactly as your own are. The host API gets
        `daily_backup()` and `StorageError` (additions: `HOST_API` stays 1), and `core.source`
        joins the core modules an extension may use (§15).
      - **The package** (`extensions/collection`, a workspace member): `games.py` (pure,
        mypy-strict) queues a PGN's games with core's parser, fingerprints and source
        detection, and scores them; `store.py` holds all its SQL; `collect.py` adds games and
        is what 12.4's page import will reuse.
      - **`collection.db`** (`0001_collections.sql`): `collections`, `games` (each once, by
        fingerprint, with its headers, PGN, engine and depth), `positions` (every position:
        FEN, the move and clock, the eval, Stockfish's move and up to 10 moves of its line)
        and `members`. Judgments aren't stored: 12.2 works them out from the evals and your
        thresholds.
      - **Commands:** `blunderbook collection import FILE --into NAME [--depth N]` and
        `blunderbook collection list [NAME]`. No side to pick. A collection is made with its
        first game. The same file again adds nothing; a game already analysed goes into
        another collection without the engine. Each game is saved as soon as it's analysed,
        so a stopped engine or Ctrl+C keeps the games before it (exit 1 / 130), and the daily
        backup runs first.
      - **Tests** (`extensions/collection/tests`, 34): the queue, pass 1 with a scripted
        engine, the headers kept, saving and dedupe, a game in two collections, no empty
        collection, the engine stopping, Ctrl+C, no Stockfish, the commands' output,
        Windows-1252, the backups, the host-API boundary, and Légal's game with real Stockfish
        (mate in 2 after 5... Bxd1, mate 0 at the end). Their fixtures are in
        `collection_fakes.py`: a second `conftest.py` would shadow core's.
      - **Checked by hand** on a scratch home with Stockfish at depth 12: five classic games
        into "Classics", the same file again (all skipped), `list`, `list classics`, the daily
        backup of `collection.db`, and `doctor`.
- [x] **12.2** Stats: accuracy, ACPL, judgments, phases, repertoire, per player or any filter.
      _Done:_
      - **`stats.py`** (pure, mypy-strict) works it all out from 12.1's evals:
        - each move's swing and mark, with core's `detect` and your thresholds (never a
          mark for the engine's own move);
        - its accuracy (Lichess's formula), and each side's accuracy per game (the average
          of the mean and the harmonic mean);
        - centipawn loss with evals capped at ±1000;
        - and its phase.
        `report()` adds it up by side, phase, opening and game, and `players()` lists who
        played. `store.load()` reads one collection's games, or every collection's with each
        game once.
      - **Filters:** a player (ignoring case: their moves next to their opponents'), a colour,
        a result (`won` / `lost` from the player's side, `drawn`, or the side that won), an
        opening (an ECO start such as `C4`, or part of the name) and a phase.
      - **Commands:** `blunderbook collection stats [NAME]` with `--player`, `--color`,
        `--result`, `--opening` and `--phase`, and `blunderbook collection players [NAME]`.
        Without a name, every collection.
      - **Tests** (32 more, 66 in all): the accuracy and swing maths with exact values, marks
        and your thresholds, the engine's own move, phases (a game from a FEN at move 40),
        every filter, openings, players, loading from `collection.db`, and the commands'
        output and problems.
      - **Checked by hand** on the five classics from 12.1. It found that Stockfish with two
        threads can score the same position differently from run to run at depth 12:
        8... Nxe4 in Réti–Tartakower came out as mate in 3 in some runs and +1 in others.
        Depth 16, or one thread, was steady. Noted in the Collection's README; it affects
        your own imports too (`engine_threads = 2` is the default).
- [ ] **12.3** API, collection / game / player views with filters and an eval graph.
- [ ] **12.4** Import on the page, and links to your Log.

### M13 Missed wins

Asked for on 2026-11-10: track the attacks you missed, not only your blunders. Done before
12.3. See Decided.

- [x] **13.1** Core: the missed-win rule, its judgment, and the "Missed my tactic" hint.
      _Done:_
      - **The rule** (`detect.missed_win`): not Stockfish's move, and either a forced mate
        lost, or at least `missed_win_cp` (300) ahead with the eval dropping by 300 or more,
        evals capped at ±1000. `analyse_game` flags these as well as blunders; their judgment
        is `blunder` at or over the blunder line, else `missed`. Pass 2 runs for them, and the
        progress total counts them.
      - **The hint** (`hints.missed_my_tactic`): a lost mate, or Stockfish's best line (pass
        1's, now kept on the `Finding` as `best_pv_uci`) played out 6 plies leaves you 3 or
        more material up.
      - **The setting:** `[thresholds] missed_win_cp = 300`, a whole number, 0 turns it off.
      - **Marks:** `missed` has none (`""`) everywhere a mark is looked up (importer, print,
        the AI prompt, `format.js`), so nothing breaks before 13.2 and 13.3 give it its words.
      - **Tests:** the rule (mates, the cap, losing positions aren't misses, off), the
        engine's judgment and pass 2 with a scripted engine, the hint, the setting, and a new
        fixture, `missed_mate.pgn`: 30. h3 misses Rd8# and stays winning (swing about 0.04),
        flagged `missed` with Rd8 accepted, at depth 12 with one thread in every run tried.
- [x] **13.2** Storage, API, CLI and print: the games list counts missed wins, the FEN and
      import reports name them, the print page labels them, and the AI prompt says "a missed
      win" (`PROMPT_VERSION` bumped).
      _Done:_
      - **No migration:** `judgment` has no CHECK, so `missed` is stored as it is.
      - **Games list:** `repo.list_games` counts `missed` next to the other judgments, and
        `/api/games` gives it on each game (`GameSummary.missed`).
      - **Words:** `models.JUDGMENT_NOUN` ("a blunder" … "a missed win") for the FEN message
        ("Logged 30. h3 as a missed win: entry #2."), and the AI prompt ("6. Nxd5, a missed
        win."). The CLI report says `entry #1, missed win`, and the summary counts them apart
        ("1 blunder and 1 missed win added", or "1 missed win added"). The print page shows
        "Missed win" with no mark.
      - **AI prompt:** a new rule tells the model a missed win leaves you ahead, so it says
        what the best move would have won. `PROMPT_VERSION` is 2.
      - **Tests:** the repo and API counts, the summary, `log_fen` and `blunderbook fen`, the
        print page and the prompt.
      - **Checked by hand** on a scratch home with Stockfish 19 at depth 12, one thread:
        `import missed_mate.pgn` (entry #1, missed win; "1 missed win added"), `fen` on the
        same position ("as a missed win"), and `print` ("30. h3 Missed win").
- [ ] **13.3** The page: a "Missed win" pill (amber) in the Log, Games ("1 missed"), Re-test,
      Patterns and Import.

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
- **2026-11-07: The Library's content (11.1).**
  - One TOML file per entry, so you can read, edit and add entries without code. The
    checker runs before anything uses them, and on demand (`blunderbook library check`).
  - `side` is the side you practise as, and the board faces it: for a trap, the side that
    must avoid it.
  - Practise answers are listed by hand, not asked of Stockfish when you practise: the
    Library works without an engine, and its answers stay the same. They were checked with
    Stockfish when written; more than one can count as right.
  - `loses` marks a reply that falls into the trap or throws the position away.
  - The extension lives in this repo as a uv workspace member, installed in the dev
    environment so one `uv run pytest` runs everything.
  - (CLAUDE.md §4, §12, §15)
- **2026-11-07: A Games tab in core (M10).**
  - Your own imported games are about your own mistakes, so they're core, not an extension.
  - Grouped by the import they came from, which the database now remembers (`imports`), or
    by date; filters; a game page. Games saved before have no import and are grouped by day.
  - FEN quick entries aren't games: they stay in the Log only.
  - No delete yet: deleting a game would delete its entries and let it be imported again,
    which deserves its own decision.
  - The extension for anyone's games is now **Collection**, so there aren't two "Games".
  - (CLAUDE.md §5, §10, §11)
- **2026-11-07: Smoother moves on the board.**
  - Drawing the next position into the same board updates it in place: the squares stay, so
    a focused square keeps focus after a tap in Re-test.
  - Pieces slide to their new squares (180 ms). Each new square takes the nearest piece of
    the same kind that left, so castling, jumps of several moves and promotions slide too;
    captures fade out, and arrows come in once the pieces have arrived. Nothing moves when
    the system asks for less motion.
  - Re-test shows a dot on each square the picked piece can reach (a ring for a capture),
    from the legal moves the API already sends. Tapping the piece again puts it down.
  - Not yet: drag and drop, and a promotion picker (Re-test still promotes to a queen,
    §7.8). (CLAUDE.md §11)
- **2026-11-08: Library practise (11.3).**
  - Practise is core's Re-test for the Library's positions: the same intervals, the same
    reading of a move, the same rule that the answer comes only after a try. One set of
    rules, already tested, rather than a second scheduler.
  - Progress is kept by entry and position (its FEN), not by the practise number, so editing
    an entry doesn't move your progress to another position.
  - Everything is due on the first day (26 positions), as new Log entries are. No daily cap
    on new positions: the Library is small.
  - The idea is shown after a try, never before: for a trap it gives the answer away.
  - Extensions get `host.transaction` (an addition, so `HOST_API` stays 1).
- **2026-11-08: Your entries in a Library entry (11.4).** Matched by position, not by ECO
  or opening name: headers are often missing (OTB, typed-up games) and an ECO code covers
  many lines, while a position is exact and catches other move orders. The position is the
  end of the entry's line, so a game that left the line early isn't listed; an entry that
  should also catch earlier positions can get a shorter line. Read on request from your Log,
  never copied into `library.db`.
- **2026-11-08: The page's shared CSS classes.** An extension's tab uses the page's own
  panels, buttons, board, step controls, move list and puzzle layout, so it looks like the
  rest. Those classes are now a written list that a test keeps, and an extension's page check
  refuses any other class that isn't its own. Openings in the Library open at their first
  move. (CLAUDE.md §15)
- **2026-11-08: `update` and `ext install` (7.4).** One `update` for Blunderbook and every
  extension: they live in the same repo, so one pull updates them all, and a per-extension
  update couldn't do anything different. It always reinstalls, even with nothing new, so
  running it again finishes a reinstall that failed (e.g. `serve` was running). Windows
  locks a running program's files, so the reinstall is handed to a new window that waits.
  The fetch is a network call when you run it, like a sync (CLAUDE.md §1.3).
- **2026-11-08: A favicon.** A notebook with an ink spine and a red "??", in the page's own
  colours (`web/favicon.svg`, served from our own files under the same CSP). The print page
  carries it inlined, so the saved file still stands alone.
- **2026-11-09: The Collection's games (12.1).**
  - A game is analysed once and can be in any number of collections (`members`), so the
    same game in two collections costs one analysis, and the stats of both use the same
    evals.
  - Only pass 1 is stored, for every position: the eval, Stockfish's move and its line.
    Judgments, accuracy and the rest are worked out when they're shown, so a changed
    threshold applies everywhere, as it would if your Log were re-imported.
  - A game already analysed at another depth is reused as it is; its depth is kept with it.
  - Collection names ignore ASCII case and are made by the first game added, like core's
    imports, so an import that adds nothing leaves no empty collection.
  - Importing is on the CLI first; the page comes in 12.4.
- **2026-11-09: The Collection's stats (12.2).**
  - **Marks** are your Log's rules exactly: the swing, your thresholds, and none for the
    engine's own move.
  - **Accuracy** is Lichess's per-move formula, and per game the average of the mean and
    the harmonic mean. Lichess also weights moves by how sharp the position is; that's left
    out to keep the number simple to explain.
  - **ACPL** caps evals at ±1000, as Lichess does.
  - **Phases:** the endgame at six pieces or fewer besides kings and pawns (both sides),
    else the opening to move 10 and the middlegame after. Move numbers come from the
    position, so a game from a FEN at move 40 has no opening.
  - **Players** are matched by name, ignoring case, so "Anderssen, A." and
    "Adolf Anderssen" are two players. Merging names waits until it's needed.
- **2026-11-10: Missed wins (M13).**
  - **What counts:** a win you didn't take: a forced mate you had and lost, or a drop of
    `missed_win_cp` (300 cp) or more while you were at least that far ahead, with evals capped
    at ±1000 so +15 → +11 isn't one. Stockfish's own move never is. Requiring you to be ahead
    keeps a losing drop (+0.4 → −4) a blunder or mistake, not a "missed win".
  - **Why a separate rule:** winning chances flatten out near a win, so missing a mate at +8
    and staying at +5 is only an inaccuracy by the swing, and imports never logged it.
  - **How it's shown:** a word, "Missed win", not a symbol. Over the blunder line it stays a
    blunder (`??`).
  - **Suggested cause:** "Missed my tactic" (a lost mate, or Stockfish's line wins 3 or more
    material). Only a suggestion, like the others.
  - **Not in it:** games imported before aren't re-analysed (no re-analyse command), the
    Collection's stats, and their threats you missed beyond today's hints.
