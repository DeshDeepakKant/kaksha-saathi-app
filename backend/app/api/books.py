"""Smart textbook mapping: photograph a book's cover/index and/or type its identity → a DRAFT of chapters
with topics matched to checkpoints; correct it by voice or text; save it via POST /syllabus (source "book").

All routes are under /v1, teacher JWT, scoped to the teacher's school (`owned_class`). Nothing here writes
the syllabus: the teacher reviews the draft first.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai import features
from app.api.deps import current_teacher, image_media_type, owned_class, validate_media
from app.db import get_db
from app.models.tables import Teacher
from app.services import content_lang
from app.services.content import get_content
from app.services.subjects import BUILTIN_NAMES, resolve_subject

router = APIRouter(prefix="/v1")

MAX_IMAGES = 6
MAX_DRAFT_CHARS = 60_000


def _opt(text: str | None) -> str:
    return " ".join((text or "").split())


def _grade(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        g = int(raw)
    except ValueError:
        raise HTTPException(422, "book_grade must be a whole number 1–8")
    if not 1 <= g <= 8:
        raise HTTPException(422, "book_grade must be a whole number 1–8")
    return g


def _response(p: features.Proposal, **extra) -> dict:
    return {"status": p.ai_status, "note": p.note, **p.payload, **extra}


@router.post("/classes/{class_id}/books/map")
async def map_book(class_id: int, subject: str = Form(...),
                   book_title: str | None = Form(None, max_length=120),
                   board: str | None = Form(None, max_length=60),
                   publisher: str | None = Form(None, max_length=60),
                   book_grade: str | None = Form(None),
                   notes: str | None = Form(None, max_length=300),
                   images: list[UploadFile] = File(default=[]),
                   teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Cover/index photos (0–6) and/or typed book identity → DRAFT chapters + topics + flat items."""
    subject = resolve_subject(db, teacher.school_id, subject)
    cls = owned_class(class_id, teacher, db)
    grade = _grade(book_grade)
    title = _opt(book_title)
    if len(images) > MAX_IMAGES:
        raise HTTPException(422, f"at most {MAX_IMAGES} photos")
    photos = []
    for up in images:
        data = await up.read()
        if not data:
            continue
        validate_media(None, data)
        photos.append((data, image_media_type(data)))
    if not photos and not title:
        raise HTTPException(422, "send a photo of the book or type its title")
    lang, _provider = content_lang.for_teacher(db, teacher)
    # The model calls block for 15–60 s; run them off the event loop so other requests keep flowing.
    p = await run_in_threadpool(
        features.map_book, db, school_id=cls.school_id, content=get_content(), subject=subject,
        subject_label=BUILTIN_NAMES.get(subject, (subject,))[0], class_grade=cls.grade,
        book_grade=grade, title=title, board=_opt(board), publisher=_opt(publisher),
        notes=_opt(notes), images=photos, lang=lang)
    return _response(p)


@router.post("/classes/{class_id}/books/map/revise")
async def revise_book_map(class_id: int, subject: str = Form(...), draft: str = Form(...),
                          transcript: str | None = Form(None, max_length=2000),
                          audio: UploadFile | None = File(None),
                          teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Apply a spoken or typed correction to a draft mapping; returns the revised draft + what was heard."""
    subject = resolve_subject(db, teacher.school_id, subject)
    cls = owned_class(class_id, teacher, db)
    if len(draft) > MAX_DRAFT_CHARS:
        raise HTTPException(422, "draft is too large")
    try:
        parsed = json.loads(draft)
    except ValueError:
        raise HTTPException(422, "draft must be JSON")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("chapters", []), list):
        raise HTTPException(422, "draft must be an object with a chapters list")
    audio_bytes = await audio.read() if audio else None
    validate_media(audio_bytes, None)
    lang, provider = content_lang.for_teacher(db, teacher)
    text = (transcript or "").strip()
    if not text and audio_bytes:
        try:
            heard = await run_in_threadpool(content_lang.transcribe, audio_bytes, audio.filename or "correction.m4a",
                                            lang=lang, preferred=provider)
            text = heard.text
        except Exception:
            text = ""
    text = (text or "").strip()[:2000]
    if not text:
        raise HTTPException(422, "no correction heard (type it instead)")
    p = await run_in_threadpool(features.revise_book_map, db, school_id=cls.school_id, content=get_content(),
                                subject=subject, class_grade=cls.grade, draft=parsed, correction=text, lang=lang)
    return _response(p, heard=text)
