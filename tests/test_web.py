"""The web page shell (CLAUDE.md §11): served by the app, no dependencies, nothing from
elsewhere, and every file it loads is there. The page's own behaviour is checked by hand in
a browser (there's no JavaScript toolchain, by design)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blunderbook.api.app import CONTENT_SECURITY_POLICY, WEB, create_app

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
