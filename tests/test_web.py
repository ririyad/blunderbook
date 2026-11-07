"""The web page shell (CLAUDE.md §11): served by the app, no dependencies, nothing from
elsewhere, and every file it loads is there. The page's own behaviour is checked by hand in
a browser (there's no JavaScript toolchain, by design)."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from blunderbook.api.app import CONTENT_SECURITY_POLICY, WEB, create_app
from blunderbook.api.jobs import GameStatus
from blunderbook.api.schemas import (
    AiOut,
    AttemptOut,
    CauseCountOut,
    EntryOut,
    EntryRefOut,
    EntrySummary,
    ExplanationOut,
    FenOut,
    GameOut,
    ImportGameOut,
    ImportJobOut,
    ImportStarted,
    MoveOut,
    PatternsOut,
    PromptOut,
    RetestedOut,
    RetestItem,
    RetestQueue,
    SourceCountOut,
    SpeedCountOut,
)
from blunderbook.core.models import CAUSES

URL = "http://127.0.0.1"
VIEWS = {"log": "log", "retest": "retest", "patterns": "patterns", "import": "importView"}
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
    for view in VIEWS:
        assert f'href="#{view}"' in page
        assert f'id="view-{view}"' in page
    assert 'id="dueBadge"' in page


def test_no_add_games_button() -> None:
    """Games are added on the Import tab (CLAUDE.md §11), not from a header button."""
    page = (WEB / "index.html").read_text("utf-8")
    assert "Add games" not in page


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
    for view, name in VIEWS.items():  # `import` is a reserved word
        assert (WEB / "js" / "views" / f"{view}.js").is_file()
        assert f'import * as {name} from "./views/{view}.js";' in router
        assert f"{view}: {name}" in router or view == name


def test_design_colours_come_from_the_spec() -> None:
    """The palette in CLAUDE.md §11."""
    css = (WEB / "css" / "app.css").read_text("utf-8")
    for colour in ("#f7f5f0", "#1b1b1b", "#5c5c5c", "#e3dfd6", "#b83227", "#1d7a52", "#9a6412"):
        assert colour in css
    assert "#2a5d9f" in css and "--light:#ebe9d8" in css and "--dark:#4c688d" in css
    assert "Georgia" in css


def luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def test_board_coordinates_are_readable() -> None:
    """Each square's coordinate is drawn in the other square's colour: at least 4.5:1."""
    light, dark = sorted((luminance("#ebe9d8"), luminance("#4c688d")), reverse=True)
    assert (light + 0.05) / (dark + 0.05) >= 4.5


# ---------------------------------------------------------------- the pieces

PIECE_NAMES = [c + k for c in "wb" for k in "KQRBNP"]


@pytest.mark.parametrize("name", PIECE_NAMES)
def test_every_piece_is_drawn(client: TestClient, name: str) -> None:
    response = client.get(f"/pieces/{name}.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    colour = "white" if name[0] == "w" else "black"
    kind = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight", "P": "pawn"}
    assert response.text.startswith("<svg ")
    assert f'class="{colour} {kind[name[1]]}"' in response.text


@pytest.mark.parametrize("name", ["wX", "WK", "k", "wK.png", "..%2Fapp"])
def test_no_other_pieces(client: TestClient, name: str) -> None:
    assert client.get(f"/pieces/{name}.svg").status_code == 404


def test_the_board_asks_for_those_pieces() -> None:
    """board.js builds `/pieces/wK.svg`-style names; no Unicode glyphs are left."""
    board = (WEB / "js" / "board.js").read_text("utf-8")
    assert '`/pieces/${isWhite(piece) ? "w" : "b"}${piece.toUpperCase()}.svg`' in board
    assert not re.search("[\u2654-\u265f]", board)


def test_other_hosts_get_no_pieces(db_file: Path) -> None:
    with TestClient(create_app(db_file), base_url="http://evil.example") as other:
        assert other.get("/pieces/wK.svg").status_code == 400


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
IMPORT_JS = WEB / "js" / "views" / "import.js"
EXPLAIN_JS = WEB / "js" / "explain.js"


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
        (IMPORT_JS, r"\bstarted\.(\w+)", (ImportStarted,)),
        (IMPORT_JS, r"\bjob\.(\w+)", (ImportJobOut,)),
        (IMPORT_JS, r"\bg\.(\w+)", (ImportGameOut,)),
        (IMPORT_JS, r"\ben\.(\w+)", (EntryRefOut,)),
        (IMPORT_JS, r"\bout\.(\w+)", (FenOut,)),
        (EXPLAIN_JS, r"\bsaved\.(\w+)", (ExplanationOut,)),
        (EXPLAIN_JS, r"\bai\.(\w+)", (AiOut,)),
        (EXPLAIN_JS, r"\bprompt\.(\w+)", (PromptOut,)),
    ],
    ids=[
        "queue item",
        "queue",
        "attempt",
        "patterns",
        "cause",
        "source/speed",
        "history",
        "import started",
        "import job",
        "import game",
        "import entry",
        "fen",
        "explanation",
        "ai",
        "prompt",
    ],
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


# `/api/blunders`, `/api/blunders/${id}`, `/api/retest/${item.id}/attempt`; a path parameter
# matches any `${...}`.
PARAM = re.compile(r"\$\{[^}]+\}|\{\w+\}")
API_CALL = re.compile(r"""["'`](/api/[a-z/]+(?:\$\{[^}]+\}[a-z/]*)*)""")


