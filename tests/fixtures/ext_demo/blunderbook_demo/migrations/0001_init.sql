-- The demo extension's database: marks on entries of your Log, by id. Another database
-- can't hold a foreign key to the Log, so the routes check the entry exists.
CREATE TABLE marks (
  id          INTEGER PRIMARY KEY,
  blunder_id  INTEGER NOT NULL,
  note        TEXT NOT NULL
);
