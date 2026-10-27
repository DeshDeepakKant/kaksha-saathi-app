"""Subject keys a school can use: the two built-in ones plus subjects a teacher adds.

`resolve_subject` is the single gate every teacher route uses (see `_subject` in api/teacher.py).
Keys are lowercase slugs of at most 16 characters (`Roadmap.subject` / `Plan.subject` are String(16)).
"""
from __future__ import annotations

import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import CustomSubject
from app.services.content import get_content

ALIASES = {"math": "numeracy", "maths": "numeracy", "ganit": "numeracy",
           "hindi": "literacy", "reading": "literacy"}


BUILTIN_NAMES = {"numeracy": ("Maths", "गणित"), "literacy": ("Hindi", "हिन्दी")}
KEY_MAX = 16


def custom_subject_keys(db: Session, school_id: int) -> list[str]:
    """Subjects this school added itself, oldest first."""
    return list(db.scalars(select(CustomSubject.key).where(CustomSubject.school_id == school_id)
                           .order_by(CustomSubject.id)))


def slugify(name: str) -> str:
    """Lowercase ASCII slug of at most 16 chars; a name with no Latin letters gets a stable hash key."""
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")[:KEY_MAX].strip("_")
    return s or "s_" + hashlib.sha1(name.strip().encode("utf-8")).hexdigest()[:6]


def create_custom_subject(db: Session, school_id: int, name: str, name_hi: str | None = None) -> CustomSubject:
    """Add a subject for the school. Same name twice or a built-in name is a 409; two different
    names that slug the same get a numeric suffix so each keeps its own key."""
    name = " ".join(name.split())
    key = slugify(name)
    reserved = set(BUILTIN_NAMES) | set(ALIASES)
    existing = list(db.scalars(select(CustomSubject).where(CustomSubject.school_id == school_id)))
    builtin_names = {n.lower() for pair in BUILTIN_NAMES.values() for n in pair}
    if key in reserved or name.lower() in builtin_names:
        raise HTTPException(409, "that is a built-in subject")
    if any(e.name_en.lower() == name.lower() for e in existing):
        raise HTTPException(409, "subject already exists")
    taken = {e.key for e in existing} | reserved
    base, n = key, 1
    while key in taken:
        n += 1
        suffix = f"_{n}"
        key = base[:KEY_MAX - len(suffix)].rstrip("_") + suffix
    row = CustomSubject(school_id=school_id, key=key, name_en=name,
                        name_hi=" ".join((name_hi or "").split()) or name)
    db.add(row)
    db.flush()
    return row


def subject_names(db: Session, school_id: int) -> list[dict]:
    """Built-ins first, then the school's own, as `{key, name_en, name_hi, builtin}`."""
    out = [{"key": k, "name_en": en, "name_hi": hi, "builtin": True} for k, (en, hi) in BUILTIN_NAMES.items()]
    for r in db.scalars(select(CustomSubject).where(CustomSubject.school_id == school_id)
                        .order_by(CustomSubject.id)):
        out.append({"key": r.key, "name_en": r.name_en, "name_hi": r.name_hi, "builtin": False})
    return out


def resolve_subject(db: Session, school_id: int, subject: str) -> str:
    s = (subject or "").strip().lower()
    s = ALIASES.get(s, s)
    if s in get_content().subjects or s in custom_subject_keys(db, school_id):
        return s
    raise HTTPException(422, f"unknown subject '{subject}'")
