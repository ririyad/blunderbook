"""Checks for page files, without running them (CLAUDE.md §12, §15). There's no JavaScript
test runner, so these catch what would otherwise be a blank tab: an import that doesn't
resolve, a call to an ``/api`` path that doesn't exist, or code the page's
Content-Security-Policy would block.

Blunderbook's own tests run them on ``web/``; an extension's tests run them on its page
folder with the app it's mounted in::

    app = create_app(db, [extension])
    assert webcheck.problems(ext.web_folder(extension), app, prefix=extension.name) == []

With ``prefix``, it also checks the page's CSS classes: each one is the extension's own
(``library``, ``library-row``) or one of the page's shared ones (:data:`SHARED_CLASSES`).
"""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from fastapi import FastAPI

HOST_WEB = Path(__file__).parent / "web"

# `import ... from "./x.js"` and `import "./x.js"`
IMPORT = re.compile(r"""^\s*import\s+(?:[^"';]+?\s+from\s+)?["']([^"']+)["']""", re.MULTILINE)
# `/api/blunders`, `/api/blunders/${id}`, `/api/ext/notes/notes`; a path parameter matches
# any `${...}`.
API_CALL = re.compile(r"""["'`](/api/[a-z0-9/_-]+(?:\$\{[^}]+\}[a-z0-9/_-]*)*)""")
PARAM = re.compile(r"\$\{[^}]+\}|\{\w+\}")
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\ssrc=)[^>]*>")
INLINE_HANDLER = re.compile(r"<[^>]*\son[a-z]+\s*=")  # onclick="..."
REMOTE_URL = re.compile(r"(?:https?:)?//[\w.-]+\.\w+")
W3 = "http://www.w3.org"  # SVG namespaces, never fetched
SHOW = re.compile(r"^export\s+(?:async\s+)?function\s+show\s*\(", re.MULTILINE)
# class="panel detail" in markup; a `${...}` part is left out (it's worked out when it runs).
CLASS_ATTR = re.compile(r"""\bclass(?:Name)?\s*=\s*["'`]([^"'`]*)["'`]""")
TEMPLATE_PART = re.compile(r"\$\{[^}]*\}")
CSS_CLASS = re.compile(r"\.(-?[a-zA-Z_][\w-]*)")
# Comments and declarations: the innermost {...}, so selectors inside @media stay.
CSS_SKIP = re.compile(r"/\*.*?\*/|\{[^{}]*\}", re.DOTALL)

# The page's own CSS classes an extension's page may use, so its tab looks like the rest
# (CLAUDE.md §15). A test checks app.css keeps each one. Anything else an extension styles
# starts with its name.
SHARED_CLASSES: Final = frozenset(
    {
        # panels, text and links
        "panel", "empty", "small", "sr", "gback", "head", "meta", "sec",
        # buttons and pills
        "btn", "primary", "ghost", "danger", "pill", "p-new", "p-due", "p-solved", "p-missed",
        "p-blunder",
        # a board with step controls (the Log and the game page)
        "detail", "boardwrap", "board", "nav", "grp", "icon", "navlabel", "legend", "l-played",
        "l-best", "l-sel", "side", "white", "black",
        # a move list
        "mlist", "mbtn", "mempty", "no", "bad",
        # a puzzle (Re-test's layout)
        "rt", "prompt", "q", "boardnote", "rtprog", "feedback", "on", "ok", "lesson",
        "rt-actions", "queue", "rt-empty",
    }
)  # fmt: skip


def problems(
    folder: Path, app: FastAPI, *, view: bool = True, prefix: str | None = None
) -> list[str]:
    """Everything wrong with the page files in ``folder``, as plain lines; [] when they're
    fine. ``view`` also asks for a view.js that exports ``show(root, rest)``. ``prefix`` (an
    extension's name) checks its CSS classes are its own or shared."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    found: list[str] = []
    if view:
        found += _view_problems(folder)
    known = routes(app)
    for path in files:
        name = path.relative_to(folder).as_posix()
        if path.suffix not in (".html", ".js", ".css", ".svg"):
            continue
        text = path.read_text("utf-8")
        found += [f"{name}: loads {url} from elsewhere" for url in _remote(text)]
        if path.suffix == ".html" and INLINE_SCRIPT.search(text):
            found.append(f"{name}: an inline <script> (the CSP blocks it)")
        if path.suffix in (".html", ".js") and INLINE_HANDLER.search(text):
            found.append(f"{name}: an on...= handler in HTML (the CSP blocks it)")
        if prefix is not None:
            found += [
                f"{name}: class {c!r} is neither shared nor {prefix}-..."
                for c in sorted(_classes(text, css=path.suffix == ".css"))
                if c not in SHARED_CLASSES and c != prefix and not c.startswith(prefix + "-")
            ]
        if path.suffix == ".js":
            found += [f"{name}: {p}" for p in _import_problems(path, folder)]
            for called in API_CALL.findall(text):
                if PARAM.sub("{}", called).rstrip("/") not in known:
                    found.append(f"{name}: calls {called}, which isn't a route")
    return found


def routes(app: FastAPI) -> set[str]:
    """The app's paths with each parameter as ``{}``: ``/api/blunders/{}``."""
    return {PARAM.sub("{}", path) for path in app.openapi()["paths"]}


def _view_problems(folder: Path) -> list[str]:
    view = folder / "view.js"
    if not view.is_file():
        return ["view.js is missing"]
    if not SHOW.search(view.read_text("utf-8")):
        return ["view.js doesn't export a function show(root, rest)"]
    return []


def _classes(text: str, *, css: bool) -> set[str]:
    """The class names a file uses: in a stylesheet's selectors, or in markup's class
    attributes, leaving out the parts worked out when it runs."""
    if css:
        selectors = CSS_SKIP.sub(" ", text)
        return {c for c in CSS_CLASS.findall(selectors) if not c[0].isdigit()}
    names: set[str] = set()
    for value in CLASS_ATTR.findall(TEMPLATE_PART.sub(" ", text)):
        names.update(value.split())
    return names


def _remote(text: str) -> Iterable[str]:
    return sorted(set(REMOTE_URL.findall(text)) - {W3})


def _import_problems(path: Path, folder: Path) -> list[str]:
    """Imports are relative files inside ``folder``, or the host's own modules by absolute
    path (``/js/board.js``)."""
    found = []
    for target in IMPORT.findall(path.read_text("utf-8")):
        if not target.endswith(".js"):
            found.append(f"imports {target}, which isn't a .js file")
        elif target.startswith("/js/"):
            if not (HOST_WEB / target.removeprefix("/")).is_file():
                found.append(f"imports {target}, which Blunderbook doesn't have")
        elif target.startswith(("./", "../")):
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(folder.resolve()):
                found.append(f"imports {target}, which is outside its folder")
            elif not resolved.is_file():
                found.append(f"imports {target}, which doesn't exist")
        else:
            found.append(f"imports {target}: use ./relative paths, or /js/ for Blunderbook's")
    return found
