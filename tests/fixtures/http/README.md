# Recorded HTTP responses

Tests feed these to the sync adapters and the AI explanation client through httpx
`MockTransport`. Tests never call Lichess, Chess.com or OpenRouter (CLAUDE.md §8, §7.10).

TODO(verify): these are hand-built from the documented formats (sites checked 2026-11-05,
OpenRouter 2026-11-07), not recorded from the real services yet. Replace each with a real response when one is recorded.

| File | Stands for |
|---|---|
| `lichess_user_games.pgn` | `GET https://lichess.org/api/games/user/{username}` with `Accept: application/x-chess-pgn`, `clocks=true`, `opening=true`: two games, oldest first, in Lichess's export layout (headers, one movetext line, two blank lines). |
| `chesscom_archives.json` | `GET https://api.chess.com/pub/player/{username}/games/archives`: three months, oldest first. |
| `chesscom_2026_09.pgn` | `GET .../games/2026/09/pgn`: one live game, in Chess.com's PGN layout (one blank line between games). |
| `chesscom_2026_10.pgn` | `GET .../games/2026/10/pgn`: a live game and a daily game (`[Link ".../game/daily/..."]`). |
| `openrouter_chat_completion.json` | `POST https://openrouter.ai/api/v1/chat/completions`, a non-streaming answer: `choices[0].message.content`, `finish_reason`, `model`, `usage`. |
| `openrouter_error_402.json` | The same request from an account with no credits: `{"error": {"code": 402, "message": ...}}`, HTTP 402. |
