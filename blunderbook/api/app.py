"""The local web app (CLAUDE.md §10, §11): JSON under ``/api``, the page from ``web/``.

``blunderbook serve`` binds it to 127.0.0.1 only and opens the database first (upgrade and
daily backup). Each request opens its own connection.
"""

import mimetypes
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import chess
import chess.svg
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import Scope

from blunderbook import __version__, ext
from blunderbook.db.connection import StorageError

from . import routes_blunders, routes_explain, routes_import, routes_patterns, routes_retest
from .jobs import ImportJobs
from .schemas import ExtensionOut

WEB = Path(__file__).parent.parent / "web"

# Only these Host headers are answered. A web page elsewhere can't reach the API by
# pointing its own domain name at 127.0.0.1 (DNS rebinding): there's no login to stop it.
LOCAL_HOSTS = ("127.0.0.1", "localhost")

# The page loads nothing from anywhere else: no CDN, no fonts, no trackers. Scripts only
# from our own files, so text from a PGN or your notes can never run as code.
# Inline style attributes are allowed: the views set widths such as the eval bar's.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)
WEB_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    # Check with the server each time (a cheap 304): a new version's files are used at once.
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


# The board's pieces, drawn as SVG by python-chess (the set the print page uses too), by
# name: "wK" is the white king, "bP" a black pawn. Made here, so no image files are copied in.
PIECES = {
    f"{color}{kind}": chess.svg.piece(
        chess.Piece.from_symbol(kind if color == "w" else kind.lower())
    )
    for color in "wb"
    for kind in "KQRBNP"
}


class _Web(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(WEB_HEADERS)
        return response


def create_app(db_path: Path, extensions: Sequence[ext.Extension] = ()) -> FastAPI:
    """The app for the database at ``db_path``, with ``extensions`` (loaded and checked,
    their databases opened by ``serve``): each one's routes at ``/api/ext/<name>``, and its
    page files at ``/ext/<name>/``, served like the page's own."""
    # Some Windows registries map .js to text/plain, and browsers refuse to run a module
    # served that way. Python reads the registry, so set the types the page needs.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    # The /docs pages load their scripts from a CDN, so they're off: the app stays offline.
    jobs = ImportJobs(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        # Ctrl+C on serve: stop a running import between positions; its engine closes.
        await run_in_threadpool(jobs.stop)

    app = FastAPI(
        title="Blunderbook", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.db_path = db_path
    app.state.jobs = jobs
    app.state.extensions = {extension.name: extension for extension in extensions}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.include_router(routes_blunders.router)
    app.include_router(routes_retest.router)
    app.include_router(routes_patterns.router)
    app.include_router(routes_import.router)
    app.include_router(routes_explain.router)

    pages: list[tuple[ext.Extension, Path]] = []
    for extension in extensions:
        if extension.router is not None:
            app.include_router(extension.router, prefix=f"/api/ext/{extension.name}")
        folder = ext.web_folder(extension)
        if folder is not None:
            pages.append((extension, folder))

    @app.get("/api/extensions")
    def list_extensions() -> list[ExtensionOut]:
        """The extensions with a page, in the order they're turned on: a tab each."""
        return [
            ExtensionOut(name=e.name, title=e.title, css=(folder / "view.css").is_file())
            for e, folder in pages
        ]

    @app.get("/pieces/{name}.svg", include_in_schema=False)
    def piece(name: str) -> Response:
        svg = PIECES.get(name)
        if svg is None:
            raise HTTPException(status_code=404, detail="There's no such piece.")
        return Response(svg, media_type="image/svg+xml", headers=WEB_HEADERS)

    for extension, folder in pages:
        app.mount(f"/ext/{extension.name}", _Web(directory=folder), name=f"ext-{extension.name}")
    app.mount("/", _Web(directory=WEB, html=True), name="web")  # last: /api comes first

    @app.exception_handler(StorageError)
    def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app
