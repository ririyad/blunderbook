-- The Journal database (ROADMAP 19.1): your notes, as you typed them, with their tags,
-- their earlier versions and a search index. Nothing here is in your Log.

-- One row per note. `body` is the Markdown exactly as typed; `title` and `snippet` are
-- read from it on every save (blunderbook_journal.notes), so the list needs no parsing.
CREATE TABLE notes (
  id           INTEGER PRIMARY KEY,
  title        TEXT NOT NULL,                -- the first line, without its '#'; '' = untitled
  snippet      TEXT NOT NULL,                -- the first line of text after the title
  body         TEXT NOT NULL,
  pinned       INTEGER NOT NULL DEFAULT 0,
  doc          TEXT,                         -- the parsed note as JSON (19.2); NULL = not yet
  doc_version  INTEGER,                      -- the parser version that wrote `doc`
  created_at   TEXT NOT NULL,                -- ISO-8601 UTC
  updated_at   TEXT NOT NULL                 -- ISO-8601 UTC: when the text last changed
);
CREATE INDEX notes_order ON notes (pinned DESC, updated_at DESC);

-- The note's #tags, lower case, read from its text on every save.
CREATE TABLE tags (
  note_id  INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  tag      TEXT NOT NULL,
  PRIMARY KEY (note_id, tag)
) WITHOUT ROWID;
CREATE INDEX tags_tag ON tags (tag);

-- Earlier texts of a note: a save keeps the text it replaces when the newest version is
-- over 5 minutes old. The newest 30 per note are kept.
CREATE TABLE versions (
  id        INTEGER PRIMARY KEY,
  note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  body      TEXT NOT NULL,
  saved_at  TEXT NOT NULL                    -- ISO-8601 UTC: when this was the note's text
);
CREATE INDEX versions_note ON versions (note_id, saved_at);

-- Search: one row per note, rowid = notes.id. `players` holds the PGN headers worth
-- finding (players, event, opening, ECO). Kept in step by blunderbook_journal.store.
CREATE VIRTUAL TABLE search USING fts5(
  title, body, players,
  tokenize = 'unicode61 remove_diacritics 2'
);
