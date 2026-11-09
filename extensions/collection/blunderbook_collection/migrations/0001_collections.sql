-- The Collection's database (ROADMAP 12.1): anyone's games, each analysed once, in any
-- number of collections. A game is kept by its fingerprint (CLAUDE.md §7.4), so the same
-- game in two collections is analysed once. Nothing here is about your Log.
CREATE TABLE collections (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- "Classics"
  created_at  TEXT NOT NULL                         -- ISO-8601 UTC
);

CREATE TABLE games (
  id            INTEGER PRIMARY KEY,
  fingerprint   TEXT NOT NULL UNIQUE,
  source        TEXT NOT NULL CHECK (source IN ('lichess','chesscom','pgn','otb')),
  site_label    TEXT NOT NULL,                -- "Over the board · Paris", "PGN file"
  external_id   TEXT,                         -- site game id when known
  white         TEXT, black TEXT,             -- NULL when unknown ("?")
  white_elo     INTEGER, black_elo INTEGER,
  result        TEXT,                         -- '1-0' | '0-1' | '1/2-1/2' | '*'
  date          TEXT,                         -- the Date header as written: "1858.??.??"
  played_on     TEXT,                         -- YYYY-MM-DD, only for a full date
  event         TEXT, site TEXT, round TEXT,
  time_control  TEXT,                         -- raw header
  tc_base_s     INTEGER, tc_inc_s INTEGER,
  speed         TEXT,                         -- bullet|blitz|rapid|classical|NULL
  opening       TEXT, eco TEXT,
  start_fen     TEXT NOT NULL,
  pgn           TEXT NOT NULL,                -- the game's own text, verbatim
  plies         INTEGER NOT NULL,
  engine_name   TEXT NOT NULL,                -- "Stockfish 17.1"
  engine_depth  INTEGER NOT NULL,
  analysed_at   TEXT NOT NULL                 -- ISO-8601 UTC
);

-- Pass 1 for every position: 0 is the start, i the position after ply i - 1.
CREATE TABLE positions (
  game_id   INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply       INTEGER NOT NULL CHECK (ply >= 0),
  fen       TEXT NOT NULL,
  move_uci  TEXT,                             -- the move that led here; NULL at 0
  move_san  TEXT,
  clock_s   REAL,                             -- the mover's clock after it, from [%clk]
  eval      TEXT NOT NULL,                    -- JSON {"cp":36} | {"mate":-2}, White POV
  best_uci  TEXT,                             -- the engine's move here; NULL when it's over
  pv_uci    TEXT NOT NULL DEFAULT '',         -- its line, space-separated, at most 10 plies
  PRIMARY KEY (game_id, ply)
) WITHOUT ROWID;

CREATE TABLE members (
  collection_id  INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  game_id        INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  added_at       TEXT NOT NULL,               -- ISO-8601 UTC
  PRIMARY KEY (collection_id, game_id)
) WITHOUT ROWID;
CREATE INDEX members_game ON members (game_id);  -- SQLite doesn't index FKs
