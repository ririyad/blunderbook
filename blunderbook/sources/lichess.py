"""Lichess sync adapter: downloads your games as PGN (CLAUDE.md §8). The code arrives in 6.2.

API notes, checked 2026-11-05 against the official OpenAPI spec (github.com/lichess-org/api,
``doc/specs/lichess-api.yaml`` and ``tags/games/api-games-user-username.yaml``; lichess.org/api
renders the same spec):

Endpoint
    ``GET https://lichess.org/api/games/user/{username}`` ("Export games of a user").
    Most recent first by default; the response is streamed, and the spec advises reading it
    as a stream because it can be very large.

Header
    ``Accept: application/x-chess-pgn`` (the default) gives PGN text, one game after
    another. ``application/x-ndjson`` gives JSON lines. We use PGN: the core takes PGN only.

Query parameters we send
    - ``since`` (int): "games played since this timestamp". Default: account creation.
      Minimum ``1356998400070``, so it's Unix time in milliseconds.
      TODO(verify): whether it compares with the game's start or end time.
    - ``clocks=true`` (default false): ``[%clk h:mm:ss]`` comments for the time hints.
    - ``opening=true`` (default false): the ``Opening`` header.
    - ``evals=false`` (default false): we run our own Stockfish anyway (§1.5).
    - ``tags=true``, ``moves=true``, ``finished=true``, ``ongoing=false``: the defaults,
      sent explicitly so a change of default can't surprise us.
    - ``sort``: ``dateDesc`` (default) or ``dateAsc``. TODO(decide in 6.2): oldest first
      would let a sync that stops halfway keep its progress.
    - ``perfType`` (comma-separated): ``ultraBullet, bullet, blitz, rapid, classical,
      correspondence, chess960, crazyhouse, antichess, atomic, horde, kingOfTheHill,
      racingKings, threeCheck``. Sending only the standard ones saves downloading variant
      games that the importer rejects anyway (§7.1).
    Not used: ``until``, ``max``, ``vs``, ``rated``, ``color``, ``analysed``, ``pgnInJson``,
    ``accuracy``, ``division``, ``literate``, ``lastFen``, ``withBookmarked`` (several of
    these are NDJSON only).

Authentication
    Optional. A personal API access token goes in ``Authorization: Bearer {token}``. The spec
    lists no scope for this endpoint. A token only raises the download speed. Never log it, and
    redact it from errors (§6).

Rate limits
    The stream is throttled to 20 games/s anonymous, 30 games/s with a token, and 60 games/s
    for your own games with a token. On HTTP 429 the spec says waiting one minute is usually
    enough, but some limits need longer: back off at least 60 s, then retry.

Game ids
    Each game's ``[Site "https://lichess.org/<8-char id>"]`` gives the fingerprint (§7.4).
"""
