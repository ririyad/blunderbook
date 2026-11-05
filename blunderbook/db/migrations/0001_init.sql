-- 0001: the schema from CLAUDE.md §5.
-- Migrations are forward-only. The runner wraps each file in one transaction and sets
-- PRAGMA user_version to the file's number, so don't put BEGIN or COMMIT in here.

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

-- Not in §5: SQLite doesn't index foreign keys itself, and deleting a blunder looks up its
-- attempts by blunder_id. (blunders.game_id is covered by UNIQUE (game_id, ply).)
CREATE INDEX retest_attempts_blunder ON retest_attempts (blunder_id);

CREATE TABLE sync_state (
  source        TEXT PRIMARY KEY,             -- 'lichess' | 'chesscom'
  username      TEXT NOT NULL,
  last_synced   TEXT,                         -- ISO time of newest game fetched
  last_run_at   TEXT,
  last_error    TEXT
);
