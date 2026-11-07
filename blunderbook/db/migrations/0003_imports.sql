-- 0003: remember each import (CLAUDE.md §5), so the Games tab can list games by the file,
-- paste or sync they came from. Games saved before this have no import (NULL).
-- No BEGIN or COMMIT: the runner adds them.

CREATE TABLE imports (
  id          INTEGER PRIMARY KEY,
  label       TEXT NOT NULL,                  -- "blitz-week.pgn", "Pasted PGN", "Lichess sync"
  kind        TEXT NOT NULL CHECK (kind IN ('file','paste','sync')),
  started_at  TEXT NOT NULL
);

ALTER TABLE games ADD COLUMN import_id INTEGER REFERENCES imports(id);
CREATE INDEX games_import ON games (import_id);
