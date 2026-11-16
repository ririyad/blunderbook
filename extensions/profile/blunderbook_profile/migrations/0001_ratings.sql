-- The Profile database (ROADMAP 17.2): your ratings as Lichess and Chess.com reported them,
-- each time you asked (`blunderbook profile refresh`, or the tab's button). Nothing here is
-- in your Log, and your rating over time is read from your games, not kept here.

-- One row per site per day you asked: asking again the same day replaces that day's row, so
-- "since last time" always compares two different days.
CREATE TABLE fetches (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL CHECK (source IN ('lichess','chesscom')),
  username    TEXT NOT NULL,                 -- the account asked about
  day         TEXT NOT NULL,                 -- local YYYY-MM-DD
  fetched_at  TEXT NOT NULL,                 -- ISO-8601 UTC
  UNIQUE (source, day)
);

-- One row per kind of play the site gave a rating for. What it didn't give is NULL.
CREATE TABLE ratings (
  fetch_id     INTEGER NOT NULL REFERENCES fetches(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL
               CHECK (kind IN ('bullet','blitz','rapid','classical','daily','puzzle')),
  rating       INTEGER,                      -- now; NULL when the site only gives a highest
  provisional  INTEGER NOT NULL DEFAULT 0,
  games        INTEGER,
  best         INTEGER,                      -- your highest
  best_at      TEXT,                         -- ISO-8601 UTC
  wins         INTEGER,
  losses       INTEGER,
  draws        INTEGER,
  PRIMARY KEY (fetch_id, kind)
) WITHOUT ROWID;
