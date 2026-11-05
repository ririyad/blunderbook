"""The local web app (CLAUDE.md §10): FastAPI, JSON under ``/api``.

``blunderbook serve`` binds it to 127.0.0.1 only and opens the database first (upgrade and
daily backup). Each request opens its own connection. The web page arrives in 3.2.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from blunderbook import __version__
from blunderbook.db.connection import StorageError

from . import routes_blunders

# Only these Host headers are answered. A web page elsewhere can't reach the API by
# pointing its own domain name at 127.0.0.1 (DNS rebinding): there's no login to stop it.
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def create_app(db_path: Path) -> FastAPI:
    # The /docs pages load their scripts from a CDN, so they're off: the app stays offline.
    app = FastAPI(title="Blunderbook", version=__version__, docs_url=None, redoc_url=None)
    app.state.db_path = db_path
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.include_router(routes_blunders.router)

    @app.exception_handler(StorageError)
    def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app
