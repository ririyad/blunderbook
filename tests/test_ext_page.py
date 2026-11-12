"""Extensions in the web app and the host API (CLAUDE.md §15): their routes, page files and
tabs, the read-only Log, settings and Stockfish, and the page checks they can reuse. The
sample "notes" extension is in ext_samples.py."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import timedelta
from importlib.metadata import EntryPoint
from pathlib import Path

import ext_samples
import pytest
from ext_samples import notes
from fastapi.testclient import TestClient
from test_api_blunders import NOW, elephant, fen_entry, scholars

from blunderbook import config, ext, host, webcheck
from blunderbook.api.app import CONTENT_SECURITY_POLICY, WEB, create_app
from blunderbook.config import AiConfig, ChesscomConfig, Config, ExtensionsConfig, LichessConfig
from blunderbook.core.models import Thresholds
from blunderbook.db import connection, repo

URL = "http://127.0.0.1"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    config.save(Config(extensions=ExtensionsConfig(enabled=("notes",))), path)
    return path


@pytest.fixture
def notes_db(cfg_file: Path) -> Path:
    with closing(ext.open_db(notes, config.load(cfg_file))):
        pass  # created, as `serve` does before the first request
    return ext.db_path(notes)


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    """Three entries in the Log."""
    made: dict[str, int] = {}
    with closing(connection.open_db(db_file, create=True)) as conn:
        for minutes, (name, make) in enumerate(
            (("elephant", elephant), ("scholars", scholars), ("fen", fen_entry))
        ):
            game, blunder = make()
            saved = repo.add_game(conn, game, [blunder], now=NOW + timedelta(minutes=minutes))
            assert saved is not None
            made[name] = saved.blunder_ids[0]
    return made


@pytest.fixture
def client(db_file: Path, notes_db: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file, [notes, ext_samples.sample]), base_url=URL) as c:
        yield c


# ---------------------------------------------------------------- the app


def test_extensions_with_a_page_are_listed(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "notes", "title": "Notes", "css": True}
    ]  # sample has commands only: no tab


def test_no_extensions(db_file: Path) -> None:
    with TestClient(create_app(db_file), base_url=URL) as plain:
        assert plain.get("/api/extensions").json() == []
        assert plain.get("/ext/notes/view.js").status_code == 404
        assert plain.get("/api/ext/notes/notes").status_code == 404


@pytest.mark.parametrize(
    ("path", "kind"),
    [("/ext/notes/view.js", "text/javascript"), ("/ext/notes/view.css", "text/css")],
)
def test_page_files_are_served_like_the_pages_own(client: TestClient, path: str, kind: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(kind)
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/ext/notes/missing.js",
        "/ext/notes/../migrations/0001_init.sql",
        "/ext/notes/",
        "/ext/other/view.js",
    ],
)
def test_nothing_else_is_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_other_hosts_get_nothing(db_file: Path, notes_db: Path) -> None:
    with TestClient(create_app(db_file, [notes]), base_url="http://evil.example") as other:
        assert other.get("/ext/notes/view.js").status_code == 400
        assert other.get("/api/ext/notes/notes").status_code == 400


def test_routes_use_their_own_database(client: TestClient) -> None:
    added = client.post("/api/ext/notes/notes", json={"text": "Look at the back rank"})
    assert added.status_code == 201
    assert client.get("/api/ext/notes/notes").json() == [{"id": 1, "text": "Look at the back rank"}]
    with closing(connection.connect(ext.db_path(notes), mode="ro")) as conn:
        rows = conn.execute("SELECT text FROM notes").fetchall()
    assert [tuple(row) for row in rows] == [("Look at the back rank",)]


def test_same_origin_is_there_for_extensions(client: TestClient) -> None:
    sent = client.post(
        "/api/ext/notes/notes", json={"text": "x"}, headers={"Origin": "http://evil.example"}
    )
    assert sent.status_code == 403
    assert client.get("/api/ext/notes/notes").json() == []


def test_the_log_can_be_read(client: TestClient, ids: dict[str, int]) -> None:
    assert client.get("/api/ext/notes/log").json() == {"entries": 3}


def test_the_log_cant_be_changed(ids: dict[str, int], db_file: Path, notes_db: Path) -> None:
    app = create_app(db_file, [notes])
    with (
        TestClient(app, base_url=URL, raise_server_exceptions=True) as c,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        c.delete("/api/ext/notes/log")
    with TestClient(app, base_url=URL) as c:
        assert c.get("/api/ext/notes/log").json() == {"entries": 3}


def test_no_log_yet_is_a_503(client: TestClient, db_file: Path) -> None:
    assert not db_file.exists()
    assert client.get("/api/ext/notes/log").status_code == 503


# ---------------------------------------------------------------- loading


@pytest.mark.parametrize(
    ("attr", "reason"),
    [
        ("no_view", "The noview extension's page folder has no view.js."),
        ("no_migrations", "The nomigrations extension's migrations folder is missing."),
    ],
)
def test_an_extension_with_missing_files_isnt_loaded(attr: str, reason: str) -> None:
    point = EntryPoint(getattr(ext_samples, attr).name, f"ext_samples:{attr}", ext.GROUP)
    assert ext.load_one(point) == (None, reason)


def test_web_folder() -> None:
    assert ext.web_folder(notes) == ext_samples.NOTES / "web"
    assert ext.web_folder(ext_samples.sample) is None


# ---------------------------------------------------------------- the host API


def test_settings_never_carry_secrets(cfg_file: Path) -> None:
    cfg = Config(
        my_names=("Rashed",),
        engine_depth=14,
        thresholds=Thresholds(blunder=0.2),
        lichess=LichessConfig(username="rashed_l", token="lip_secret"),
        chesscom=ChesscomConfig(contact=" me@example.org "),
        ai=AiConfig(key="sk-or-secret"),
    )
    config.save(cfg, cfg_file)
    got = host.settings()
    assert got == host.Settings(
        my_names=("Rashed", "rashed_l"),
        thresholds=Thresholds(blunder=0.2),
        engine_depth=14,
        engine_threads=2,
        engine_hash_mb=128,
        chesscom_contact="me@example.org",
    )
    assert "lip_secret" not in repr(got) and "sk-or-secret" not in repr(got)
    assert set(host.Settings.__slots__) == {  # type: ignore[attr-defined]
        "my_names", "thresholds", "engine_depth", "engine_threads", "engine_hash_mb",
        "chesscom_contact",
    }  # fmt: skip


def test_a_broken_config_is_a_host_error(cfg_file: Path) -> None:
    cfg_file.write_text("engine_depth = 'deep'\n")
    with pytest.raises(host.HostError):
        host.settings()


def test_no_stockfish_is_a_host_error(cfg_file: Path) -> None:
    with pytest.raises(host.HostError, match="Can't analyse: No Stockfish found"):
        host.engine()


@pytest.mark.engine
def test_engine(cfg_file: Path, stockfish_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.STOCKFISH_ENV, str(stockfish_path))
    with host.engine() as sf:
        assert sf.name.startswith("Stockfish")
    assert sf.closed


def test_read_log_outside_a_request(ids: dict[str, int]) -> None:
    with host.read_log() as log:
        entries = log.entries()
        assert len(entries) == 3
        one = log.entry(ids["elephant"])
        assert one is not None and log.game(one.game.id) == one.game
        assert log.entry(999) is None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            log._conn.execute("DELETE FROM blunders")


def test_open_db_outside_a_request(cfg_file: Path) -> None:
    with closing(host.open_db(notes)) as conn:
        assert connection.table_names(conn) == {"notes"}


# ---------------------------------------------------------------- page checks


def test_the_sample_page_passes(db_file: Path) -> None:
    folder = ext.web_folder(notes)
    assert folder is not None
    assert webcheck.problems(folder, create_app(db_file, [notes])) == []


def test_blunderbooks_own_page_passes(db_file: Path) -> None:
    assert webcheck.problems(WEB, create_app(db_file), view=False) == []


def test_the_checks_find_problems(tmp_path: Path, db_file: Path) -> None:
    page = tmp_path / "page"
    page.mkdir()
    (page / "view.js").write_text(
        'import { api } from "/js/api.js";\n'
        'import { nope } from "/js/nope.js";\n'
        'import { x } from "./x.js";\n'
        'import { y } from "../outside.js";\n'
        'import { z } from "lodash";\n'
        "export function draw() {}\n"
        'api("/api/ext/page/missing");\n'
        "el.innerHTML = '<button onclick=\"go()\">Go</button>';\n"
        'const font = "https://fonts.example.com/a.css";\n'
    )
    (page / "index.html").write_text("<script>alert(1)</script>")
    assert webcheck.problems(page, create_app(db_file)) == [
        "view.js doesn't export a function show(root, rest)",
        "index.html: an inline <script> (the CSP blocks it)",
        "view.js: loads https://fonts.example.com from elsewhere",
        "view.js: an on...= handler in HTML (the CSP blocks it)",
        "view.js: imports /js/nope.js, which Blunderbook doesn't have",
        "view.js: imports ./x.js, which doesn't exist",
        "view.js: imports ../outside.js, which is outside its folder",
        "view.js: imports lodash, which isn't a .js file",
        "view.js: calls /api/ext/page/missing, which isn't a route",
    ]
    (page / "view.js").unlink()
    assert webcheck.problems(page, create_app(db_file))[0] == "view.js is missing"
