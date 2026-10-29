"""First-week level check routes (feature 4). Teacher JWT, tenant-scoped through `owned_class`.

Contract: docs/teacher_loop_contract.md ("Backend-Manage"). No AI: the teacher judges each item,
code applies the stop rule and records the placement (`services/level_check.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_teacher, owned_child, owned_class
from app.api.teacher import _remember, _replayed, _subject
from app.services import prefs
from app.db import get_db
from app.models.tables import Teacher
from app.services import level_check as lc

router = APIRouter(prefix="/v1")

# Replay markers reuse the probe kind (a level check is a run of guided probes), so they stay out of
# the /ai_activity capture counts; the "lc:" prefix keeps them apart from single-probe client ids.
_REPLAY_KIND = "probe"


def _ladder(subject: str, lang: str = "hi") -> dict:
    lad = lc.ladder_in(subject, lang)
    if lad is None:
        raise HTTPException(422, f"no level check for subject '{subject}'")
    return lad


@router.get("/classes/{class_id}/level_check")
def get_level_check(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    subject = _subject(subject, db, teacher)
    return lc.class_view(db, cls, subject, _ladder(subject, prefs.content_lang_for(db, teacher=teacher)))


class LevelResultIn(BaseModel):
    level_key: str = Field(max_length=24)
    passed: bool


class LevelCheckIn(BaseModel):
    subject: str
    child_id: int
    results: list[LevelResultIn] = Field(max_length=20)
    client_uuid: str | None = Field(default=None, max_length=200)


@router.post("/classes/{class_id}/level_check")
def post_level_check(class_id: int, body: LevelCheckIn, teacher: Teacher = Depends(current_teacher),
                     db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    replay_id = f"lc:{body.client_uuid}" if body.client_uuid else None
    if (done := _replayed(db, teacher, _REPLAY_KIND, replay_id)) is not None:
        return done
    subject = _subject(body.subject, db, teacher)
    lad = _ladder(subject, prefs.content_lang_for(db, teacher=teacher))
    ch = owned_child(body.child_id, teacher, db)
    if ch.class_id != cls.id or not ch.active:
        raise HTTPException(422, "child not in this class")
    results = [(r.level_key, r.passed) for r in body.results]
    try:
        lc.placement(lad, results)
    except lc.LadderError as e:
        raise HTTPException(422, str(e))
    marker = _remember(db, cls, teacher, _REPLAY_KIND, replay_id, {}) if replay_id else None
    out = lc.record(db, cls, ch, teacher, subject, lad, results, session_id=marker.id if marker else None)
    if marker:
        marker.status = "confirmed"
        marker.payload = {**marker.payload, "response": out}
    return out
