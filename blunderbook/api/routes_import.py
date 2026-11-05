"""Web import and FEN quick entry (CLAUDE.md §10, "Web import"). The work is in
``importer.py``, shared with the CLI; ``jobs.py`` runs it in the background."""

from dataclasses import asdict
from datetime import date
from typing import Final

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from blunderbook import config

from .common import Db
from .jobs import Busy, CantStart, ImportJobs
from .schemas import FenIn, FenOut, ImportJobOut, ImportStarted

PGN_TYPE: Final = "application/x-chess-pgn"
MAX_BYTES: Final = 10 * 1024 * 1024
TOO_BIG: Final = "That's more than 10 MB of PGN. Split it, or use blunderbook import FILE."

router = APIRouter(prefix="/api", tags=["import"])


def jobs(request: Request) -> ImportJobs:
    found: ImportJobs = request.app.state.jobs
    return found


def same_origin(request: Request) -> None:
    """Only the page itself may start an import. Browsers send ``Origin`` with every POST;
    a request without one isn't from a web page."""
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        raise HTTPException(status_code=403, detail="Only the Blunderbook page can do this.")


@router.post("/import", status_code=202)
async def start_import(request: Request) -> ImportStarted:
    """Start importing the PGN sent as the body (its raw bytes, like a .pgn file)."""
    same_origin(request)
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind != PGN_TYPE:
        raise HTTPException(status_code=415, detail=f"Send the PGN as {PGN_TYPE}.")
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=TOO_BIG)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail=TOO_BIG)
    try:
        job = await run_in_threadpool(jobs(request).start, bytes(data))
    except Busy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CantStart as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    except config.ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return ImportStarted(job_id=job.id)


@router.get("/import/{job_id}")
def import_status(job_id: str, request: Request) -> ImportJobOut:
    job = jobs(request).get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="That import isn't known. It may be from before the server restarted.",
        )
    return ImportJobOut.model_validate(asdict(job.view()))


@router.post("/fen")
def fen_entry(body: FenIn, request: Request, conn: Db) -> FenOut:
    """Log one position and the move you played, as `blunderbook fen` does."""
    same_origin(request)
    try:
        outcome, notes = jobs(request).log_fen(
            conn, body.fen, body.move, body.opponent, body.date or date.today()
        )
    except Busy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CantStart as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    except config.ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return FenOut(
        result=outcome.result, message=outcome.message, entry_id=outcome.entry_id, notes=notes
    )
