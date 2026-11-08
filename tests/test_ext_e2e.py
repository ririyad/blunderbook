"""One extension end to end (CLAUDE.md §15), installed for real: the demo package in
fixtures/ext_demo is put on sys.path, so importlib.metadata finds its entry point as it
would after `uv tool install --with`. Nothing is faked between `ext enable` and the page:
its commands, `serve`, its routes, page files and database, backup and restore, and your
Log, which it reads and never changes."""

import ast
import re
import socket
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_api_blunders import NOW, elephant, fen_entry, scholars
from typer.testing import CliRunner

from blunderbook import cli, config, ext, webcheck
from blunderbook.api.app import create_app
from blunderbook.db import backup, connection, repo

DEMO = Path(__file__).parent / "fixtures" / "ext_demo"
PACKAGE = DEMO / "blunderbook_demo"
CORE_PACKAGE = Path(cli.__file__).parent
URL = "http://127.0.0.1"
runner = CliRunner()


@pytest.fixture(autouse=True)
def demo_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(DEMO))


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.delenv("ONEDRIVE", raising=False)
    return path


@pytest.fixture
def restore_commands() -> Iterator[None]:
    """add_extension_commands() changes the app itself: put it back afterwards."""
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Callable[[], tuple[str, FastAPI]]:
    """`blunderbook serve`, up to the point where uvicorn would start: its output, and the
    app it would have served."""
    apps: list[FastAPI] = []

    def fake_run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        apps.append(self.config.app)

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)

    def run() -> tuple[str, FastAPI]:
        with closing(socket.socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result = runner.invoke(cli.app, ["serve", "--port", str(port)])
        assert result.exit_code == 0, result.output
        return result.output, apps[-1]

    return run


def log_entries(db: Path) -> list[int]:
    with closing(connection.open_db(db, create=True)) as conn:
        ids = []
        for minutes, make in enumerate((elephant, scholars, fen_entry)):
            game, blunder = make()
            saved = repo.add_game(conn, game, [blunder], now=NOW + timedelta(minutes=minutes))
            assert saved is not None
            ids.extend(saved.blunder_ids)
    return ids


def marks(db: Path) -> list[str]:
    with closing(connection.connect(db, mode="ro")) as conn:
        return [row[0] for row in conn.execute("SELECT note FROM marks ORDER BY id")]


def invoke(*args: str) -> str:
    result = runner.invoke(cli.app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_end_to_end(
    cfg_file: Path,
    db_file: Path,
    restore_commands: None,
    serve: Callable[[], tuple[str, FastAPI]],
) -> None:
    config.save(config.Config(my_names=("Rashed",), engine_depth=13), cfg_file)
    ids = log_entries(db_file)
    demo_db = db_file.parent / "demo.db"

    # Found as an installed package, off until turned on.
    assert "demo        off  blunderbook-demo 0.1" in invoke("ext", "list")
    assert invoke("ext", "enable", "demo") == (
        "Turned on demo (Demo).\nRestart blunderbook serve to see it on the page.\n"
    )
    assert config.load(cfg_file).extensions.enabled == ("demo",)
    assert "demo        on   blunderbook-demo 0.1 \N{MIDDLE DOT} Demo" in invoke("ext", "list")

    # Its commands, with its database created on first use.
    cli.add_extension_commands()
    assert invoke("demo", "count") == "0 marks \N{MIDDLE DOT} 3 entries in your Log\n"
    assert demo_db.is_file()

    # serve: its tab, files and routes.
    output, app = serve()
    assert "Extensions: Demo\n" in output
    with TestClient(app, base_url=URL) as page:
        assert page.get("/api/extensions").json() == [
            {"name": "demo", "title": "Demo", "css": False}
        ]
        for path in ("/ext/demo/view.js", "/ext/demo/parts.js"):
            assert page.get(path).headers["content-type"].startswith("text/javascript")
        added = page.post("/api/ext/demo/marks", json={"blunder_id": ids[0], "note": "Again"})
        assert added.status_code == 201, added.text
        assert added.json()["played_san"] == "Nxd5"
        missing = page.post("/api/ext/demo/marks", json={"blunder_id": 999, "note": "x"})
        assert (missing.status_code, missing.json()) == (404, {"detail": "No entry #999."})
        assert [m["note"] for m in page.get("/api/ext/demo/marks").json()] == ["Again"]
        assert page.get("/api/ext/demo/settings").json() == {"engine_depth": 13}
    assert webcheck.problems(PACKAGE / "web", app, prefix="demo") == []

    # Backed up with Blunderbook's database, and restored on its own.
    assert "Backed up the demo extension's database to" in invoke("backup")
    (taken,) = backup.list_backups(db_file.parent / "backups", ext.store(ext_demo()))
    with TestClient(app, base_url=URL) as page:
        page.post("/api/ext/demo/marks", json={"blunder_id": ids[1], "note": "Later"})
    assert marks(demo_db) == ["Again", "Later"]
    assert "Restored" in invoke("restore", taken.path.name, "--yes")
    assert marks(demo_db) == ["Again"]

    # Your Log: read, never changed. The demo's table is in its own file only.
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert "marks" not in connection.table_names(conn)
        assert conn.execute("SELECT count(*) FROM blunders").fetchone()[0] == 3

    # Turned off: no tab, its data kept.
    assert "Its data stays" in invoke("ext", "disable", "demo")
    output, app = serve()
    assert "Extensions:" not in output
    with TestClient(app, base_url=URL) as page:
        assert page.get("/api/extensions").json() == []
        assert page.get("/api/ext/demo/marks").status_code == 404
    assert marks(demo_db) == ["Again"]


def ext_demo() -> ext.Extension:
    point = ext.find("demo")
    assert point is not None
    extension, problem = ext.load_one(point)
    assert problem is None and extension is not None
    return extension


# ---------------------------------------------------------------- the boundary


def test_the_demo_uses_only_the_host_api() -> None:
    assert ext.boundary_problems(PACKAGE) == []


def test_the_boundary_check_finds_other_imports(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "import blunderbook.config\n"
        "from blunderbook import config, host\n"
        "from blunderbook.db import repo\n"
        "from blunderbook.core.models import Entry\n"
        "from blunderbook.core import detect\n"
        "from . import routes\n"
        "import blunderbook_other\n"
    )
    assert ext.boundary_problems(tmp_path) == [
        "bad.py:1 imports blunderbook.config, which isn't part of the host API",
        "bad.py:2 imports blunderbook.config, which isn't part of the host API",
        "bad.py:3 imports blunderbook.db, which isn't part of the host API",
    ]


def test_core_never_imports_an_extension() -> None:
    """Principle 7: extensions are found through entry points, never imported by name."""
    for path in CORE_PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names: list[Any] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith("blunderbook_"), (path, name)


# The page modules CLAUDE.md §15 promises extensions, with the names they may import.
HOST_PAGE_EXPORTS = {
    "api.js": ("api", "ApiError"),
    "ui.js": ("esc", "toast", "showError"),
    "format.js": ("fmtDate", "fmtEval", "fmtClock", "MARK", "moveLabel", "percent"),
    "board.js": ("renderBoard", "fenToBoard", "squareLabel", "sqIdx", "sqName", "uciSquares"),
}


@pytest.mark.parametrize("module", sorted(HOST_PAGE_EXPORTS))
def test_the_host_page_modules_keep_their_exports(module: str) -> None:
    text = (webcheck.HOST_WEB / "js" / module).read_text("utf-8")
    for name in HOST_PAGE_EXPORTS[module]:
        assert re.search(rf"^export (?:async )?(?:function|const|class) {name}\b", text, re.M), (
            module,
            name,
        )


# ---------------------------------------------------------------- the shared CSS classes


def test_the_page_keeps_the_shared_classes() -> None:
    """Every class CLAUDE.md §15 lets an extension use is still styled by app.css."""
    css = (webcheck.HOST_WEB / "css" / "app.css").read_text("utf-8")
    defined = webcheck._classes(css, css=True)
    assert sorted(webcheck.SHARED_CLASSES - defined) == []


def test_the_class_check_finds_other_classes(tmp_path: Path) -> None:
    (tmp_path / "view.js").write_text(
        "export function show(root) {\n"
        '  root.innerHTML = `<div class="panel demo-list ${x ? "a" : "b"}"><p class="log">`;\n'
        '  root.firstChild.className = "rt stray";\n'
        "}\n",
        "utf-8",
    )
    (tmp_path / "view.css").write_text(
        "/* .commented-out */\n.demo{color:red}\n"
        "@media (max-width:480px){.demo .pill,.list{margin:0}}\n",
        "utf-8",
    )
    app = create_app(tmp_path / "blunderbook.db")
    assert webcheck.problems(tmp_path, app, prefix="demo") == [
        "view.css: class 'list' is neither shared nor demo-...",
        "view.js: class 'log' is neither shared nor demo-...",
        "view.js: class 'stray' is neither shared nor demo-...",
    ]
