# Recorded HTTP responses

Tests feed these to the sync adapters through httpx `MockTransport`. Tests never call
Lichess or Chess.com (CLAUDE.md §8).

TODO(verify): these are hand-built from the documented formats (checked 2026-11-05), not
recorded from the real sites yet. Replace each with a real response when one is recorded.

| File | Stands for |
|---|---|
| `lichess_user_games.pgn` | `GET https://lichess.org/api/games/user/{username}` with `Accept: application/x-chess-pgn`, `clocks=true`, `opening=true`: two games, oldest first, in Lichess's export layout (headers, one movetext line, two blank lines). |
| `chesscom_archives.json` | `GET https://api.chess.com/pub/player/{username}/games/archives`: three months, oldest first. |
| `chesscom_2026_09.pgn` | `GET .../games/2026/09/pgn`: one live game, in Chess.com's PGN layout (one blank line between games). |
| `chesscom_2026_10.pgn` | `GET .../games/2026/10/pgn`: a live game and a daily game (`[Link ".../game/daily/..."]`). |
