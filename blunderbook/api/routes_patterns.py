"""The Patterns route (CLAUDE.md §7.9, §10)."""

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter

from blunderbook.core import patterns
from blunderbook.db import repo

from .common import Db
from .schemas import PatternsOut

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


@router.get("")
def get_patterns(conn: Db) -> PatternsOut:
    found = patterns.compute(repo.list_entries(conn), repo.attempt_stats(conn), date.today())
    return PatternsOut.model_validate(asdict(found))
