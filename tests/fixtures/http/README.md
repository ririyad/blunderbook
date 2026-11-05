# Recorded HTTP responses

Tests feed these to the sync adapters through httpx `MockTransport`. Tests never call
Lichess or Chess.com (CLAUDE.md §8).

TODO(verify): these are hand-built from the documented formats (checked 2026-11-05), not
recorded from the real sites yet. Replace each with a real response when one is recorded.

| File | Stands for |
|---|---|
| `lichess_user_games.pgn` | `GET https://lichess.org/api/games/user/{username}` with `Accept: application/x-chess-pgn`, `clocks=true`, `opening=true`: two games, oldest first, in Lichess's export layout (headers, one movetext line, two blank lines). |
