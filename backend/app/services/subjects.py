"""Subject keys a school can use: the two built-in ones plus subjects a teacher adds.

`resolve_subject` is the single gate every teacher route uses (see `_subject` in api/teacher.py).
Keys are lowercase slugs of at most 16 characters (`Roadmap.subject` / `Plan.subject` are String(16)).
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.content import get_content

ALIASES = {"math": "numeracy", "maths": "numeracy", "ganit": "numeracy",
           "hindi": "literacy", "reading": "literacy"}


def custom_subject_keys(db: Session, school_id: int) -> list[str]:
    """Subjects this school added itself. The syllabus work extends this."""
    return []


def resolve_subject(db: Session, school_id: int, subject: str) -> str:
    s = (subject or "").strip().lower()
    s = ALIASES.get(s, s)
    if s in get_content().subjects or s in custom_subject_keys(db, school_id):
        return s
    raise HTTPException(422, f"unknown subject '{subject}'")
