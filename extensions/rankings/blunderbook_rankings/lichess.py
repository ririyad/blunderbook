"""Lichess's leaderboards (ROADMAP 16.2).

Endpoint, checked on 2026-11-12 in the official API docs (https://lichess.org/api, the spec
at github.com/lichess-org/api: ``tags/users/api-player-top-nb-perfType.yaml`` and
``schemas/TopUser.yaml``):

- ``GET https://lichess.org/api/player/top/{nb}/{perfType}``: no key; ``nb`` 1 to 100;
  ``perfType`` one of ultraBullet, bullet, blitz, rapid, classical (and variants, not used
  here). There's no leaderboard for correspondence or puzzles.
- Answer: ``{"users": [{"id", "username", "title"?, "perfs": {"<perfType>": {"rating",
  "progress"}}, "patron"?, "online"?}]}``, best first.
- Lichess asks for one request at a time, and a minute's wait after a 429.
"""

import json
from typing import Final

from blunderbook_rankings.site import MAX_NAME, MAX_TITLE, BadBoard, SitePlayer, text, whole

TOP: Final = 100
BOARDS: Final = ("bullet", "blitz", "rapid", "classical", "ultraBullet")
NAMES: Final = {
    "bullet": "Bullet",
    "blitz": "Blitz",
    "rapid": "Rapid",
    "classical": "Classical",
    "ultraBullet": "UltraBullet",
}


def url(board: str) -> str:
    return f"https://lichess.org/api/player/top/{TOP}/{board}"


def profile(username: str) -> str:
    return f"https://lichess.org/@/{username}"


def parse(board: str, data: bytes) -> list[SitePlayer]:
    """One leaderboard, best first. Entries without a name or a rating are skipped. Raises
    BadBoard when the answer isn't a leaderboard at all."""
    try:
        answer = json.loads(data)
    except ValueError as exc:
        raise BadBoard(f"Lichess's {NAMES[board]} leaderboard couldn't be read.") from exc
    users = answer.get("users") if isinstance(answer, dict) else None
    if not isinstance(users, list):
        raise BadBoard(f"Lichess's {NAMES[board]} leaderboard couldn't be read.")
    found: list[SitePlayer] = []
    for user in users:
        if not isinstance(user, dict):
            continue
        perfs = user.get("perfs")
        perf = perfs.get(board) if isinstance(perfs, dict) else None
        rating = whole(perf.get("rating")) if isinstance(perf, dict) else None
        name = text(user.get("username"), MAX_NAME)
        if name is None or rating is None:
            continue
        progress = whole(perf.get("progress")) if isinstance(perf, dict) else None
        found.append(
            SitePlayer(len(found) + 1, name, text(user.get("title"), MAX_TITLE), rating, progress)
        )
    return found
