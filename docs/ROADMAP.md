# Blunderbook: roadmap and decisions

How v1 was built, one slice at a time, and the decisions made along the way. For using
Blunderbook, see the [README](../README.md). The spec is [CLAUDE.md](../CLAUDE.md).

## Status

_Last updated: 2026-11-21_

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
| M11 Library | Removed (2026-11-20) | Extension: openings, traps and tactics to study and practise. The Journal replaced it; its entries are Journal examples |
| M12 Collection | Done (4/4) | Extension: a collection of anyone's games, analysed |
| M13 Missed wins | Done (3/3) | Log a mate or a big gain you didn't take, even when you stay winning |
| M14 Page polish | Done (4/4) | Smoother page: the shell, one board with step controls, a review flow, import and re-test feedback |
| M15 Desktop app | Planned | v2: a download anyone can double-click, with extensions added and removed from its Extensions page |
| M16 Rankings | Done (4/4) | Extension: the FIDE, Lichess and Chess.com top lists, updated when you ask |
| M17 Profile | Done (4/4) | Extension: your Lichess and Chess.com ratings, and your rating over time next to your blunders |
| M18 Game commentary | Planned | Collection: every move explained (what, why, what followed), from Stockfish's lines, with optional AI prose |
| M19 Journal | Done (5/5) | Extension: fast chess notes in Markdown, with PGN and FEN that play on a board |
| M20 Cost, not count | Planned | Patterns: what each cause, time control and opening costs you, in points per 10 games |
| M21 Solid core | In progress (3/10) | Fewer false entries, the evals kept, `reanalyse`, more suggested causes, a fairer re-test |

**Order of work** (decided 2026-11-20, revised 2026-11-21, see Decided):

1. **M19 Journal.** Started 2026-11-20, after the prototype's feedback; done 2026-11-20.

_Stage 1: a safety net and the data (no change to what's logged)_

2. **21.2 Clean-game fixture.** First, so every later change to detection is checked for
   false entries. It may show some the app logs today.
3. **21.1 Keep the evals.** 21.3, 21.5, 21.9 and M18 build on them, and on `phase` and
   accuracy moving into core.
4. **21.10 Engine safety limit.** Small, and it protects every later engine run, including
   the long `reanalyse` runs.

_Stage 2: what gets logged_

5. **21.3 Check each flag with the move you played.**
6. **21.6 Fairer re-test answers.** The same pass-2 loop as 21.3, so the two land together.
7. **21.5 More suggested causes.** Before `reanalyse`, so one run refreshes them too.

_Stage 3: your old games_

8. **21.4 `reanalyse`.** One run brings old games to every rule from stages 1 and 2.

_Stage 4: Patterns, from checked entries_

9. **M20 Cost, not count.** Its costs add up swings, so they come after 21.3 and 21.4.
10. **21.9 When you blunder.** The same `core/patterns.py` and view as M20.

_Stage 5: the re-test loop_

11. **21.7 Re-test scheduling.**
12. **21.8 The same position again.** After 21.7: both change how the queue is built.

_Stage 6: the milestones planned before M21_

13. **M18 Game commentary.** Accuracy and phase from core (21.1), checked entries (21.3).
14. **M15 Desktop app.** It opens with a packaging test (15.0), then 15.1 to 15.8. Its
    bundled Stockfish (15.5) relies on `reanalyse` (21.4).

The milestone and slice numbers stay as they are; only the order changes.

**Next up:** 21.3, check each flag with the move you played (next in the order of work;
its rule still needs your yes). Stage 1 is done: 21.2, the clean-game fixture; 21.1, keep
the evals; 21.10, the engine's safety limit. M19, the Journal extension,
is done: notes in Markdown with PGN, FEN and moves in sentences that play on a board,
boards that write, Analyse, history and export. Still to check from M19: the tab on a real
phone at 390 px (Chrome on this Mac stops at 570 px, where it was checked). M17, the Profile extension,
is done. Still to check from M17: one real `blunderbook profile refresh` or press of Refresh
ratings (the rating fixtures are hand-built, `TODO(verify)`), and its tab on a touch screen. M15, the desktop app, is planned
below and not started. M16, the Rankings extension, is done; check its tab at 390 px on a real phone once. Still to check from M8: one real explanation with your key, and Re-test at 390 px wide (the Log was
measured at 390 px in 10.3); from 13.3, the "Missed win" pills at 390 px. Before relying
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
`collection.db`, and shows their stats on the CLI (`collection stats`, `collection players`)
and in its tab: each collection, its players, and each game with an eval graph and links to
your Log entries from its positions. Games can be added on the tab too.
Missed wins (M13): a mate or a big gain you didn't take is logged too, even when you stay
winning, shown as "Missed win" (no mark), with "Missed my tactic" suggested.
Profile (M17), another extension, shows your own ratings on Lichess and Chess.com, fetched
only when you press Refresh ratings or run `blunderbook profile refresh` and kept in
`profile.db`, and your rating over time from the games in your Log, with your blunders per
game under it.

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

**Removed on 2026-11-20** (see Decided): the Journal does its job, as notes you write. Its
15 entries are `extensions/journal/examples/`. The slices below are kept as history.

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
        is what 12.4's page import reuses.
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
- [x] **12.3** API, collection / game / player views with filters and an eval graph.
      _Done:_
      - **Routes** (`routes.py`, at `/api/ext/collection`, all GET): `collections`; `stats`
        with `collection` (a number or `all`) and 12.2's filters (`player`, `color`,
        `result`, `opening`, `phase`), plus the filter menus' players and openings and the
        engines used; `players`; and `games/{id}` with every position (its FEN, eval and
        White's winning chances, for the graph) and every move judged (its mark, accuracy,
        centipawn loss and phase; for a marked move, Stockfish's move, its line and the line
        after). Your thresholds are read from config.toml on each request. `store.py` gains
        `by_id`, `count_games`, `engines` and `game_detail`.
      - **The tab** (`web/view.js`, `view.css`, classes `collection-…`): the collections; a
        collection's tiles, filters (kept in the address: `#collection/1?player=…`), by
        phase, openings and games; its players, each opening their stats; and a game page
        on core's board and step controls, with arrow keys, "next marked move", an eval
        graph (an SVG; dots for marked moves; click to jump) and the marked move's lines.
      - **Tests** (21 more, 87 in all): the routes with a scripted engine (Légal's 5... Bxd1
        a blunder, its best move and refutation), every filter and its refusals, thresholds
        read each time, players, a game's positions and chances, a 404, the date label, the
        tab listed, the page checks, and that every route is a GET.
      - **Checked in Chrome** on a scratch home (classics at depth 12): the collections, the
        stats, a filter by player and result, clearing the player (the result resets), the
        phase filter, players, and a game page with the graph and next marked move. No
        console errors. Not checked at 390 px: the window couldn't be resized
        (`TODO(verify)`).
