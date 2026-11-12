"""Chess.com's leaderboards (ROADMAP 16.2).

Endpoint, checked on 2026-11-12 in the official docs
(https://www.chess.com/news/view/published-data-api, "Leaderboards"):

- ``GET https://api.chess.com/pub/leaderboards``: no key; one answer with every board.
  Boards used here: ``live_rapid``, ``live_blitz``, ``live_bullet`` and ``daily`` (others,
  such as ``daily960``, ``live_bughouse`` and ``tactics``, are left out).
- Each board is a list of up to 50 entries: ``player_id``, ``@id``, ``url``, ``username``,
  ``score`` and ``rank``. TODO(verify): whether entries carry ``title`` (not documented;
  used when present).
- It sends ``ETag`` and ``Last-Modified``: send them back (``If-None-Match``,
  ``If-Modified-Since``) for a 304 when nothing changed. Requests one at a time; a
  descriptive User-Agent with contact details, as Chess.com asks.
"""

import json
from typing import Final

from blunderbook_rankings.site import MAX_NAME, MAX_TITLE, BadBoard, SitePlayer, text, whole

URL: Final = "https://api.chess.com/pub/leaderboards"
BOARDS: Final = ("live_rapid", "live_blitz", "live_bullet", "daily")
NAMES: Final = {
    "live_rapid": "Rapid",
    "live_blitz": "Blitz",
    "live_bullet": "Bullet",
    "daily": "Daily",
}
TOP: Final = 50


def profile(username: str) -> str:
    return f"https://www.chess.com/member/{username}"


def parse(data: bytes) -> dict[str, list[SitePlayer]]:
    """Each of BOARDS in the answer, best first (by ``rank``). A board that's missing is
    left out; entries without a name or a score are skipped. Raises BadBoard when the answer
    has none of the boards."""
    try:
        answer = json.loads(data)
    except ValueError as exc:
        raise BadBoard("Chess.com's leaderboards couldn't be read.") from exc
    if not isinstance(answer, dict) or not any(
        isinstance(answer.get(board), list) for board in BOARDS
    ):
        raise BadBoard("Chess.com's leaderboards couldn't be read.")
    boards: dict[str, list[SitePlayer]] = {}
    for board in BOARDS:
        entries = answer.get(board)
        if not isinstance(entries, list):
            continue
        rows: list[tuple[int, str, str | None, int]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = text(entry.get("username"), MAX_NAME)
            score = whole(entry.get("score"))
            if name is None or score is None:
                continue
            rank = whole(entry.get("rank")) or len(rows) + 1
            rows.append((rank, name, text(entry.get("title"), MAX_TITLE), score))
        rows.sort(key=lambda r: r[0])
        boards[board] = [
            SitePlayer(i, name, title, score, None)
            for i, (_, name, title, score) in enumerate(rows[:TOP], start=1)
        ]
    return boards
