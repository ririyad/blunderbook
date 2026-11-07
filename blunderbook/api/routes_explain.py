"""The optional AI explanation (CLAUDE.md §7.10, §10): is it on, what would be sent, and
asking for one. The prompt comes from ``core/explain.py``; ``ai.py`` sends it."""

from fastapi import APIRouter, HTTPException, Request

from blunderbook import ai, config
from blunderbook.core import explain
from blunderbook.db import repo

from .common import Db, explanation_out, found, not_found, same_origin
from .schemas import AiOut, ExplanationOut, PromptOut

router = APIRouter(prefix="/api", tags=["ai"])


def _config() -> config.Config:
    """config.toml, read again on each request: `blunderbook ai on` works without a restart."""
    try:
        return config.load()
    except config.ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/ai")
def ai_status() -> AiOut:
    cfg = _config()
    return AiOut(enabled=config.ai_problem(cfg) is None, model=cfg.ai.model or None)


@router.get("/blunders/{blunder_id}/explanation/prompt")
def prompt(blunder_id: int, conn: Db) -> PromptOut:
    """Exactly what "Explain this blunder" sends, for "What's sent"."""
    entry = found(repo.get_entry(conn, blunder_id), blunder_id)
    built = explain.build_prompt(explain.mistake(entry))
    return PromptOut(model=_config().ai.model or None, system=built.system, user=built.user)


@router.post("/blunders/{blunder_id}/explanation")
def explanation(blunder_id: int, request: Request, conn: Db) -> ExplanationOut:
    """Ask the model for an explanation and save it, replacing the one before. A plain
    ``def``: the call to OpenRouter runs in a worker thread."""
    same_origin(request)
    cfg = _config()
    problem = config.ai_problem(cfg)
    if problem is not None:
        raise HTTPException(status_code=503, detail=problem)
    entry = found(repo.get_entry(conn, blunder_id), blunder_id)
    built = explain.build_prompt(explain.mistake(entry))
    try:
        answer = ai.explain(built, key=cfg.ai.key, model=cfg.ai.model)
    except ai.AiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    saved = repo.save_explanation(
        conn,
        blunder_id,
        text=answer.text,
        model=answer.model,
        prompt_version=explain.PROMPT_VERSION,
    )
    out = explanation_out(saved)
    if out is None:  # deleted while the model was writing
        not_found(blunder_id)
    return out
