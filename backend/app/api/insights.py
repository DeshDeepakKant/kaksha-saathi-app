"""Teacher insights: follow-ups (re-check, stuck, missed, not checked, fading) and did-it-work outcomes.

Read-only and deterministic; all computation lives in `services/followups.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_teacher, owned_class
from app.api.teacher import _subject
from app.db import get_db
from app.models.tables import Teacher
from app.services import followups as fu

router = APIRouter(prefix="/v1")


@router.get("/classes/{class_id}/followups")
def class_followups(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    return fu.followups(db, owned_class(class_id, teacher, db), subject)


@router.get("/classes/{class_id}/outcomes")
def class_outcomes(class_id: int, subject: str, days: int = Query(42, ge=1, le=180),
                   teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    return fu.outcomes(db, owned_class(class_id, teacher, db), subject, days)