- [x] **12.4** Import on the page, and links to your Log.
      _Done:_
      - **The import job** (`jobs.py`): one import into a collection at a time, in a thread
        with its own connection to `collection.db` and one Stockfish, through the same
        `collect.add` as `collection import` (now with `should_stop`, checked between
        positions). It takes the daily backup first (a failure is a note). Each game's status
        (waiting, analysing, added, added already analysed, skipped, can't be read, not
        analysed), the percentage and the CLI's summary line (`collect.summary`, now printed by
        `collection import` too) are read while it runs. The last job is kept for its report.
      - **Routes:** `POST /api/ext/collection/import?into=NAME` (the PGN's bytes, as core's
        import: `application/x-chess-pgn` or 415, the page's own `Origin` or 403, 10 MB or
        413, no games or a bad name 422, busy 409) → 202 `{job_id}`; `GET /import/{job_id}`.
        Stopping `serve` stops the job: the router's lifespan, which FastAPI merges into the
        app's.
      - **Your Log:** `games/{id}` gains `yours`, your Log entries whose position before your
        move is one of the game's positions (the FEN's first four fields), each with the ply
        it's at. Read through `host.Log`, read-only.
      - **The tab:** "Add games" on the collections, the empty state and a collection's page
        (with its name filled in), a form (name with your collections offered, paste, choose or
        drop), the progress bar and report, linked to each game and the collection; a game's
        "From your Log", linked to `#log/<id>`, with "Show it here".
      - **Tests** (15 more, 102 in all): an import end to end with one engine, the same games
        again (skipped), into a second collection (reused), Windows-1252 and an unreadable
        game, no Stockfish, every refusal, an unknown job, a second import while one runs,
        stopping `serve`, `should_stop`, and your Log's entry on Légal's game (and not on
        Morphy's). Every route but the import is still a GET.
      - **Checked in Chrome** on a scratch home: three games into a new "Traps" (two analysed,
        Légal's reused from Classics), the progress and report, "Open Traps"; the same game
        again, skipped; "Add games" from a collection filling in its name; Légal's game listing
        your 5... Bxd1?? (entry #5) and "Show it here" stepping to the position after 5. Nxe5.
        It found the report out of view when an import started (it scrolls to it now), and
        "Already in Traps — skipped" next to "Already in this collection" (now "Skipped").
        No console errors. Not checked at 390 px (`TODO(verify)`).

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
- [x] **13.3** The page: a "Missed win" pill (amber) in the Log, Games ("1 missed"), Re-test,
      Patterns and Import.
      _Done:_
      - **`format.js`:** `JUDGMENT_WORD` ("missed win"), `markText()` (the mark, or
        " (missed win)") and `markPill()` (the red mark pill, or an amber "Missed win").
      - **Log:** the list's pill, a "Missed win" pill next to the move in the detail, and
        "Position before your missed win" on the board.
      - **Games:** the row's marks plus an amber "1 missed" pill (its label "1 missed win"),
        the import header ("1 game · 1 missed win"), the entry list's pill, the move in amber
        in the move list (`mbtn miss`), and "your missed win comes next".
      - **Re-test and Patterns:** "30. h3 (missed win)" in the result and the history.
        **Import:** "1 missed win found" (or "1 blunder and 1 missed win found").
        **AI:** "Explain this missed win".
      - **CSS:** `p-missed-win` and `mbtn.miss` in amber.
      - **Tests:** every judgment has a mark and a word in `format.js`, the new classes are
        styled, and `test_web`'s field check covers the games list's `missed`.
      - **Checked in Chrome** on a scratch home (Stockfish 19, depth 12): the Log list and
        detail, the Games list and game page, solving the missed mate in Re-test (Rd8#
        accepted), the Patterns history, and a pasted import. No console or CSP errors.
        Not checked at 390 px wide: the browser window couldn't be resized, as in 8.4
        (`TODO(verify)`).

### M14 Page polish

Asked for on 2026-11-11, after v1's milestones: a smoother, more solid page. From reading
the shell, the styles and every view. See Decided.

- [x] **14.1** The shell.
      _Done:_
      - **Tabs:** opening another tab starts at the top of the page (a route inside a tab
        doesn't scroll: Games and the Library put their lists back themselves). A route can
        carry a query (`#log?cause=…`, `#log/12?cause=…`), passed to the view with the rest;
        before, `#log?…` was an unknown route. 14.3 uses it.
      - **The error line** has "Try again" (loads the open tab and the badge again) and
        "Dismiss", built with DOM calls. `showError(text)` is unchanged for extensions.
      - **A phone** (under 640 px): no tagline, the tabs are one row that scrolls sideways
        (the open one scrolled into view), and the header stays at the top. Before, seven
        tabs wrapped into three rows and the header scrolled away.
      - **Fingers** (`pointer: coarse`): buttons, tabs, chips, step buttons, menus and move
        buttons are at least 44 px high.
      - **A tab that hasn't drawn yet** says "Loading…" after 300 ms (CSS only).
      - **One copy** of `statusPill` and `plural`, in `format.js`; the views and both
        extensions use it (`plural` and `markText` join the names extensions may import).
      - **Tests** (4 more): the scroll and the query, the error line, the phone and touch
        rules, and that no view keeps its own copy of the helpers.
      - **Checked in headless Chrome at 390 px** through the DevTools protocol (the Chrome
        extension wasn't connected): no sideways scroll on `#log`, `#patterns`,
        `#collection` and `#games/<id>`; the tab row scrolls and keeps the open tab in view;
        the header is sticky; Patterns → Log lands at the top; `#log?cause=…` opens the Log;
        with the network off the error line shows, and "Try again" loads the tab. No
        console errors. Screenshots at 500 px and 1200 px looked right.
- [x] **14.2** One board with step controls, and the Log's rough edges.
      _Done:_
      - **`js/steps.js`:** the one copy of the step buttons (`stepsHtml`), their wiring and
        disabled states (`bindSteps`), the icons, and ← → Home End. The keys are heard on
        the document and go to the board on screen, unless you're typing. Before, Games, the
        Library and the Collection each listened on their own section, so the keys did
        nothing until you clicked in the view (the focus is on the page body right after a
        game opens: confirmed in the browser).
      - **The four boards use it:** the Log (which gains "End of game" and the keys), Games,
        the Library and the Collection. Each keeps its own drawing. The "next mistake" /
        "next marked move" button is disabled when there's none. Every button has a tooltip.
        `/js/steps.js` joins the page modules an extension may import (`HOST_API` stays 1).
      - **Delete asks in the page:** "Delete 5... Bxd1?? from your Log?" with Delete and Keep
        in the button's place, focus on Keep, Escape keeps. The page has no browser dialogs
        left (a test checks).
      - **The list** scrolls the open entry into view (`#log/40` from the Import report),
        moving only the list, not the page.
      - **The save line** says "Saving…", then "Saved" until the next change (it used to
        vanish after 1.2 s). A failed save shows "Try again".
      - **Tests** (2 more; the exports test covers `steps.js`): no `confirm(` / `alert(` /
        `prompt(` in page files; the Log and Games use the shared controls and keep no key
        handler or icons of their own.
      - **Checked in headless Chrome** (DevTools protocol, keys sent as real key events):
        - Games: open a game from the list and press → twice with no click, then End;
        - the Log: →, Home, the End button; → while typing in Lesson leaves the board alone;
        - the Collection and the Library (turned on for this): → steps;
        - the save line: "Saving…" → "Saved", still there 2.5 s later; with the network off,
          "Not saved … Try again", which then saves;
        - delete: the question with focus on Keep, Escape restores the button, Delete removes
          the entry and opens the next;
        - `#log/5` at 390 px, the delete question open: no sideways scroll.
        No console errors.
- [x] **14.3** Review flow.
      _Done:_
      - **"Needs your notes":** an entry with no confirmed cause or no lesson
        (`models.needs_notes`; the same rule in SQL in `repo.list_entries`).
        `GET /api/blunders?notes=missing` keeps those, and each list item carries
        `needs_notes`. In the Log: a "Needs your notes" toggle in the filter bar, and "needs
        notes" in amber on a row, which clears as soon as you've written both.
      - **The Log's filters are in the address** (`#log/12?status=due&cause=…&notes=missing`),
        written with `replaceState`. A link with no query keeps the filters that are set,
        `#log?` clears them, and a link with filters and no entry opens the first match.
      - **Previous / Next** over the entry, with "3 of 12", through the filtered list. An
        entry the filters leave out says so.
      - **Patterns links to what's behind its numbers:** each cause and the biggest leak to
        `#log?cause=…`, "Blunders logged" to the Log, "Due for re-test" to Re-test, and
        "Review them" to `#log?notes=missing`.
      - **Tests** (4 more): the repo's filter (a cause but no lesson, a lesson but no cause,
        a blank lesson, both), the API's `notes=missing` and `needs_notes`, `notes=done`
        refused, and the page's wiring.
      - **Checked in headless Chrome:** Next moves through the list and the address follows;
        the toggle narrows the list; confirming a cause and writing a lesson clears "needs
        notes" on the row; a Patterns cause opens the Log filtered by it (other filters
        cleared), and a reload keeps it; `#log?notes=missing`; `#log/2` keeps the filters;
        `#log?` clears them. No console errors.
- [x] **14.4** Import and Re-test feedback.
      _Done:_
      - **An import shows on its tab:** a blue badge with the percentage, on every tab. The
        shell calls the Import view's `resume()` at start, so a job that was running before
        a reload is followed again without opening Import.
      - **When it ends on another tab**, a toast gives the summary line ("Import done: 5
        games read · 6 blunders added"). The Re-test badge already updated.
      - **The Import button** reads "Importing…" and stays disabled while a job runs (a
        second press was a 409), and starting an import scrolls the report into view (on a
        narrow screen it's under both cards).
      - **A Re-test session ends with its score:** "Session done: 1 of 10 solved", and the
        ones you missed (your move, the best move), each linked to the Log. The results are
        kept on the page only, and only after the server answered an attempt.
      - **Every result** has "Open this entry in the Log", and the progress bar counts
        answers, so it's full when the last one is in.
      - **Tests** (2 more): the badge, `resume()`, the toast and the busy button; the
        session summary, filled only after an attempt.
      - **Checked in headless Chrome:** five fixture games pasted at depth 16: the button
        went to "Importing…", the badge counted up on the Log tab (2% … ), then hid, the
        toast gave the summary and the Re-test badge went to 10. A ten-puzzle session, nine
        given up and one solved: the bar reached 100%, every result linked to the Log, and
        the end screen listed the nine. No console errors. Not checked: `resume()` after a
        reload in the middle of an import, and both at 390 px (`TODO(verify)`).

### v2: M15 Desktop app (planned, not started)

Planned on 2026-11-11; v1 is done. Blunderbook as a download anyone can double-click, in
place of Python, uv, a git clone and a separate Stockfish.

- **Decided:** desktop only (Windows, macOS, Linux); public, built by GitHub on every commit
  and published as release assets; not signed or notarised (the code is there to read);
  its own window (pywebview); Stockfish and both extensions inside (all GPL-3).
- **Extensions page (planned 2026-11-17).** Asked for: an "Extensions" item in the app's
  menu, listing the app's extensions, with **Add** and then a red **Remove**. See Decided.
- **Last in the order** (2026-11-20): it packages everything, so the extensions and core
  changes made before it ship in the first build.
- [ ] **15.0** Packaging test, before 15.1 (about half a session, nothing committed but its
      findings here):
      - A throwaway PyInstaller one-folder build on macOS. It holds the server, one page,
        python-chess and Stockfish found inside the app, plus pywebview opening the page.
      - It works: 15.1 to 15.8 go ahead as written.
      - It fails on Python 3.15: the plan changes first (another bundler, or building
        with an older Python), before anything is built on it.
- [ ] **15.1** One server, swappable: `blunderbook/server.py`, the "one way to start the
      server". The server serves a thin holder that forwards each request to the current
      FastAPI app; `build()` (config, `ext.load`, databases opened and upgraded with their
      `-pre-migrate` backups, `create_app`) and `swap()` replace it without a restart: same
      port, same window, requests already running finish on the old app. `cli.serve` uses
      it, and `_serve_extensions` moves there.
- [ ] **15.2** Extensions on the page (`#extensions`, a built-in view; "extensions" joins
      `ext.RESERVED`):
      - `Extension` gains `summary` (one line) and `network` (what it asks the network for,
        "" if nothing): additions, so `HOST_API` stays 1. Filled in for all four.
      - `ext.catalog(cfg)`: every known extension and its state: on, off, not installed (a
        folder `update.available()` finds in a git install), or a problem.
        `ext.enable` / `ext.disable` take over the logic in `cli.ext_enable` / `ext_disable`,
        so the commands and the page run the same code.
      - `GET /api/extensions/catalog`, `POST /api/extensions/{name}/add` and `/remove`
        (`same_origin`; 409 while an import runs). Add or Remove changes config.toml, then
        swaps in a fresh app (15.1), and the page reloads with the new tabs.
      - The page: grouped On, Available, Not installed; each with its summary and what it
        has (tab, commands, own database, "uses the network when you ask"). **Add** is the
        primary button; **Remove** is red and asks in the page first ("Its data stays",
        Remove / Keep). A not-installed one shows `blunderbook ext install NAME`; a broken
        one says why.
      - A quiet "Manage" link at the end of the extensions tray; with none on, the tray
        holds just that link.
      - Remove keeps the extension's data (like `ext disable`). Only the bundled extensions
        are listed: nothing is downloaded and no outside code is loaded.
      - Changes "no settings page in v1" (CLAUDE.md §6) and "settings go through the CLI
        only" (§10), as Setup (15.3) would have. Also §9, §10, §11, §15, README.
- [ ] **15.3** Setup on the page: with no config.toml the app creates it and the database;
      `GET` / `PUT /api/setup` and a Setup tab for your names. Turning extensions on and off
      is the Extensions page's (15.2). Engine depth, thresholds, sync, backups and AI stay in
      config.toml and the CLI.
- [ ] **15.4** The window: `blunderbook/desktop.py` and `blunderbook app` (the server on a
      thread, a pywebview window, a free port if 8732 is taken, closing the window stops the
      server and any import). An application menu (`webview.start(menu=…)`) with
      "Extensions…", which opens `#extensions`; pywebview's docs list only per-window menus
      as unsupported on GTK (`TODO(verify)` on Windows and Linux). pywebview is an optional
      extra. On Linux with no WebKitGTK it opens the browser, where the "Manage" link
      reaches the same page.
- [ ] **15.5** Frozen-app behaviour: a "bundled" step in the Stockfish lookup, between
      `stockfish_path` and PATH, when the app is frozen; `update` and `ext install` say
      plainly what a downloaded app can't do; `build_info.py` (version and commit), shown by
      `doctor`.
- [ ] **15.6** The build: a PyInstaller one-folder bundle (`packaging/`), with two programs
      (`Blunderbook`, the window, and `blunderbook-cli`), the page, the migrations, every
      extension with its data and entry-point metadata (so "Add" is turning it on, never an
      install), and Stockfish fetched at a pinned version and SHA-256 (baseline x86-64
      builds). A smoke test runs the built app: `doctor`, an import of a fixture, `ext list`,
      the extensions catalog, the server.
- [ ] **15.7** Built by GitHub on every push to `main`: the tests (their first CI run), then
      Windows, macOS (Apple silicon) and Linux builds with the smoke test, published as a
      rolling "Latest build" pre-release with `SHA256SUMS.txt` and build attestations; a
      `v*` tag makes a release. README gets a "Download" section: which file, the one-time
      Gatekeeper and SmartScreen steps, how to check a download, where your data lives.
- [ ] **15.8** "Check for updates": in Setup and `update --check`, asks GitHub for the latest
      build's commit, only when pressed; it links to the release and never installs. A new
      network call, to list in CLAUDE.md §1.3.
- **Not in it:** signing, app stores, automatic updates, phones, a full settings page,
  installers (`.msi`, `.deb`), extensions from outside the app (a user folder, downloads).
- **Risks:** Windows and Linux are checked only by CI's smoke test until someone opens each
  once; unsigned PyInstaller apps are sometimes flagged by antivirus; the download is about
  80 to 120 MB; a frozen Python 3.15 app is unproven until 15.6 (PyInstaller 6.22 and
  pywebview 6.2 do resolve on 3.15).

### M16 Rankings (extension)

Planned on 2026-11-12. The top lists of FIDE (the official world ratings), Lichess and
Chess.com, each on its own sub-tab of a Rankings tab. An extension (CLAUDE.md §1.7, §15):
rankings aren't about your own mistakes.

- **Decided:**
  - **Online only when you ask:** `blunderbook rankings update`, or the tab's Update
    button. Nothing checks or downloads on its own. The tab says when a newer FIDE
    list is probably out (a list from an earlier month), without asking the network. For an
    automatic monthly update, schedule the command (Windows Task Scheduler, cron).
  - **Only what changed is downloaded:** the ETag and Last-Modified of each file are kept
    and sent back. A 304, or the same ETag (the same Last-Modified when there's no ETag),
    is "already up to date".
  - **Polite:** one request at a time, a descriptive User-Agent, a timeout; HTTP 429 waits
    (Retry-After, at least a minute), tries once more, then stops with a plain message.
  - **Safe:** everything is downloaded and read before anything is written, in one
    transaction; a failure keeps the lists you had and records why; Ctrl+C changes nothing.
    A download is capped at 200 MB, and the zip must hold one XML file of at most 400 MB.
    The XML is read as a stream.
  - **Small:** rankings.db is in every backup, so it keeps only what the tab shows: FIDE's
    active players, the world top 100 and each federation's top 50 in Open, Women, Juniors
    and Girls, from the latest list of each speed only (the one before is deleted when a
    new one is saved; see Decided, 2026-11-12); the latest Lichess and Chess.com boards.
- [x] **16.1** The package, rankings.db and FIDE's lists on the command line.
      _Done:_
      - **`extensions/rankings/`**, a workspace package like the Collection, with its entry
        point, `httpx` as a dependency (already core's), and `migrations/0001_rankings.sql`:
        `sources` (each source's newest month, when it last changed, when it was last
        checked, the last error), `downloads` (ETag and Last-Modified per URL),
        `fide_players` and `site_players` (for 16.2).
      - **`net.py`:** the client, conditional downloads to a file with a size cap, one retry
        after a 429, and a wait that a stop interrupts.
      - **`fide.py`:** the three XML lists' URLs, one player's fields (inactive `i`/`wi`,
        unrated and unnamed players left out; title codes; a woman's title when there's no
        other), the month from the member's name (`standard_nov26frl_xml.xml`) or else from
        Last-Modified, and the selection, kept with small heaps while the file is read.
      - **`store.py`:** all the SQL; a list replaces its month (FIDE sometimes republishes)
        and only two months of each list are kept; `fide_top` for 16.3.
      - **`update.py`:** `update_fide`, shared by the command and (16.3) the page.
      - **Commands:** `blunderbook rankings update [fide]` (the daily backup first; Ctrl+C
        exits 130 and changes nothing; a failure exits 1 and keeps the lists) and
        `blunderbook rankings status` (each list's month, players kept, when it was
        downloaded, a stale-list hint, the last failure).
      - **Tests** (60): players, the zip's guards, who's kept (ties at the cut, Juniors at
        20), updates against a fake server (304, a server that ignores the question, a new
        month, two months kept, a republished month, a failure halfway, a bad file, offline,
        too big, 429 once, twice and too long, a stop), the commands, the daily backup,
        `rankings.db` in `backup`, and the host API boundary. No test goes online.
      - `TODO(verify)`: FIDE's XML element names, title codes and member name, and its
        junior rule; the fixtures are hand-built from FIDE's description until a real
        download is recorded (16.4).
- [x] **16.2** The Lichess and Chess.com leaderboards.
      _Done:_
      - **`lichess.py`:** `GET https://lichess.org/api/player/top/100/{perfType}` for
        bullet, blitz, rapid, classical and ultraBullet, one at a time (checked in the
        official API spec on 2026-11-12). Lichess sends no ETag, so its five small answers
        are fetched each time. Its own `progress` is kept as the change.
      - **`chesscom.py`:** `GET https://api.chess.com/pub/leaderboards`, one answer for
        every board; `live_rapid`, `live_blitz`, `live_bullet` and `daily` are kept (top
        50), the others (variants, tactics, lessons) left out. Its ETag is sent back, so an
        unchanged answer is a 304: "already up to date".
      - **Both:** an entry without a name or a rating is skipped; names and titles are cut to
        a sane length; an answer that isn't a leaderboard is a plain error. A source's boards
        are replaced together, in one transaction, or not at all.
      - **The User-Agent** carries `[chesscom] contact` when it's set, for Chess.com only,
        as Chess.com asks. `host.settings()` gains `chesscom_contact` (added, so `HOST_API`
        stays 1); a contact with a line break is never sent.
      - **`blunderbook rankings update [fide|lichess|chesscom|all]`**, `all` by default:
        one line per source; one source failing doesn't stop the next (exit 1 at the end);
        Ctrl+C keeps the sources already done and says which wasn't changed.
        **`status`** has a line per source and each one's last failure.
      - **Tests** (29 more): both answers (titles, missing fields, sorting and the cap, not a
        leaderboard), updates (one at a time, a failure keeps the boards, a 429, a stop,
        the 304, new boards replace the old), the User-Agent, and the command for each
        source, all of them, a failure in the middle and a stop.
      - `TODO(verify)`: whether Chess.com's entries carry `title`; the JSON fixtures follow
        the docs' examples until real answers are recorded (16.4).
- [x] **16.3** The Rankings tab and its Update button.
      _Done:_
      - **Routes** at `/api/ext/rankings`: `GET /status` (each source's list, when it was
        downloaded and checked, the last failure, whether FIDE's list is from an earlier
        month, and a running update's id, so a reload follows it); `GET /fide?speed=&list=&fed=`
        (the world's top 100 or a federation's top 50 from the latest list, the
        federations for the filter, and each player's FIDE page); `GET /lichess?board=` and
        `GET /chesscom?board=` (each board, with the site's own recent change and each
        player's profile); `POST /update {source}` (202 with a job id; 409 while one runs;
        `same_origin`); `GET /update/{id}` (status, percent, what it's doing, one outcome per
        source, the daily backup's note). Every route but `POST /update` only reads
        rankings.db (a test checks).
      - **`jobs.py`:** one update at a time in a background thread, through the same
        `update.one` as the command, with the daily backup first. Stopping `serve` stops it
        between steps (a wait after a 429 within a second): the source being updated keeps
        its lists.
      - **The tab** (`web/view.js`, `view.css`): FIDE / Lichess / Chess.com sub-tabs
        (`#rankings/fide`, `#rankings/lichess`, `#rankings/chesscom`, links with
        `aria-current`); filters kept in the address (`?speed=blitz&list=women&fed=NOR`); a
        table with the rank, the title, the player (a link to their profile, in a new
        tab), federation, rating, games and birth year; a credit
        line naming the source and the month. The source line says when it was downloaded,
        "A newer FIDE list is usually out after the 1st" in amber, and the last failure in
        red. **Update** names the source ("Update FIDE"), disables while it runs ("Updating…"),
        shows what it's doing and a progress bar (`aria-live`), then each source's outcome
        and redraws the list.
      - Profile links come from the API, so the page loads nothing from anywhere else (the
        page checks); the table scrolls inside its panel on a narrow screen.
      - **Tests** (31 more): status, each list and its filters (only the latest list, a
        federation, Women, Juniors, Girls, bad values are a 422), both boards, the Update
        button (all, one source, a failure, another site's Origin, a bad body, one at a time,
        an unknown job, a stop, progress), the tab and its files (`webcheck`), and that only
        `POST /update` changes anything.
- [x] **16.4** One real update, recorded answers, docs.
      _Done:_
      - **A real `blunderbook rankings update`** on a scratch config and data folder (no
        `[chesscom] contact`) on 2026-11-12: FIDE November 2026 (standard 19,044 players
        kept, rapid 17,512, blitz 15,980; Carlsen first at 2823, Hou Yifan first of the
        women), 5 Lichess and 4 Chess.com boards, in 91 s. Run again: "already up to date"
        for FIDE (304) and Chess.com, 3.2 s. rankings.db is 5.2 MB (a backup 4.5 MB), and
        stays that size: only the latest list is kept.
      - **What it showed:**
        - FIDE's zip member has **no month in its name** (`blitz_rating_list.xml`, 90.7 MB
          of XML), so the month comes from the file's Last-Modified date (November's lists
          were dated 11 Nov). A file dated from the 25th on counts as the next month's list
          (`update.list_month`); `TODO(verify)` over a few months.
        - The XML's element names, titles (`GM`, `WGM` in `w_title`) and flags (`w`, `i`) are
          as described.
        - Chess.com's entries carry `title`, and `trend_score` (`{"direction", "delta"}`),
          now kept as the board's change, like Lichess's `progress`.
        - Lichess sends no ETag.
        - `rankings status` took 47 s on real data: the count of players kept ran a subquery
          per row. Now one grouped query, instantly.
        - At 390 px the table's screen-reader labels (absolute) widened the whole page; the
          table's panel now contains them.
      - **Recorded answers** in `tests/fixtures/`: five well-known players' records from
        FIDE's blitz list (`fide_blitz_recorded.xml`), Lichess's top 3 in blitz, and
        Chess.com's boards (two entries each, trimmed to the fields read). The
        `TODO(verify)` markers they settle are gone.
      - **Checked in headless Chrome** through `serve` on the real data: each sub-tab and
        its filters (the women's list, Bangladesh's blitz top 50, the rapid juniors), the
        links, the Update button (FIDE "already up to date", Chess.com updated), 390 px (the
        page 390 px wide, the table scrolling inside), the API under 40 ms a request, no
        console errors. `backup` takes `rankings-….db` and `restore` puts it back.
      - **Docs:** README (the tab, the button), the extension's README, CLAUDE.md.

### M17 Profile (extension)

Your ratings on Lichess and Chess.com in a Profile tab: the official numbers, fetched when
you ask and kept in `profile.db`, and your rating over time from the games you synced, next
to your blunders per game. Done before M15, which will bundle it with the other three.

- [x] **17.1** Host: ratings from the site adapters.
      _Done:_
      - **The docs were checked first** (§8, 2026-11-16) and noted at the top of each
        adapter: Lichess `GET /api/user/{username}` (`perfs`) and
        `GET /api/user/{username}/perf/{perf}` (`stat.highest`, `stat.count`); Chess.com
        `GET /pub/player/{username}/stats` (`last`, `best`, `record`, `tactics`).
      - **Core:** `Rating`, `SiteRatings` and `RATING_KINDS` in `core/models.py` (bullet,
        blitz, rapid, classical, daily, puzzle; what a site doesn't give is `None`).
      - **Adapters:** `LichessAdapter.fetch_ratings()` (one request, then one per kind you
        have games in; no token sent, since it's public data) and
        `ChesscomAdapter.fetch_ratings()` (one request, with the contact `User-Agent`).
        A 429 is a message and never a wait. `sources.ratings_for(name, cfg)`.
      - **Host API** (additions: `HOST_API` stays 1): `accounts()`, `fetch_ratings(site)`
        and `Log.games()`.
      - **Tests** (30 more): every field read from hand-built answers, a kind never played,
        a provisional rating, a closed account, odd values, plain messages for 404 / 429 /
        5xx / unreadable answers / no connection, no `Authorization` header, the contact in
        Chess.com's `User-Agent`, the host functions and the redacted token.
      - **Not checked:** a real answer from either site. The fixtures are hand-built from
        the docs (`TODO(verify)`): Chess.com's `chess_rapid` / `chess_bullet` names and its
        `date` as Unix seconds, and whether Lichess lists a kind you never played.
- [x] **17.2** The package, profile.db, your rating from your games, and two commands.
      _Done:_
      - **The package** (`extensions/profile`, a workspace member, no dependency of its own):
        `history.py` (pure, mypy-strict), `store.py` (all its SQL) and the commands. It has
        no HTTP: `host.fetch_ratings` asks, so `ext.boundary_problems` stays empty without
        httpx.
      - **profile.db:** `fetches` (one per site per local day) and `ratings` (one per kind
        of play, every field the site gave). Asking twice on one day keeps the later answer,
        so "since" always compares two different days, and the file grows by a few rows a
        day at most. It keeps the usual number of backups: unlike the Rankings' lists, an
        old answer can't be downloaded again.
      - **Changed from the plan:** the plan kept every refresh. One per day is kept
        instead: two refreshes a minute apart would otherwise make "since last time" say
        +0.
      - **"Since"** compares with the newest earlier day's answer for the same account
        (ignoring case). After the username changes, nothing is compared.
      - **Your rating from your games** (`history.py`): Lichess and Chess.com games with
        your rating, a date and a time control; your side's rating; by site and speed, month
        by month (the month's last game, games, blunders), and the newest game of each.
      - **`blunderbook profile refresh [lichess|chesscom|all]`:** the daily backup, then
        each site with a username, one after the other. A site that fails says why, keeps
        the ratings you had, and doesn't stop the other; the command then exits 1. No
        username at all is a message naming the config.toml keys, and nothing is created.
      - **`blunderbook profile show`:** what was fetched last and, under it, "From your
        games". It asks no site.
      - **Tests** (36): the history (your side, games left out, months, order), the store
        (round trip of every field, the same day, the day before, another account, sites
        apart), the commands with `host.fetch_ratings` faked (both sites, one, none, a
        failure, the change line, the backup, a broken config, through `blunderbook`), and
        the host-API boundary.
      - **Docs:** README (Extensions, the command reference, Privacy), the extension's
        README, CLAUDE.md §4 and §15.
      - **Not checked:** a real refresh. It's yours to run once: development never calls
        the sites (CLAUDE.md §14).
- [x] **17.3** The Profile tab and its Refresh ratings button.
      _Done:_
      - **Routes** (`routes.py`, at `/api/ext/profile`): `GET` gives each site's username
        (from config.toml), what was fetched last (each rating with its label and its change
        since the fetch before) and your rating in your newest game of each speed. It asks
        no site. `POST /refresh` (`host.same_origin`, `{site}`: all, lichess or chesscom)
        takes the daily backup, asks each site with a username, keeps the answers and sends
        the same shape back, with a `problem` on a site that couldn't be asked.
      - **Not a background job**, unlike the Rankings' update: a refresh is at most seven
        small requests with a 15 s timeout each, so the route answers when it's done. One at
        a time: a second is a 409. No username is a 409 naming the config.toml key.
      - **The tab** (`web/view.js`, `view.css`): a bar that says the sites are asked only
        when you press Refresh ratings, the button (disabled with no username, "Refreshing…"
        while it runs, an `aria-live` line for the outcome), and a panel per site: time
        control, rating (`?` in amber while provisional, the change in green or red), best
        with its date, won / lost / drawn. A site not fetched yet shows "From your games",
        each rating linked to its game; one with no username says which key to set.
      - **Tests** (18 more): the answer before and after a refresh, one site, the change,
        a failing site, no username, another website's `Origin` (403), a bad body, one
        refresh at a time, the backup, a broken config (503), the page checks
        (`webcheck.problems(..., prefix="profile")`), that only the refresh isn't a GET, and
        that view.js reads only fields the schemas have.
      - **Checked in Chrome** against a scratch config and databases with the sites faked
        (no request left the computer): the tab with ratings kept, Refresh (the button
        "Refreshing…", then "+12" in green, "−15" in red and "changes since 9 Nov"), one
        site failing (its reason in red on its panel, the other updated), nothing fetched
        yet with "From your games", no Chess.com username. No console errors. At 390 px
        (headless Chrome): the page 390 px wide, both tables inside their panels, the best
        rating's date hidden.
      - **Not checked:** a press of the real button against the real sites, and a touch
        screen (`TODO(verify)`).
- [x] **17.4** Rating over time, from your games.
      _Done:_
      - **The data** (`history.charts`, pure): for each speed you have games in, every month
        from your first game to your last (the months you didn't play too, so time runs
        evenly), each with your rating in each site's last game of the month, the games on
        both sites and their blunders. `GET /api/ext/profile` sends it as `history`.
      - **The chart** (`web/chart.js`): two plots over the same months, each with its own
        scale and never one on top of the other: ratings as 2 px lines with a dot per month
        and the last value beside each line's end, and blunders per game as thin red bars
        from one baseline. A picker chooses the time control (the one with the most games
        first). A legend names the lines, and "The numbers" has every month as a table.
      - **Reading a month:** point at it, or focus the chart and press ← → Home End
        (Escape to leave): a hairline through the month, and its ratings, blunders per game
        and games beside it. Built with DOM calls and `textContent`.
      - **Drawn at the panel's real width**, and again when that changes, not scaled from a
        fixed size: lines stay 2 px and the text stays 11 px on a phone. Under 14 px a month,
        only each line's last dot is drawn; month labels thin out to what fits.
      - **Colours:** Lichess is the page's ink, solid; Chess.com its blue, dashed; the bars
        are red, which is "your blunders" everywhere on the page. See Decided.
      - **Tests** (4 more): the months side by side with gaps and across a new year,
        `history` in the API and after a refresh, the fields chart.js reads, and that the
        month readout never uses `innerHTML`. The page checks cover chart.js too.
      - **Checked in Chrome** against scratch data (a year of made-up games; the sites
        faked): the chart at 1200 px and at 390 px (the page 390 px wide, twelve months
        fitting), pointing at a month with the real pointer, the readout flipping to the
        left near the right edge, ← → Home End and Escape, the picker (focus stays on the
        button), a time control with one site only, "The numbers", and no games at all. No
        console errors.
      - **Not checked:** your real games, a touch screen, and several years of months at
        390 px (`TODO(verify)`).
      - **Docs:** README, the extension's README, CLAUDE.md §4.

**Later (not v1):** a side picker for web imports, FEN board editor in the browser, settings
page, more AI helpers (reflection questions, cause suggestions from your notes, a monthly
digest), Anki / Lichess-study export, mobile PWA.

---

### M18 Game commentary in the Collection (planned, not started)

Planned on 2026-11-18. The Collection's game page has a board, an eval graph, the moves
with marks and one box for the move shown. M18 makes it read like an annotated game: for
each move, what it did, why it was played and what followed, as one commentary. See
Decided for the answers it's built on.

- **What a note says.** _What_ (python-chess): captures and recaptures, castling,
  development, pawn advances, checks, promotions, queen trades, pieces newly attacked.
  _Why_ (Stockfish): "Stockfish's choice", "one of its top three" or "Stockfish preferred
  …"; the threat the move creates and the threat it stops. _What followed_: the position
  in words ("level", "White is better", "Black is winning"), how it changed, and for a
  mistake the line that punishes it, with its captures.
- **Weighted.** Every move gets one line. Key moments get a paragraph and a small board:
  every marked move, turning points (White's winning chances cross a band: lost, worse,
  level, better, winning), only moves (Stockfish's top move far ahead of its second) and
  the last move. A summary opens the game (result, who was better when, the decisive
  moment, each side's accuracy) and each phase (opening, middlegame, endgame).
- [ ] **18.1** Shared facts, and AI for extensions (core).
      - `core/facts.py` (pure, mypy strict): the move and line facts moved out of
        `core/explain.py` (reading a line, captures, move notes, line facts, pieces left
        attacked, the game ending, `eval_words`), with the owner's wording as a parameter:
        "your / their" for the Log, "White's / Black's" for anyone's game. The Log's
        prompt stays byte-for-byte the same (a test).
      - `ai.explain` gains `max_tokens` (default stays 1000).
      - `host.ai_status()` (`enabled`, `model`; never the key) and
        `host.ask_ai(system, user, *, max_tokens)` (text and model; `HostError` with a
        plain, redacted message). Additions, so `HOST_API` stays 1. A network call only on
        a button press.
      - CLAUDE.md §1.3, §7.10, §15 (`facts` joins the core modules an extension may use).
- [ ] **18.2** The deeper analysis, once per game, when you first open its commentary.
      - `migrations/0002_commentary.sql`: `studies` (engine, depth, when), `threats` (per
        position, the best move for the side not to move, from the position with the turn
        passed; none when that side is in check) and `alternatives` (MultiPV 3 at the key
        moments).
      - `study.py`, a job like `jobs.py`: one at a time, its own connection and Stockfish,
        progress as positions done / total, stops between positions when `serve` stops,
        nothing saved for a game that stops halfway. The game's own depth.
      - `POST /games/{id}/study` (`same_origin`; 409 while one runs), `GET /study/{job_id}`,
        and `blunderbook collection study GAME_ID`.
      - `TODO(verify)`: Stockfish with a turn-passed FEN (en passant cleared); the time per
        game at depth 16.
- [ ] **18.3** The built-in commentary and the page.
      - `commentary.py` (pure, mypy strict): positions, study and `stats.moves()` in, a
        summary, the phases and a note per move (key or quiet; what, why, what followed;
        its line) out.
      - `GET /games/{id}/commentary`: that, the PGN's own comments and variations (read
        from the stored PGN), and the saved AI prose. No study yet: the page offers "Study
        this game" with a progress bar.
      - The page: a "Moves | Commentary" switch. Commentary reads like a book: the summary,
        a heading and summary per phase, one line per quiet move, a block with a small
        board per key moment, the PGN's comment in muted italics marked "From the PGN";
        every move a button that shows it on the board. Under the board while stepping:
        that move's note (the AI prose when saved, the facts in a "Facts" details).
      - `blunderbook collection commentary GAME_ID` prints it.
- [ ] **18.4** AI prose, one request per game.
      - `prompt.py` (pure): the system prompt (only the facts given, no new moves or
        variations, "White" and "Black", plain prose, no markdown, no exclamation marks,
        one line per quiet move, a short paragraph per key moment) and the user message:
        the moves, the notes and lines, evals in words, the opening and ECO.
        `PROMPT_VERSION`.
      - **Never sent:** player names, ratings, dates, event, site, the PGN, the
        annotator's comments.
      - The answer is asked for as JSON keyed by move (`"18b"`), with the summary and the
        phases. Unknown keys are dropped, a missing move keeps its built-in note, markdown
        is stripped; an answer that can't be read is a 502 and nothing is saved.
        `TODO(verify)`: JSON mode for each model.
      - Saved in `prose` (text, model, prompt version, when). `POST
        /games/{id}/commentary/ai` (`same_origin`; 503 with the reason when AI is off; 502
        on an OpenRouter problem) and `GET …/commentary/ai/prompt` (exactly what's sent).
      - The page: "Write the commentary", the prose marked "AI commentary · auto",
        "Written by {model} on {date}, from Stockfish's lines. It can be wrong", "Write
        again", and "What's sent". An output limit of about 4000 tokens: a very long game
        sends only its key moments in full, and the page says so.
- [ ] **18.5** Annotated PGN, and docs.
      - `GET /games/{id}/annotated.pgn` and a "Download annotated PGN" link: the headers
        plus `Annotator`, the marks as NAGs (`??` `?` `?!`), each note as a `{comment}`
        (the AI prose when saved), the PGN's own comments kept before it, Stockfish's best
        line at a mistake as a variation. Built with python-chess; nothing is sent.
      - README, `extensions/collection/README.md`, CLAUDE.md §4 and §15.
- **Tests:** each fact in both wordings, the Log's prompt unchanged; `ask_ai` against
  `MockTransport` (off, no key, 401, 429, a timeout, never the key); the study job with a
  stub engine, and one engine test (`scholars_mate`: after 3. Qh5 the threat is Qxf7#);
  the key-moment rules and the wording; nothing private in the prompt; parsing the
  answer; 403 / 409 / 503 / 502; the annotated PGN read again by python-chess with every
  move; the page and boundary checks.
- **By hand:** a classic annotated game, studied, read, stepped through and downloaded,
  with the AI answer faked; 390 px, the keyboard, no console errors. Left for you: one real
  "Write the commentary" with your key and model.

### M19 Journal (extension)

Planned on 2026-11-19. It's first in the order of work. A minimal, very fast chess
journal, kept like a blog for yourself. You write in Markdown. In Reading mode, every PGN,
FEN and move in a sentence plays on a board beside the text. It's an extension
(`journal`): its own `journal.db`, in every backup, with your Log read-only and no network.
A prototype (a design canvas with working Reading and Writing screens) was made before any
code; its feedback is folded in here before 19.1. See Decided for the answers it's built on.

**The note format.** Plain Markdown, stored as typed:
- ```` ```pgn ```` blocks: a game with variations and `{comments}`;
- ```` ```fen ```` blocks: a diagram;
- moves inside a sentence ("after 5. cxd5 exd5 6. Nxd5??");
- `#tags`;
- `[[log 12]]` / `[[game 40]]`: links to your Log entries and games.

**How each part plays:**
- **A run of moves in a sentence:** it starts with a numbered move ("5. cxd5",
  "6...Nxd5"). It plays from the nearest block or run above it that reaches that move, in
  the main line or a variation, where the whole run is legal. With none above, it plays
  from the nearest block below, so you can write about a game before pasting it (as the
  prototype's note does). A run from 1. with neither plays from the start. Where it follows
  the block's moves it shares them, so the board's ← → go on in that game. A run that can't
  be played stays plain text.
- **Arrows and highlights:** Lichess's `[%cal …]` / `[%csl …]`, in a PGN comment or under a
  FEN.
- **Log links:** each shows the entry's or game's position and links to it. Library lines
  can't be linked: extensions don't read each other. Inside a sentence a link is inline
  text; on a line of its own it's a "From your Log" card (the move, opponent, time control,
  date and re-test status, with "Open →").

**Python only, no frontend chess.** On save, the server (python-chess) parses the note once
into a document tree:
- the blocks;
- the inline spans;
- for every playable move, its FEN, SAN and place in the variation tree.

The tree is stored beside the text, so Reading mode is one read. The page builds it with DOM
calls and `esc()`. Each block's parse is cached by its text, so switching modes on a heavy
note re-reads only the blocks you changed.

Measured on 2026-11-19:

| What | Time |
|---|---|
| A warm local request | 1–3 ms |
| Checking one move | 0.02 ms |
| A 131-ply game read with a FEN per move | 3.8 ms |
| Ten such games, uncached | about 40 ms |

Rejected: a vendored chess.js (a second set of chess rules), Rust/WASM (a toolchain and
build step), and CodeMirror (a bundle built outside the app).

**Fast:**
- Writing is a plain monospace `<textarea>`: nothing is redrawn as you type.
- Autosave runs 400 ms after a pause, one save at a time, like the Log's notes.
- Search uses SQLite FTS5 over the title, the text and the PGN headers. Checked in 19.1:
  uv's Python has SQLite 3.53.1 with FTS5, so no `LIKE` fallback is needed.
- Reading is a book serif at about 18 px and 68 characters a line, with system fonts only.

**Boards:**
- One reading board is pinned beside the text. Under 860 px it sits above the text, smaller.
- It's built with `/js/board.js` and `/js/steps.js`. ← → follow the line you're in, a
  variation included.
- Insert-from-board and "Continue here" check each move with `POST /board`.

**Keyboard:**
- Ctrl/Cmd+K: the quick switcher.
- Ctrl/Cmd+E: switch between Writing and Reading.
- Ctrl/Cmd+B / Ctrl/Cmd+I: bold / italic.
- Esc: back to the list.
- `n` in the list: a new note. Browsers keep Ctrl+N.

- [x] **19.1** The package and storage.
      - `extensions/journal/`: the entry point and `Extension(name="journal",
        title="Journal")`.
      - `migrations/0001_journal.sql`:
        - `notes`: the title from the first line, the text, pinned, the parsed tree and
          its version, created, updated;
        - `tags`;
        - `versions`: a snapshot when the last one is over 5 minutes old; the newest 30
          kept;
        - an FTS5 table.
      - `store.py` holds all its SQL.
      - CLI: `journal new`, `journal list`, `journal show ID`, `journal export FOLDER`.
      - The root `pyproject.toml` and `uv.lock`.
      - **As built:**
        - `notes.py` (pure, mypy strict) reads the title, the list's snippet, the tags and
          the PGN headers to search on every save. The parser (19.2) isn't needed for them.
        - A tag is `#` and a letter after a space or the line's start, outside ```` ``` ````
          blocks and `inline code`. So `Qxf7#`, `# Heading` and `#1` aren't tags.
        - A version is the text a save replaces, with the time it was written. Pinning
          isn't an edit.
        - Search matches every word, also as the start of a longer word, ignoring accents.
          The best matches come first, after the pinned notes.
        - The export writes `ID-title.md`. Exporting again replaces those files only.
        - `journal.db` is in `backup` and `restore`, a test each.
- [x] **19.2** The note parser (`doc.py`, `moves.py`; pure, mypy strict).
      - It reads:
        - the Markdown subset;
        - PGN blocks with their variation tree, comments and arrows;
        - FEN blocks;
        - moves inside sentences, with where they play from;
        - tags;
        - `[[log N]]` / `[[game N]]`.
      - The heaviest tests are here:
        - every kind of block;
        - a broken PGN, shown as code with the reason;
        - an illegal run in a sentence, left as text;
        - variations within variations;
        - Unicode;
        - a note with no chess at all.
      - **As built:**
        - `moves.py`, not `chess.py`: inside the package, that name reads like
          python-chess.
        - Runs look below too, when nothing above reaches them (see "How each part
          plays").
        - The tree is stored with the note on every save, with `DOC_VERSION`.
          `store.document` makes it again when the parser's version changes.
        - Headers written on one line (`[White "?"] [Black "?"]`) are read.
        - A variation written inside another, `(1. d4 (1. c4))`, is a second alternative
          to the same move, as PGN means it.
        - Links are kept only for `http(s):`, `mailto:` and `#`. Any other link stays
          text.
        - Timing on a note with ten 130-ply games and 6,000 words: 72 ms the first time,
          7 ms after an edit (the games' reading is cached).
- [x] **19.3** The tab: the list, Writing and Reading.
      - Routes:
        - `GET /notes?q=&tag=`;
        - `POST /notes`;
        - `GET /notes/{id}`;
        - `PATCH /notes/{id}` (text, pinned), which answers with the parsed tree;
        - `DELETE /notes/{id}`, asked in the page first.
      - `same_origin` on every route that changes something.
      - `web/view.js` and `view.css` (`journal-*` classes plus the shared ones):
        - the list, with "New note" at its top, then search, tags and pins;
        - Writing mode: the save line, a pasted PGN or FEN wrapped in its own block, the
          shortcuts;
        - Reading mode: the serif text, the pinned board, variations indented;
        - the quick switcher.
      - **As built:**
        - The page is `view.js` (the list, the bar over a note, the switcher, the keys),
          `read.js` and `write.js`. Reading builds the note with DOM calls only.
        - Routes at `/api/ext/journal/notes`. A note's answer has its tree and `refs`:
          each Log link once, as your Log has it now (`found: false` when it's gone; a
          FEN entry's game isn't a game). A game link carries its moves, read again from
          its PGN.
        - A new note (`#journal/new`) is made by its first save, so leaving it empty
          makes nothing. A save that fails keeps you in Writing with your text.
        - A paste gets its own block when it has PGN headers, or when it's a FEN or three
          or more numbered moves on a line of their own. Moves pasted into a sentence stay
          in it.
        - The board shows a Log entry's position before your move, with your move in red
          and not the best move, so the Journal doesn't give the re-test away.
        - Lichess's blue and yellow arrows: `/js/board.js` gained `blue` and `amber`.
        - Titles and snippets in the list are plain text: `**`, `_`, `` ` `` and links
          are taken off (`notes.plain`).
        - Three columns from 1180 px; under it an open note hides the list ("← All
          notes"); under 860 px one column, with the board above the text when reading.
- [x] **19.4** Boards that write.
      - `POST /board`: a FEN and moves in; the position, the SAN and the legal moves out.
      - The insert-from-board panel in Writing mode.
      - On the reading board:
        - Copy FEN;
        - Copy PGN up to here;
        - Continue here: play on, then copy it or insert it as a variation.
      - `POST /analyse`: `host.engine()`, one at a time, the depth from settings, only when
        you press Analyse.
      - **As built:**
        - `web/play.js` is the board you play on, shared by Writing and Reading: tap a
          piece, then a square; the server checks each move. A pawn on the last rank
          becomes a queen, as in Re-test.
        - `POST /board` changes nothing but is `same_origin` like every route that isn't
          a GET; at most 600 moves.
        - Insert as a variation: `POST /notes/{id}/lines` with the PGN block, the move
          the line goes on from (or its start) and the moves. The server writes the line
          into that block's PGN (python-chess's exporter, `??` and `!` kept as typed,
          headers kept as written) and saves the note like an edit, so the text before
          is a version. It follows the game's own moves where the line agrees with them,
          and a line from the game's last move continues the game. A line the game has
          already is a 409, and nothing changes. Offered only when the board shows a
          move written in a PGN block, or a block's start.
        - Analyse: `POST /analyse`, three lines at your `engine_depth`, a green arrow for
          the best move, kept while that position is shown. One at a time (a 409 says
          Stockfish is busy); no Stockfish is a 503 with the reason. A finished game
          isn't sent to the engine.
        - Insert from a board starts from the usual position, a diagram in the note or
          the end of one of its games (as last saved). It inserts the moves at the
          cursor, a ```pgn block, or the position as a ```fen block.
        - `.btn.primary:disabled` in app.css keeps its label readable: a disabled
          primary button (Import's "Importing…" too) showed white on white.
- [x] **19.5** History, export and docs.
      - History: the snapshots, a preview, and bring one back (the current text is kept as
        a snapshot first).
      - Export: `.md` files, with PGN and FEN blocks as written and tags kept. A folder from
        the CLI, or a `.zip` from the page.
      - Docs: README, `extensions/journal/README.md`, CLAUDE.md §4 and §15 (the fifth
        extension).
      - **As built:**
        - History is a third mode, `#journal/12/history`, beside Write and Read (Ctrl/Cmd+E
          goes to Read). The versions are listed without their text; a version's text is
          asked for when you pick it, and shown as written. A version with the same text
          as now says so and can't be brought back.
        - `POST /notes/{id}/versions/{vid}/restore` (`same_origin`) always keeps the text
          it replaces as a version, even under 5 minutes, then keeps the newest 30. It
          answers with the note, and the page opens it in Read.
        - Export: `GET /export` is `journal-YYYY-MM-DD.zip`, one `.md` per note named
          `ID-title.md`, the bytes as typed, each file's time the note's last edit.
          `archive.py` names the files for the CLI and the page alike. The link under the
          list is hidden while there are no notes.
- **Tests:**
  - the parser, as in 19.2;
  - the routes with a temp `journal.db`: create, read, update, delete, search and tags, a
    403 for another `Origin`, and a `[[log N]]` that no longer exists ("entry not found");
  - when snapshots are taken, and that only 30 are kept;
  - export gives back the text as written;
  - `/board` legality, and `/analyse` with a stub engine;
  - `webcheck.problems` and `ext.boundary_problems`.

  No test touches the network.
- **By hand, in Chrome against scratch data:**
  - a long note: autosave, switching modes, smooth typing at 5,000 words;
  - a pasted Lichess PGN, played through its variations with ← →;
  - a move in a sentence, clicked;
  - a FEN with arrows;
  - insert from the board, Continue here, Analyse;
  - search, tags, pins, the quick switcher, a history restore, an export;
  - 390 px, the keyboard only, no console errors.

### M20 Cost, not count (planned, not started)

Planned on 2026-11-20 from an idea you picked earlier ("Cost, not count", recommended). It
comes after M21's stages 1 to 3 (21.2 to 21.4), so its costs add up checked swings, and
21.9 follows it. Patterns counts blunders per cause. Each entry already
stores its swing: the share of the game's result it cost you (0..1, §2). So adding the
swings up gives what each cause cost, in game points. "Points per 10 games" puts every
cause on the same scale, so a rare but expensive cause stands out.

- [ ] **20.1** The sums (`core/patterns.py`, pure).
      - Cost per cause: confirmed, plus suggested for entries with no confirmed cause,
        kept apart as today.
      - Cost per time control and per opening (ECO and name).
      - The games behind each figure, so a cost can be shown per 10 games.
      - The biggest leak by cost, next to the one by count.
      - Missed wins count with their own swing, which is small by design.
      - Blunders per 10 games by month and by speed, from every game you imported (clean
        ones are saved too): the number that says whether you're improving. Added from
        the 2026-11-21 core review (M21).
      - Tests with hand-made entries.
- [ ] **20.2** The page.
      - A "Count | Cost" switch on the Patterns view. The bars stay solid for confirmed and
        striped for suggested.
      - A top-openings list by cost.
      - The insight line names the most expensive cause when it isn't the most common one.
      - The links to the Log keep working.
      - `/api/patterns` fields, the schemas, `tests/test_web.py`, README, CLAUDE.md §7.9
        and §11.
- **To settle when it starts:** what "games" means for a cost per 10 games, either every
  game you imported or only the games of that speed or opening. Also, whether FEN entries
  (no game) count.

### M21 Solid core (planned, not started)

Planned on 2026-11-21 from a review of the core (`core/detect.py`, `core/engine.py`,
`core/hints.py`, `core/retest.py`, `core/patterns.py`, `importer.py`), asked for before
the desktop app. The core works and is well tested. The gaps are about trust (is each
entry a real mistake?), data the engine works out and the import throws away, and the
prevention loop (re-test and suggested causes).

Most slices change a product rule. Each one marked **§ change** says the rule it proposes;
nothing changes until you accept it, and then CLAUDE.md changes in the same commit.

The slices run in the Order of work at the top, not by number: stages 1 to 3 (21.2, 21.1,
21.10, 21.3, 21.6, 21.5, 21.4) before M20, then 21.9, 21.7 and 21.8.

- [x] **21.1** Keep the evals (§5 change, accepted 2026-11-21).
      - `engine.analyse_game` scores every position (`GameAnalysis.evals`), and
        `importer.new_game` drops them. Migration `0004`: a `positions` table,
        `(game_id, ply, eval, best_uci)`, primary key `(game_id, ply)`, `ON DELETE
        CASCADE`, N + 1 rows per game: the Collection's shape (`eval` in `eval_before`'s
        form, White POV; `best_uci` NULL when the game is over). The best move is kept so
        a move can be re-judged without Stockfish.
      - `games.engine_threads` and `games.engine_hash_mb`, next to `engine_name` and
        `engine_depth`. Imports keep the configured threads, so the same game can still
        give slightly different entries elsewhere (Stockfish isn't deterministic with
        more than one thread); now you can see why.
      - Games saved before 0004 have no positions until `reanalyse` (21.4).
      - `move_accuracy`, `game_accuracy` and `phase` move from the Collection's
        `stats.py` to `core/detect.py`, and the Collection imports them from there.
        `core/detect.py` is already open to extensions, so §15 doesn't change. The
        Collection's `phase` counts moves 1 to 10 as the opening, while 21.5's "Opening
        gap" says move 12: settle one number at 21.5.
      - Unlocks without Stockfish: your accuracy and mistakes per game, an eval graph on
        the game page, re-judging after a threshold change, and 21.9.
      - _Done when_ an imported fixture has N + 1 positions, a FEN entry has 2, and an old
        database migrates with none.
      - Done 2026-11-21: `0004_positions.sql`; `repo.add_game(positions=…)` saves them in
        the game's transaction and `repo.game_positions()` reads them back.
        `GameAnalysis` carries each position's best move and the engine's Threads and Hash
        as applied (`Engine.threads` / `Engine.hash_mb`; None from a stand-in engine), and
        `GameAnalysis.positions` lists them. The helpers are in `core/detect.py`, with
        their tests in `tests/test_detect.py`; `Phase` is in `core/models.py`. CLAUDE.md §5
        and §7.6 and the README say what's saved. Nothing reads the positions yet: 21.3,
        21.4, 21.9 and M18 will.
- [x] **21.2** A clean-game fixture.
      - `tests/fixtures/pgn/` only checks that blunders are found. Add a short quiet game
        where nothing may be flagged at depth 12, so a false entry fails a test.
      - Done 2026-11-21: `clean_berlin.pgn`, a quiet Berlin endgame (17 moves, a draw).
        `test_a_clean_game_logs_nothing` analyses it as each side and flags nothing, even
        from the inaccuracy line. When chosen, no move's swing passed 0.02 for either side
        (depth 12 with one thread, and depth 16 with two; Stockfish 19), so it doesn't sit
        near a line. It found no false entries in today's rules. CLAUDE.md §12 lists it.
- [ ] **21.3** Check each flag with the move you played (§7.6 change).
      - Today a move is flagged from two separate searches, before and after it. At depth
        16 that's noisy, and it makes false missed wins: "mate in 7" before, "+12" after,
        because the mate moved past the engine's horizon.
      - **Proposed rule:** pass 2 also searches the played move alone from the position
        before it (`root_moves=[played]`, same depth). The flag is dropped when that score
        is within `accept_margin_cp` of the top line, or, for a missed win, when it still
        mates. One extra search per flagged move.
      - The §12 fixtures still flag their move; 21.2's flags nothing.
- [ ] **21.4** `blunderbook reanalyse [--depth N] [--game ID]` (§9 change).
      - Games imported before missed wins were never re-analysed, and the desktop app will
        ship a newer Stockfish.
      - **Proposed rule:** run both passes again and save the new evals. An entry at the
        same ply keeps your notes, causes and attempts and gets the new engine facts. A new
        flag becomes a new entry. An entry that's no longer flagged stays, marked "not
        flagged by the last analysis", so nothing you wrote is lost. A `-pre-reanalyse`
        backup first, like restore.
      - **To settle when it starts:** whether a still-flagged entry keeps its old
        `accept_uci` or gets the new one.
- [ ] **21.5** More suggested causes (§7.7 change). Today 5 of the 11 are ever suggested.
      - **Missed their threat vs Hung a piece:** if the refutation's first move was already
        a winning capture before your move (the same position with the opponent to move),
        the threat was there and you missed it. If your move made it possible, you hung a
        piece. Today only a mate counts as a missed threat.
      - **Opening gap:** move 12 or earlier.
      - **Endgame technique:** few pieces left (`phase`, from 21.1).
      - **Miscalculated a line:** a long think, 10% of the base time or more, that still
        ended in the mistake.
      - **Overconfident / tilt:** you were 3 pawns or more ahead before the move.
      - All pure, in `core/hints.py`, from data an entry already has. "Wrong plan",
        "Skipped blunder check" and "Other" stay yours.
      - **To settle when it starts:** the exact lines (move 12, 10%, 3 pawns).
- [ ] **21.6** Fairer re-test answers (§7.6 change).
      - `detect.accepted_moves` accepts moves within 60 cp of the best. At +9, a move
        that keeps +7 is refused; at 0.00, 60 cp is generous.
      - **Proposed rule:** accept a MultiPV move whose swing against the top line is under
        the inaccuracy line, the same maths as the blunders. MultiPV 5 instead of 3.
        `accept_margin_cp` goes.
- [ ] **21.7** Re-test scheduling (§7.8 and §6 change).
      - **Proposed rules:** solved with the hint keeps the streak and comes back
        tomorrow (today the hint is recorded and ignored). At most `retest.new_per_day`
        new entries (default 10) join the queue each day, oldest game first, so a big
        sync doesn't put 40 positions in one day.
- [ ] **21.8** The same position again (§7.8 and §11 change).
      - The same opening mistake in three games is three entries and three re-tests.
      - **Proposed rule:** entries whose position matches (FEN without the move counters)
        and that you played the same move in are re-tested once, and the Log says "You
        went wrong here 3 times" with links to the games.
- [ ] **21.9** When you blunder (§7.9 change).
      - Patterns by game phase, by how the game stood before the move (winning, level,
        losing, from your evals), and by clock left. Needs 21.1.
- [x] **21.10** A safety limit on the engine (§7.6 and §9 change, accepted 2026-11-21).
      - Depth is the only limit, so one stuck search (a broken binary, a rare position)
        hangs an import for good.
      - Each search gets `Limit(depth=d, time=SEARCH_LIMIT_S)`, a fixed 120 s in
        `core/engine.py` (no setting). A search that ends before reaching depth `d` was cut
        short: that's an error, never a judgment. A wedged engine is caught by
        python-chess's own timeout (the limit plus `Engine.open`'s 10 s).
      - `Engine` restarts its own process (it keeps the command, threads and hash) and
        raises `EngineTimeout`, an `EngineError`. `importer.run` reports that game as an
        error, "Stockfish took over 120 s after 23. Nf5", and goes on with the next. The
        game isn't saved, so importing again retries it. Any other `EngineError` still
        stops the import.
      - §9: the import exits 0 with a skipped game, like other per-game errors.
      - Done 2026-11-21: `SEARCH_LIMIT_S`, `EngineTimeout` (with the position it names) and
        the restart in `core/engine.py`; `importer.run` skips the game with
        `importer.timed_out()`'s line. A search is cut short only when it took the whole
        limit and reported less than the depth, so a quick search is never one. A stuck
        process is ended by a watchdog half the command timeout after the limit, while
        python-chess is still waiting: ended after python-chess's own wait, its background
        thread never finishes (1.11) and Python hangs on exit, which a test now checks.
        The fake UCI engine gained `--slow-on-go` and `--hang-on-go`. A real-Stockfish
        test checks that it honours the limit. The CLI,
        the page's import job, sync, the Collection and the Journal all use the same
        `Engine`, so they all get the limit; only an import skips and goes on.
- **Later, not in M21:** a "spot the threat" re-test for missed threats (name the
  opponent's move), and playing out the best line for tactics longer than one move.

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

- **2026-11-21: The M21 rule changes.** Each slice marked "§ change" waits for your yes or
  no on its proposed rule (21.3 to 21.9).

### Decided

- **2026-11-21: Keeping the evals, and the engine's safety limit (21.1, 21.10).**
  - **A `positions` table**, not a JSON column: the same shape as the Collection's, easy
    to query across games for 21.9, and the best move is kept for re-judging.
  - **Threads and hash recorded**, not forced to one thread: imports stay as fast, and a
    difference between two runs can be explained.
  - **A stuck search skips its game**, not the whole import: degrade gracefully (§1.4),
    and never judge from a search cut short (§1.5). Importing again retries the game.
  - **A fixed 120 s**, not a setting: depth 16 takes well under a second per position, so
    it only catches a stuck engine.

- **2026-11-21: The order of work, revised.** Asked for: a logical order once M21 was
  planned. It replaces the 2026-11-20 order (below).
  - **A safety net first:** the clean-game fixture (21.2), so every later change to
    detection is checked for false entries.
  - **The evals before what builds on them:** 21.1 feeds 21.3, 21.5, 21.9 and M18.
  - **The changes to pass 2 together:** 21.3 and 21.6 share one loop, and the engine
    safety limit (21.10) lands before the long runs.
  - **Causes before `reanalyse`:** 21.5, then 21.4, so one run applies every rule.
  - **Patterns from checked entries:** M20, then 21.9 on the same files.
  - **The re-test queue:** 21.7, then 21.8, which both change how it's built.
  - **M18 and M15 last:** M18 uses 21.1's accuracy and phase; M15's bundled Stockfish
    relies on `reanalyse`.
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
- **2026-11-11: The Collection's tab (12.3).**
  - **A player's page is the collection's page with the player filter**, not a page of its
    own: the same tiles, phases, openings and games, from their side. One layout to keep.
  - **Filters live in the address** (`#collection/1?player=…&phase=opening`), so the browser's
    Back and a bookmark keep them.
  - **The server does the maths**, as in core: the page gets each move's mark and accuracy,
    and each position's winning chances, for the graph.
  - **Missed wins** (M13) aren't in the Collection's stats yet: its marks stay `??` / `?` /
    `?!`, as decided for M13.
- **2026-11-11: Adding games on the Collection's tab, and links to your Log (12.4).**
  - **Its own import job**, not core's: core's job saves to your Log, and an extension can't
    use it (§15). The two don't share a slot, so one of each can run at once, each with its own
    Stockfish. That's two engines' threads at worst; a shared slot would need a host API
    addition, and waits until it's a problem.
  - **The same rules as core's web import** (§10): the PGN's bytes, decoded as §7.1 says, the
    same refusals, one at a time, in memory, stopped with `serve`.
  - **Your Log is matched by position**, not by game: an entry is listed when its position
    before your move (pieces, side to move, castling, en passant) is in the game, so a master
    game that reached the position you went wrong in shows it, as the Library does. Move
    numbers are ignored: the same position comes up at different moves.
- **2026-11-11: Page polish (M14).**
  - **What's in it:** fixes at the seams between views, one board with step controls, a
    review flow for going through new entries, and feedback for imports and re-test sessions.
  - **Left out, by choice:** dragging pieces in Re-test, and a dark theme. Also a side picker
    for web imports (still out of v1), Games filters in the address, a promotion picker.
  - **"Needs your notes"** means no confirmed cause or no lesson. "What I was thinking" isn't
    required: for an old game you may not remember, and the entry shouldn't nag for ever.
  - **The phone header** scrolls its tabs sideways rather than wrapping or hiding them in a
    menu: every tab stays one tap away, and extensions add more.
- **2026-11-11: Branches and releases (before M15).**
  - **One branch:** work goes on `main`, the desktop app included. It packages the same code
    (15.1 and 15.2 change what the CLI uses too), and `blunderbook update` follows `main`, so a
    CLI install and a download of the same version are the same code.
  - **Releases are tags:** `v1.0.0` marks v1, and a `v*` tag makes a release (15.5). A
    `release/N.x` branch is made from a tag only when an old version needs a fix.
  - **Every commit on `main` can be released:** the CLI keeps working after each slice
    (pywebview is an optional extra), and once CI exists a build that fails its tests or smoke
    test publishes nothing.
  - **CI is tried out on a throwaway branch** (for example `ci/desktop`), then lands on `main`
    as one commit, so `main` stays linear.
- **2026-11-12: Rankings keeps only the latest lists (M16).** Asked for after 16.4. A FIDE
  update that saves a new list deletes the one it replaces, in the same transaction, so
  rankings.db holds one list of each speed (about 5 MB, not 10) and doesn't grow: the new
  list reuses the old one's pages. The cost: no change in place or rating since last month,
  and no "new" mark (FIDE's XML has no previous rating to show instead). Lichess and
  Chess.com already kept only their latest boards. A failed update still keeps the lists you
  had.
- **2026-11-12: Rankings keeps only its newest backup.** Asked for next. An extension may
  set `ext.Extension(backups_kept=N)` (1 or more; an addition, so `HOST_API` stays 1), and
  its backups keep the smaller of N and `backup.keep`; Rankings sets 1, since its lists can
  be downloaded again (about 4.5 MB of backups, not 60). Blunderbook's own database and the
  other extensions keep `keep`. A `-pre-restore` copy isn't rotated by the restore that
  makes it, as before; the next backup of that database replaces it. (CLAUDE.md §6, §15)
- **2026-11-16: Profile (M17), an extension for your ratings.**
  - **Two sources:** the official current ratings, fetched from Lichess and Chess.com and
    kept in `profile.db`, and a history drawn from the ratings in the games you already
    synced, which needs no network.
  - **Fetched only when you ask:** a "Refresh ratings" button and `blunderbook profile
    refresh`. Never when the tab opens or on a timer. It's a new network call, listed in
    CLAUDE.md §1.
  - **The HTTP code is in the site adapters**, not the extension: `fetch_ratings()` on
    each, reached through `host.fetch_ratings`. They already hold your username, contact
    and token, and a site changing its API still breaks only its adapter. §8's "PGN text
    only" now has this one addition. (Rankings, M16, keeps its own HTTP: its lists are
    public and have nothing to do with your accounts.)
  - **No token for ratings:** Lichess's are public, so the token isn't sent.
  - **Chess.com's puzzle rating is a highest only:** its API gives your highest and lowest,
    not the current one, so it's shown as a best.
  - **Also shown:** the highest rating and the win / loss / draw record, puzzle ratings, and
    blunders per game next to the rating line.
  - **profile.db keeps one answer per site per day** (17.2), not every refresh, so "since"
    always compares two different days.
  - **The chart's colours (17.4).** Two sites need two line colours, and §11 allows accents
    only with a meaning. Lichess is ink and Chess.com is blue, dashed, so they differ by
    more than colour, with a legend and each line's last value beside it. A palette check
    (OKLab distance under simulated colour blindness) puts the pair far apart (27, where 8
    is the target), but fails ink on two counts as a series colour: it's darker than the
    band it allows and has no hue. Kept anyway, with the dash as the second cue. Blue and
    amber passed every check, but amber means "due / suggested" on this page.
  - **Not checked (17.4):** the month readout at phone width, where it can sit over the
    hairline it belongs to.
  - **Ratings and blunders are never on one scale.** They're two plots over the same
    months: a second y-axis would let the eye read a crossing that means nothing.
- **2026-11-16: Extension tabs sit in one rounded tray.** Asked for after M17: with four
  extensions on, the header was nine identical pills and nothing said which were add-ons.
  - **The tray** (`.tabgroup`, built in `addExtensions`): white with a hairline border,
    after the built-in tabs. Inside, tabs behave as before: muted, a hover tint, the open
    one a solid ink pill. Nothing new in the design language: a white panel and a hairline.
  - **No visible label.** Nine tabs already fill the row. It's `role="group"` named
    "Extensions" for a screen reader.
  - **The header doesn't grow.** Tabs inside are 6 px shorter, so the tray is as high as a
    tab (35 px). On a touch screen its tabs are 44 px like the rest and the border sits
    outside that. Measured before and after at 1200 px and 390 px, mouse and touch: the
    header ends at the same pixel.
  - **Wrapping:** it moves to the next line as one piece (seen at 800 px). The radius is a
    fixed 20 px, so two rows of its own tabs would be a rounded box, not an oval. On a
    phone it scrolls with the row.
  - **None on:** no tray. One on: a tray around one tab.
  - **Not chosen:** a "More" menu (hides tabs behind a click), or only a divider.
  - **Checked** in Chrome and at a true 390 px against scratch data: four, one and no
    extensions, the focus ring, hover, opening a tab, the tab order. Touch was emulated
    (a coarse pointer), not a real touch screen.
- **2026-11-17: Extensions page, with Add and Remove (planned in M15).** Asked for: an
  "Extensions" item in the desktop app's menu, listing its extensions, with Add and then a
  red Remove. Answers:
  - **Where:** a native menu item and a page (`#extensions`), with a link in the header's
    extensions tray, so the browser fallback reaches it too.
  - **Remove keeps the data**, like `ext disable`; adding it again brings it all back.
  - **Bundled extensions only.** Nothing is downloaded and no outside code runs.
  - **The same page under `blunderbook serve`.** One that's in the repo but not installed
    shows the `ext install` command (installing needs uv and takes a while).
  - **Applied at once, no restart** (my proposal, part of the plan you accepted): a FastAPI
    app can't cleanly gain or lose routes while running, so the server forwards to the
    current app and swaps in a fresh one. Refused while an import runs. A package installed
    from the CLI while `serve` runs still needs a restart (Python sees new packages at
    start); the desktop app never hits this.
  - **Order:** M15 is renumbered: 15.1 one swappable server and 15.2 the Extensions page
    come first, since neither needs the desktop build and both help `serve` today. Setup
    becomes 15.3, the window 15.4 (with the menu item), frozen-app behaviour 15.5, then the
    build, CI and "Check for updates".
    Slice numbers in Decided entries before this one are the old ones.
  - **To check while building:** where the import job lives (so a swap never strands it),
    whether `create_app` has shutdown hooks the holder must forward, Collection's own job.
- **2026-11-18: Game commentary in the Collection (M18, planned).** Asked for: each move of a
  Collection game explained (what it did, why, what followed) as one structured commentary.
  Your answers:
  - **Both writers:** the app always writes factual notes from Stockfish and python-chess
    (offline, free); with `[ai]` on, a button turns them into prose, saved with the game.
  - **Every move, weighted:** one line per move, a paragraph per key moment, a summary for
    the game and each phase.
  - **Shown two ways:** a book-style Commentary view, and the move's note under the board.
  - **Extra Stockfish analysis**, once per game, when you ask: each side's threat at every
    position, and the top three moves at key moments.
  - **The PGN's own comments** are shown alongside, marked as the PGN's, never sent to AI.
  - **No player names to AI:** White and Black, as for the Log's explanations (your own
    games can be in a collection too).
  - **One AI request per game**, and **an annotated PGN download**.
  - **Mine, for you to overrule:** the facts move from `core/explain.py` into a shared
    `core/facts.py` so the Log and the Collection say the same things the same way; AI
    reaches the extension through two new host functions, never `ai.py` itself.
- **2026-11-19: Journal, an extension for chess notes (M19, planned).** Asked for: a minimal,
  very fast chess journal, like a blog for yourself, with smooth writing and PGN and FEN
  that play in reading mode. Your answers:
  - **Writing:** Markdown in a plain, fast editor, with Writing and Reading modes and one key
    to switch.
  - **Chess in notes:** PGN blocks, FEN diagrams, moves in sentences, arrows and highlights.
  - **The board:** one board that follows you, pinned beside the text.
  - **Organising:** tags, fast search and pinned notes. There's no dated-journal list.
  - **Type:** mono to write, serif to read.
  - **Getting moves in:** paste PGN or FEN, play on a board to insert, copy from the reading
    board, and link to your Log.
  - **Engine:** only when you press Analyse.
  - **Storage:** `journal.db`, plus a Markdown export.
  - **Variations:** playable, indented.
  - **History:** autosave, plus the last 30 versions.
  - **Keyboard:** the full keyboard and a quick switcher.
  - **A working prototype first**, before any code.
  - **Speed over the stack.** You allowed another language as long as it's well integrated
    and blocks neither packaging (M15) nor other extensions. After measuring, you chose
    Python only, with each block's parse cached, and a plain textarea with no syntax
    colours.
- **2026-11-20: The order of work for the planned milestones.** Asked for: an order for
  the plans written so far. My proposal, accepted:
  - **M19 Journal first:** no core change, used daily, prototype fresh.
  - **M20 Cost, not count next:** a small core change, useful at once, a break between two
    big milestones.
  - **M18 Game commentary third:** its core changes (`core/facts.py`, `host.ask_ai`) land
    before the desktop build, so the first build ships the final host API.
  - **M15 Desktop app last:** it packages everything, and it's the biggest and riskiest.
  - **A packaging test first (15.0):** the plan's own risk is a frozen Python 3.15 app, so a
    throwaway build is tried before 15.1 to 15.4 rely on it.
  - **Swaps you can make:** M18 before M19 if studying games matters more than notes. M15
    first, still opening with 15.0, if a download for others is wanted soon.
- **2026-11-20: The Library extension is removed.** Asked for: with the Journal shipped,
  the Library is redundant, since anyone can keep their own knowledge base as notes.
  - **Kept:** its 15 entries (5 openings, 6 traps, 4 tactics), once, as Markdown notes in
    `extensions/journal/examples/`: the idea, a PGN with the replies that matter (`??` on
    the one that loses), a diagram for a tactic, and its practise positions as a "Try it"
    list. You add them with `blunderbook journal new --file`; nothing goes into journal.db
    by itself. A test checks every one plays.
  - **Lost:** Library practise (spaced repetition on its positions) and "From your Log" (your
    entries in an entry's opening).
  - **Your data:** `library.db` and its backups stay on disk, untouched. A Library backup
    can't be restored any more.
  - **`update`:** an installed extension whose folder has left the repo is left out of the
    reinstall and turned off in config.toml, so the reinstall doesn't fail and `serve` and
    `doctor` don't look for it. A development copy runs `blunderbook ext disable library`.
  - **Found on the way:** python-chess can wrap a variation's move number onto its own line
    (`(4...` then `Nd7`); `moves.with_line` now keeps it with its move.
