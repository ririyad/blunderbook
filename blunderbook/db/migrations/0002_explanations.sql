-- 0002: saved AI explanations (CLAUDE.md §5, §7.10). One per entry: explaining again
-- replaces it, and deleting the entry deletes it. No BEGIN or COMMIT: the runner adds them.

CREATE TABLE explanations (
  blunder_id      INTEGER PRIMARY KEY REFERENCES blunders(id) ON DELETE CASCADE,
  text            TEXT NOT NULL,
  model           TEXT NOT NULL,               -- the OpenRouter model that wrote it
  prompt_version  INTEGER NOT NULL,            -- core/explain.py PROMPT_VERSION
  created_at      TEXT NOT NULL
);
