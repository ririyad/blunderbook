"""The Rankings' test setup: a scratch config.toml with the extension on, FIDE zips built in
memory, and a fake server (httpx ``MockTransport``), so no test touches your real files or
the network.

Not a conftest.py: core's tests import their own ``conftest`` by name, and a second one on
the path would shadow it. Each test module imports these fixtures instead."""

import io
import json
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from blunderbook_rankings import chesscom, fide, lichess, net

from blunderbook import config

FIXTURES = Path(__file__).parent / "fixtures"
NOV = "Wed, 11 Nov 2026 09:00:00 GMT"
DEC = "Tue, 01 Dec 2026 09:00:00 GMT"


@pytest.fixture(autouse=True)
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """config.toml with the Rankings on, and Blunderbook's database next to rankings.db,
    both in tmp_path. Every test gets them, so none touches your real files."""
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "data" / "blunderbook.db")
    config.save(config.Config(extensions=config.ExtensionsConfig(enabled=("rankings",))), path)
    return path


def player(
    fide_id: int,
    rating: int,
    *,
    name: str | None = None,
    fed: str = "NOR",
    sex: str = "M",
    title: str = "",
    born: str = "1990",
    flag: str = "",
    games: str = "9",
) -> dict[str, str]:
    """One ``<player>``'s fields, as FIDE's XML has them."""
    return {
        "fideid": str(fide_id),
        "name": name or f"Player, {fide_id}",
        "country": fed,
        "sex": sex,
        "title": title,
        "w_title": "",
        "o_title": "",
        "foa_title": "",
        "rating": str(rating),
        "games": games,
        "k": "10",
        "birthday": born,
        "flag": flag,
    }


def xml(*players: dict[str, str]) -> bytes:
    rows = "".join(
        "<player>" + "".join(f"<{k}>{v}</{k}>" for k, v in p.items()) + "</player>" for p in players
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<playerslist>{rows}</playerslist>\n'.encode()


def fide_zip(data: bytes, member: str = "standard_nov26frl_xml.xml") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, data)
    return buf.getvalue()


def month_zip(speed: fide.Speed, month: str, *players: dict[str, str]) -> bytes:
    """A list for ``month`` ("nov26"), with ``players`` or one default player."""
    return fide_zip(xml(*(players or (player(1503014, 2830),))), f"{speed}_{month}frl_xml.xml")


Handler = Callable[[httpx.Request], httpx.Response]


class Server:
    """A fake server: each URL answers its queue of responses, in order (the last one
    again once the queue is down to one). Every request is kept."""

    def __init__(self) -> None:
        self.answers: dict[str, list[Handler]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, url: str, *answers: Handler) -> None:
        self.answers[url] = list(answers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.answers.get(str(request.url))
        if not queue:
            return httpx.Response(404)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return answer(request)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handle),
            headers={"User-Agent": net.USER_AGENT},
            follow_redirects=True,
        )

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def ok(body: bytes, etag: str | None = None, modified: str | None = NOV) -> Handler:
    """200 with ``body``; 304 when the request sends back the same ETag."""

    def answer(request: httpx.Request) -> httpx.Response:
        if etag is not None and request.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        headers = {}
        if etag is not None:
            headers["ETag"] = etag
        if modified is not None:
            headers["Last-Modified"] = modified
        return httpx.Response(200, content=body, headers=headers)

    return answer


def status(code: int, **headers: str) -> Handler:
    return lambda request: httpx.Response(code, headers=headers)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    """The fake server, used by ``net.client()`` (so by the commands too)."""
    fake = Server()
    monkeypatch.setattr(net, "client", lambda user_agent=net.USER_AGENT: fake.client())
    yield fake


def serve_fide(fake: Server, month: str = "nov26", modified: str = NOV) -> None:
    """All three lists for ``month``, each with an ETag."""
    for speed in fide.SPEEDS:
        fake.on(
            fide.url(speed),
            ok(month_zip(speed, month), etag=f'"{speed}-{month}"', modified=modified),
        )


# ---------------------------------------------------------------- Lichess and Chess.com
# Shaped like the recorded answers in fixtures/ (lichess_blitz_recorded.json,
# chesscom_leaderboards_recorded.json, 2026-11-12), with only the fields that are read.


def lichess_json(board: str, *users: tuple[str, int, int], title: str | None = "GM") -> bytes:
    """A leaderboard of ``users`` (name, rating, progress), best first."""
    rows = []
    for name, rating, progress in users or (("DrNykterstein", 3200, 12),):
        row: dict[str, object] = {
            "id": name.lower(),
            "username": name,
            "perfs": {board: {"rating": rating, "progress": progress}},
        }
        if title:
            row["title"] = title
        rows.append(row)
    return json.dumps({"users": rows}).encode()


def chesscom_json(**boards: list[tuple[str, int]]) -> bytes:
    """Boards of (username, score), best first; every board used when none is given."""
    chosen = boards or {
        board: [("Hikaru", 3300), ("MagnusCarlsen", 3290)] for board in chesscom.BOARDS
    }
    answer: dict[str, object] = {"tactics": [{"username": "Puzzler", "score": 5000, "rank": 1}]}
    for board, entries in chosen.items():
        answer[board] = [
            {
                "player_id": 1000 + i,
                "@id": f"https://api.chess.com/pub/player/{name.lower()}",
                "url": f"https://www.chess.com/member/{name}",
                "username": name,
                "score": score,
                "rank": i,
            }
            for i, (name, score) in enumerate(entries, start=1)
        ]
    return json.dumps(answer).encode()


def serve_sites(fake: Server, etag: str = '"cc-1"') -> None:
    for board in lichess.BOARDS:
        fake.on(lichess.url(board), ok(lichess_json(board), modified=None))
    fake.on(chesscom.URL, ok(chesscom_json(), etag=etag, modified=NOV))