def test_page_calls_only_routes_that_exist(db_file: Path) -> None:
    paths = create_app(db_file).openapi()["paths"]  # "/api/blunders/{blunder_id}", ...
    routes = {PARAM.sub("{}", route) for route in paths}
    seen = set()
    for path in JS_FILES:
        for called in API_CALL.findall(path.read_text("utf-8")):
            route = PARAM.sub("{}", called).rstrip("/")
            assert route in routes, (served(path), called)
            seen.add(route)
    assert {
        "/api/retest/queue",
        "/api/retest/{}/attempt",
        "/api/retest/{}/hint",
        "/api/patterns",
        "/api/import",
        "/api/import/{}",
        "/api/fen",
        "/api/ai",
        "/api/blunders/{}/explanation",
        "/api/blunders/{}/explanation/prompt",
    } <= seen


def test_no_inline_handlers_in_scripts() -> None:
    """HTML built in JavaScript can't use onclick= either: the CSP blocks it."""
    for path in JS_FILES:
        assert not re.search(r"<[^>]*\son[a-z]+\s*=", path.read_text("utf-8")), served(path)


def test_empty_states_point_to_the_import_tab_and_the_cli() -> None:
    copy = (
        'Import a PGN on the <a href="#import">Import</a> tab, or with '
        "<code>blunderbook import FILE.pgn</code>."
    )
    for path in (LOG_JS, RETEST_JS, PATTERNS_JS):
        assert copy in path.read_text("utf-8"), served(path)
    text = LOG_JS.read_text("utf-8")
    assert "Add games" not in text
    assert "No blunders match these filters." in text  # the demo's copy


# ---------------------------------------------------------------- the Import view (5.3)


def test_import_sends_the_pgn_as_bytes_of_its_own_type() -> None:
    """The import route takes only application/x-chess-pgn (CLAUDE.md §10): a file goes as its
    bytes, so the server reads its encoding."""
    text = IMPORT_JS.read_text("utf-8")
    assert 'const PGN_TYPE = "application/x-chess-pgn";' in text
    assert 'api("/api/import", { method: "POST", data, type: PGN_TYPE })' in text
    assert "readAsText" not in text and "file.text()" not in text
    api_js = (WEB / "js" / "api.js").read_text("utf-8")
    assert 'init.headers["Content-Type"] = options.type;' in api_js


def test_import_view_copy() -> None:
    text = IMPORT_JS.read_text("utf-8")
    for copy in (
        "Paste PGN here, or drop a .pgn file on this box.",
        "Choose .pgn file",
        ">Import</button>",
        "Quick entry from a FEN",
        'aria-live="polite"',
        'role="progressbar"',
    ):
        assert copy in text, copy
    assert "entriesChanged()" in text
    assert "!" not in re.sub(r"!==?|!\w|!\(", "", text)  # no exclamation marks in the copy


def test_import_report_knows_every_game_status() -> None:
    """A status the page has no pill for would show its raw name."""
    statuses = set(get_args(GameStatus))
    pills = set(re.findall(r"^  (\w+): \[", IMPORT_JS.read_text("utf-8"), re.MULTILINE))
    assert pills == statuses


def test_explanation_is_shown_in_the_log_and_after_a_re_test_only() -> None:
    """The Log and the Re-test result pass the saved explanation on; the queue item can't
    carry one (CLAUDE.md §10)."""
    assert "showExplanation(" in LOG_JS.read_text("utf-8")
    retest = RETEST_JS.read_text("utf-8")
    assert "showExplanation(fb.querySelector" in retest
    assert "r.explanation" in retest and "item.explanation" not in retest
