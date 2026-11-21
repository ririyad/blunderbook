-- 0004: keep every position's pass-1 score and best move (CLAUDE.md §5, ROADMAP 21.1), so
-- a game can be judged again without Stockfish, and record the engine's threads and hash.
-- Games saved before this have no positions and NULL settings until they're re-analysed.
-- No BEGIN or COMMIT: the runner adds them.

CREATE TABLE positions (
  game_id   INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply       INTEGER NOT NULL,                 -- 0 = the start, i = after ply i - 1
  eval      TEXT NOT NULL,                    -- JSON {"cp":36} | {"mate":-2}, White POV
  best_uci  TEXT,                             -- the engine's move here; NULL when it's over
  PRIMARY KEY (game_id, ply)
);

ALTER TABLE games ADD COLUMN engine_threads INTEGER;
ALTER TABLE games ADD COLUMN engine_hash_mb INTEGER;
