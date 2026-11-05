"""Chess.com sync adapter: downloads your games as PGN (CLAUDE.md §8). The code arrives in 6.3.

API notes, checked 2026-11-05 against the official "Published-Data API" page
(https://www.chess.com/news/view/published-data-api):

Endpoints (read-only, no authentication)
    - ``GET https://api.chess.com/pub/player/{username}/games/archives``:
      ``{"archives": ["https://api.chess.com/pub/player/{username}/games/YYYY/MM", ...]}``,
      in ascending chronological order. Only months with games are listed.
    - ``GET https://api.chess.com/pub/player/{username}/games/{YYYY}/{MM}/pgn``: that month's
      games as one PGN file (``Content-Type: application/x-chess-pgn``, not JSON-encoded;
      ``Content-Disposition: attachment; filename="ChessCom_username_YYYYMM.pgn"``).
      ``YYYY``/``MM`` is the month the game *ended*, with a two-digit month.
    - (Not used: ``.../games/{YYYY}/{MM}`` is the same month as JSON, ``{"games": [...]}``,
      each with a ``pgn`` field.)
    The examples use lowercase usernames, and the page doesn't say whether case matters.
    TODO(verify): send the username lowercased.

Which months
    Past months never change, so download only the months from the last synced month onward
    (§8). The month of ``sync_state.last_synced`` is fetched again because it may have been
    incomplete. No HTTP cache table: we don't keep ETags. The page offers ``ETag`` /
    ``Last-Modified`` with ``If-None-Match`` / ``If-Modified-Since`` -> 304, and says data
    refreshes "at most once every 12 hours" in one place and every 24 hours in another, so
    a game you just finished may not be there yet.

Rate limits
    Serial access is unlimited: send one request at a time, waiting for each answer.
    Parallel requests may get ``429 Too Many Requests``. Suspicious activity can get the
    application blocked.

User-Agent
    Chess.com asks for "a recognizable user-agent that contains contact information", so they
    can reach you rather than block you. We send
    ``Blunderbook/<version> (contact: <chesscom.contact>)``. There's no required format.
    Don't fill the contact in for the user.

Status codes
    301: the right URL is elsewhere; follow it. 404: malformed URL, or no such data (e.g. an
    unknown username). 410: there will never be data there; don't ask again.

Game ids
    Each game's ``[Link "https://www.chess.com/game/live/<id>"]`` header gives the
    fingerprint (§7.4). TODO(verify) with a real download: the Link header and ``[%clk]``
    comments in the monthly PGN.
"""
