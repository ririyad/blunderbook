"""The web page shell (CLAUDE.md §11): served by the app, no dependencies, nothing from
elsewhere, and every file it loads is there. The page's own behaviour is checked by hand in
a browser (there's no JavaScript toolchain, by design)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from blunderbook.api.app import CONTENT_SECURITY_POLICY, WEB, create_app
from blunderbook.api.schemas import (
    AttemptOut,
    CauseCountOut,
    EntryOut,
    EntrySummary,
    GameOut,
    MoveOut,
    PatternsOut,
    RetestedOut,
    RetestItem,
    RetestQueue,
    SourceCountOut,
    SpeedCountOut,
)
from blunderbook.core.models import CAUSES

URL = "http://127.0.0.1"
WEB_FILES = sorted(p for p in WEB.rglob("*") if p.is_file())
JS_FILES = [p for p in WEB_FILES if p.suffix == ".js"]
# `import ... from "./x.js"` and `import "./x.js"`
IMPORT = re.compile(r"""^\s*import\s+(?:[^"';]+?\s+from\s+)?["']([^"']+)["']""", re.MULTILINE)


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file), base_url=URL) as test_client:
        yield test_client


def served(path: Path) -> str:
    return "/" + path.relative_to(WEB).as_posix()


def test_the_page_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert '<script type="module" src="js/app.js"></script>' in page
    assert '<link rel="stylesheet" href="css/app.css">' in page
    for view in ("log", "retest", "patterns"):
        assert f'href="#{view}"' in page
        assert f'id="view-{view}"' in page
    assert 'id="dueBadge"' in page


def test_no_import_view_or_add_button() -> None:
    """Imports run on the CLI (CLAUDE.md §11)."""
    page = (WEB / "index.html").read_text("utf-8")
    assert "Add games" not in page
    assert "#import" not in page
    assert "view-import" not in page


@pytest.mark.parametrize("path", WEB_FILES, ids=lambda p: served(p))
def test_every_file_is_served_with_its_type(client: TestClient, path: Path) -> None:
    response = client.get(served(path))
    assert response.status_code == 200
    expected = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
    assert response.headers["content-type"].startswith(expected[path.suffix])


def test_page_headers(client: TestClient) -> None:
    for path in ("/", "/js/app.js", "/css/app.css"):
        headers = client.get(path).headers
        assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert headers["cache-control"] == "no-cache"
        assert headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY


def test_page_files_load_nothing_from_elsewhere() -> None:
    """No CDN, no web fonts, no chess.js: the app works offline (CLAUDE.md §1, §3)."""
    for path in WEB_FILES:
        text = path.read_text("utf-8")
        urls = set(re.findall(r"(?:https?:)?//[\w.-]+\.\w+", text)) - {"http://www.w3.org"}
        assert not urls, f"{served(path)} refers to {urls}"
        assert "chess.js" not in text.lower(), served(path)
    assert not any(p.name.lower() in ("chess.js", "package.json") for p in WEB_FILES)


def test_no_inline_scripts() -> None:
    """The Content-Security-Policy only runs our own script files."""
    for path in WEB_FILES:
        if path.suffix == ".html":
            text = path.read_text("utf-8")
            assert re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", text) == [], served(path)
            assert not re.search(r"\son[a-z]+\s*=", text), served(path)  # onclick="..."


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: served(p))
def test_module_imports_resolve(path: Path) -> None:
    """Every `import` names a relative .js file that exists (a typo would be a blank page)."""
    for target in IMPORT.findall(path.read_text("utf-8")):
        assert target.startswith("./") or target.startswith("../"), (served(path), target)
        assert target.endswith(".js"), (served(path), target)
        assert (path.parent / target).resolve().is_file(), (served(path), target)


def test_routes_have_views() -> None:
    """Each tab's view module exists, and the router knows it."""
    router = (WEB / "js" / "app.js").read_text("utf-8")
    for view in ("log", "retest", "patterns"):
        assert (WEB / "js" / "views" / f"{view}.js").is_file()
        assert f'import * as {view} from "./views/{view}.js";' in router


def test_design_colours_come_from_the_spec() -> None:
    """The palette in CLAUDE.md §11."""
    css = (WEB / "css" / "app.css").read_text("utf-8")
    for colour in ("#f7f5f0", "#1b1b1b", "#5c5c5c", "#e3dfd6", "#b83227", "#1d7a52", "#9a6412"):
        assert colour in css
    assert "#2a5d9f" in css and "#ece6d9" in css and "#a99f8b" in css
    assert "Georgia" in css


def test_api_still_comes_first(client: TestClient) -> None:
    assert client.get("/api/blunders").status_code == 503  # no database yet, but it's the API
    missing = client.get("/api/nothing-here")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert client.get("/nothing-here.js").status_code == 404


