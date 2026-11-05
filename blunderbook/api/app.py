"""The local web app (CLAUDE.md §10, §11): JSON under ``/api``, the page from ``web/``.

``blunderbook serve`` binds it to 127.0.0.1 only and opens the database first (upgrade and
daily backup). Each request opens its own connection.
"""

import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import Scope

from blunderbook import __version__
from blunderbook.db.connection import StorageError

from . import routes_blunders, routes_retest

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


class _Web(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(WEB_HEADERS)
        return response


def create_app(db_path: Path) -> FastAPI:
    # Some Windows registries map .js to text/plain, and browsers refuse to run a module
    # served that way. Python reads the registry, so set the types the page needs.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    # The /docs pages load their scripts from a CDN, so they're off: the app stays offline.
    app = FastAPI(title="Blunderbook", version=__version__, docs_url=None, redoc_url=None)
    app.state.db_path = db_path
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.include_router(routes_blunders.router)
    app.include_router(routes_retest.router)
    app.mount("/", _Web(directory=WEB, html=True), name="web")  # last: /api comes first

    @app.exception_handler(StorageError)
    def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app
