-- The Rankings database (ROADMAP 16.1): the top lists the tab shows, downloaded only when
-- you press Update or run `blunderbook rankings update`. It holds only what the tab can show,
-- so it stays small in every backup. Nothing here is about your Log.

-- One row per source: what was downloaded last, and the last problem.
CREATE TABLE sources (
  source      TEXT PRIMARY KEY CHECK (source IN ('fide','lichess','chesscom')),
  list_month  TEXT,                          -- FIDE: "2026-11", the newest list kept
  fetched_at  TEXT,                          -- ISO-8601 UTC of the last update that changed it
  checked_at  TEXT,                          -- ISO-8601 UTC of the last update that ran
  last_error  TEXT                           -- NULL after an update that worked
) WITHOUT ROWID;

-- What the server said about each file, so an unchanged one isn't downloaded again.
CREATE TABLE downloads (
  url            TEXT PRIMARY KEY,
  etag           TEXT,
  last_modified  TEXT
) WITHOUT ROWID;

-- FIDE's active players the tab can show (the world top 100 and each federation's top 50 in
-- Open, Women, Juniors and Girls), for the two newest months of each list.
CREATE TABLE fide_players (
  list_month  TEXT NOT NULL,                 -- "2026-11"
  speed       TEXT NOT NULL CHECK (speed IN ('standard','rapid','blitz')),
  fide_id     INTEGER NOT NULL,
  name        TEXT NOT NULL,                 -- as FIDE writes it: "Carlsen, Magnus"
  fed         TEXT,                          -- "NOR"; NULL when missing
  sex         TEXT,                          -- 'M' | 'F' | NULL
  title       TEXT,                          -- "GM", "WGM", ...; NULL when none
  born        INTEGER,                       -- birth year; NULL when missing
  rating      INTEGER NOT NULL,
  games       INTEGER,                       -- rated games in the list's period
  PRIMARY KEY (list_month, speed, fide_id)
) WITHOUT ROWID;
CREATE INDEX fide_players_top ON fide_players (list_month, speed, rating DESC);

-- The latest Lichess and Chess.com leaderboards, as fetched.
CREATE TABLE site_players (
  source    TEXT NOT NULL CHECK (source IN ('lichess','chesscom')),
  board     TEXT NOT NULL,                   -- "blitz" (Lichess), "live_blitz" (Chess.com)
  rank      INTEGER NOT NULL,
  username  TEXT NOT NULL,
  title     TEXT,
  rating    INTEGER NOT NULL,
  progress  INTEGER,                         -- Lichess's own change; NULL for Chess.com
  PRIMARY KEY (source, board, rank)
) WITHOUT ROWID;