def test_other_hosts_get_no_page(db_file: Path) -> None:
    with TestClient(create_app(db_file), base_url="http://evil.example") as other:
        assert other.get("/").status_code == 400
        assert other.get("/js/app.js").status_code == 400


# ---------------------------------------------------------------- the Log view (3.3)

LOG_JS = WEB / "js" / "views" / "log.js"


def test_cause_list_matches_the_core() -> None:
    """The page's chips and filter use the same fixed list, in the same order (§5)."""
    text = (WEB / "js" / "causes.js").read_text("utf-8")
    body = text[text.index("[") : text.index("]")]
    assert tuple(re.findall(r'"([^"]+)"', body)) == CAUSES


def fields_read(pattern: str, path: Path = LOG_JS) -> set[str]:
    return set(re.findall(pattern, path.read_text("utf-8")))


@pytest.mark.parametrize(
    ("pattern", "model"),
    [
        (r"\b(?:e|entry)\.(\w+)", EntryOut),
        (r"\b(?:g|e\.game)\.(\w+)", GameOut),
        (r"\bitem\.(\w+)", EntrySummary),
        (r"\bm\.(\w+)", MoveOut),
    ],
    ids=["entry", "game", "summary", "move"],
)
def test_log_reads_only_fields_the_api_sends(pattern: str, model: type[BaseModel]) -> None:
    """There's no JavaScript test runner, so this catches a misspelt field (a blank cell)."""
    used = fields_read(pattern)
    assert used, "the pattern found nothing"
    assert used <= set(model.model_fields), used - set(model.model_fields)


RETEST_JS = WEB / "js" / "views" / "retest.js"
PATTERNS_JS = WEB / "js" / "views" / "patterns.js"


@pytest.mark.parametrize(
    ("path", "pattern", "models"),
    [
        (RETEST_JS, r"\bitem\.(\w+)", (RetestItem,)),
        (RETEST_JS, r"\bdata\.(\w+)", (RetestQueue,)),
        (RETEST_JS, r"\br\.(\w+)", (AttemptOut,)),
        (PATTERNS_JS, r"\bp\.(\w+)", (PatternsOut,)),
        (PATTERNS_JS, r"\bc\.(\w+)", (CauseCountOut,)),
        (PATTERNS_JS, r"\bs\.(\w+)", (SourceCountOut, SpeedCountOut)),
        (PATTERNS_JS, r"\br\.(\w+)", (RetestedOut,)),
    ],
    ids=["queue item", "queue", "attempt", "patterns", "cause", "source/speed", "history"],
)
def test_views_read_only_fields_the_api_sends(
    path: Path, pattern: str, models: tuple[type[BaseModel], ...]
) -> None:
    used = fields_read(pattern, path)
    assert used, "the pattern found nothing"
    known = set().union(*(m.model_fields for m in models))
    assert used <= known, used - known


def test_retest_hides_nothing_it_needs_before_the_attempt() -> None:
    """The queue item is all the board has before you move: the answer only comes from the
    attempt's result (CLAUDE.md §10)."""
    used = fields_read(r"\bitem\.(\w+)", RETEST_JS)
    assert not used & {"best_uci", "accept_uci", "played_uci", "played_san", "lesson"}


# `/api/blunders`, `/api/blunders/${id}`, `/api/retest/${item.id}/attempt`
API_CALL = re.compile(r"""["'`](/api/[a-z/]+(?:\$\{[^}]+\}[a-z/]*)*)""")


def test_page_calls_only_routes_that_exist(db_file: Path) -> None:
    routes = set(create_app(db_file).openapi()["paths"])  # "/api/blunders/{blunder_id}", ...
    seen = set()
    for path in JS_FILES:
        for called in API_CALL.findall(path.read_text("utf-8")):
            route = re.sub(r"\$\{[^}]+\}", "{blunder_id}", called).rstrip("/")
            assert route in routes, (served(path), called)
            seen.add(route)
    assert {
        "/api/retest/queue",
        "/api/retest/{blunder_id}/attempt",
        "/api/retest/{blunder_id}/hint",
        "/api/patterns",
    } <= seen


def test_no_inline_handlers_in_scripts() -> None:
    """HTML built in JavaScript can't use onclick= either: the CSP blocks it."""
    for path in JS_FILES:
        assert not re.search(r"<[^>]*\son[a-z]+\s*=", path.read_text("utf-8")), served(path)


def test_log_empty_state_points_to_the_cli() -> None:
    text = LOG_JS.read_text("utf-8")
    assert "Import a PGN with <code>blunderbook import FILE.pgn</code>." in text
    assert "Add games" not in text
    assert "No blunders match these filters." in text  # the demo's copy
