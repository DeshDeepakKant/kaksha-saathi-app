from __future__ import annotations

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db import get_db
from app.models.tables import Child, Classroom, ParentAccount, Teacher


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing token")
    return authorization.split(" ", 1)[1]


def current_teacher(authorization: str | None = Header(default=None),
                    db: Session = Depends(get_db)) -> Teacher:
    try:
        payload = decode_token(_bearer(authorization))
    except Exception:
        raise HTTPException(401, "invalid token")
    if payload.get("kind") != "teacher":
        raise HTTPException(403, "teacher token required")
    t = db.get(Teacher, int(payload["sub"]))
    if not t:
        raise HTTPException(401, "teacher not found")
    return t


def current_parent(authorization: str | None = Header(default=None),
                   db: Session = Depends(get_db)) -> ParentAccount:
    try:
        payload = decode_token(_bearer(authorization))
    except Exception:
        raise HTTPException(401, "invalid token")
    if payload.get("kind") != "parent":
        raise HTTPException(403, "parent token required")
    p = db.get(ParentAccount, int(payload["sub"]))
    if not p:
        raise HTTPException(401, "parent not found")
    return p


def owned_class(class_id: int, teacher: Teacher, db: Session) -> Classroom:
    c = db.get(Classroom, class_id)
    if not c or c.school_id != teacher.school_id:
        raise HTTPException(404, "class not found")
    return c


def owned_child(child_id: int, teacher: Teacher, db: Session) -> Child:
    ch = db.get(Child, child_id)
    if not ch:
        raise HTTPException(404, "child not found")
    cls = db.get(Classroom, ch.class_id)
    if not cls or cls.school_id != teacher.school_id:
        raise HTTPException(404, "child not found")
    return ch


def validate_media(audio: bytes | None, image: bytes | None):
    from app.config import get_settings
    s = get_settings()
    if audio and len(audio) > s.max_audio_bytes:
        raise HTTPException(413, "audio too large")
    if image and len(image) > s.max_photo_bytes:
        raise HTTPException(413, "photo too large")
