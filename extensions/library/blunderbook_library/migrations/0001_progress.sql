-- The Library's database (ROADMAP 11.3): your practise. A position is named by its entry's
-- id and its FEN, so it keeps its progress when positions are added to an entry or
-- reordered. One that leaves the content is kept, and counts again if it comes back.
-- A position you haven't tried has no row: it's new, and due today.
CREATE TABLE progress (
  entry_id    TEXT NOT NULL,                -- the content file's name: "legal-trap"
  fen         TEXT NOT NULL,                -- the position, as the content checker gives it
  status      TEXT NOT NULL CHECK (status IN ('solved','missed')),
  streak      INTEGER NOT NULL CHECK (streak >= 0),
  due_on      TEXT NOT NULL,                -- YYYY-MM-DD, local
  updated_at  TEXT NOT NULL,                -- ISO-8601 UTC
  PRIMARY KEY (entry_id, fen)
) WITHOUT ROWID;

CREATE TABLE attempts (
  id            INTEGER PRIMARY KEY,
  entry_id      TEXT NOT NULL,
  fen           TEXT NOT NULL,
  attempted_at  TEXT NOT NULL,              -- ISO-8601 UTC
  move_uci      TEXT,                       -- NULL when you gave up
  solved        INTEGER NOT NULL,
  used_hint     INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (entry_id, fen) REFERENCES progress (entry_id, fen) ON DELETE CASCADE
);
CREATE INDEX attempts_position ON attempts (entry_id, fen);  -- SQLite doesn't index FKs
