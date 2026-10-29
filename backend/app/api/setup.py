"""Teacher setup: add a class, add a subject, build or import a syllabus, see coverage per topic.

All routes are under /v1, teacher JWT, scoped to the teacher's school (`owned_class`).
Custom topics become real checkpoints (see `services/coverage.py`), so taps, board, plans and
profiles work on them unchanged. Contract: docs/teacher_api_additions.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_teacher, owned_class
from app.db import get_db
from app.models.tables import Classroom, Teacher, TextbookMap
from app.services import coverage
from app.services.content import get_content
from app.services.subjects import create_custom_subject, resolve_subject, subject_names

router = APIRouter(prefix="/v1")

MAX_ITEMS = 80
SOURCES = ("template", "photo", "import", "book")
MAX_BOOK_CHAPTERS = 40


def _class_out(c: Classroom, children: int = 0, consented: int = 0) -> dict:
    return {"id": c.id, "label": c.label, "grade": c.grade, "section": c.section,
            "children": children, "consented": consented}


# ------------------------------------------------------------------ classes
class ClassIn(BaseModel):
    grade: int = Field(ge=1, le=8)
    section: str = Field(min_length=1, max_length=8)
    label: str | None = Field(default=None, max_length=40)


@router.post("/classes")
def create_class(body: ClassIn, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    section = body.section.strip().upper()
    if not section:
        raise HTTPException(422, "section is required")
    if db.scalar(select(Classroom.id).where(Classroom.school_id == teacher.school_id,
                                            Classroom.grade == body.grade, Classroom.section == section)):
        raise HTTPException(409, "this class already exists")
    label = (body.label or "").strip() or f"कक्षा {body.grade}{section}"
    cls = Classroom(school_id=teacher.school_id, teacher_id=teacher.id, grade=body.grade,
                    section=section, label=label)
    db.add(cls)
    db.flush()
    return _class_out(cls)


@router.get("/classes/{class_id}/subjects")
def class_subjects(class_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    out = []
    for s in subject_names(db, teacher.school_id):
        _rm, rows = coverage.effective_items(db, cls, s["key"])
        out.append({**s, "topics": len(rows)})
    return out


# ------------------------------------------------------------------ subjects
class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    name_hi: str | None = Field(default=None, max_length=60)


@router.post("/subjects")
def add_subject(body: SubjectIn, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    row = create_custom_subject(db, teacher.school_id, body.name, body.name_hi)
    return {"key": row.key, "name_en": row.name_en, "name_hi": row.name_hi, "builtin": False}


# ------------------------------------------------------------------ syllabus
@router.get("/classes/{class_id}/syllabus")
def get_syllabus(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                 db: Session = Depends(get_db)):
    subject = resolve_subject(db, teacher.school_id, subject)
    cls = owned_class(class_id, teacher, db)
    return _with_book(db, cls, subject, coverage.syllabus(db, cls, subject))


def _book_out(row: TextbookMap | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "title": row.title, "grade": row.grade, "board": row.board, "publisher": row.publisher,
            "chapters": (row.mapping or {}).get("chapters", []),
            "saved_at": row.created_at.isoformat() if row.created_at else None}


def _with_book(db: Session, cls: Classroom, subject: str, out: dict) -> dict:
    """The syllabus response plus the latest saved textbook mapping for this class + subject (or None)."""
    row = db.scalar(select(TextbookMap).where(TextbookMap.class_id == cls.id, TextbookMap.subject == subject)
                    .order_by(TextbookMap.created_at.desc(), TextbookMap.id.desc()).limit(1))
    out["book"] = _book_out(row)
    return out


class SyllabusItemIn(BaseModel):
    checkpoint_id: str | None = Field(default=None, max_length=80)
    custom_title: str | None = Field(default=None, max_length=120)
    custom_title_hi: str | None = Field(default=None, max_length=120)
    chapter: str | None = Field(default=None, max_length=120)
    position: int | None = None


class BookTopicIn(BaseModel):
    text: str = Field(default="", max_length=120)
    checkpoint_id: str | None = Field(default=None, max_length=80)


class BookChapterIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    inferred: bool = False
    basis: str = Field(default="page", max_length=20)
    topics: list[BookTopicIn] = Field(default_factory=list, max_length=MAX_ITEMS)


class BookIn(BaseModel):
    """The reviewed textbook mapping (same shape as the /books/map draft); stored as a record of the book."""
    title: str = Field(default="", max_length=120)
    grade: int | None = Field(default=None, ge=1, le=8)
    board: str = Field(default="", max_length=60)
    publisher: str = Field(default="", max_length=60)
    chapters: list[BookChapterIn] = Field(default_factory=list, max_length=MAX_BOOK_CHAPTERS)


class SyllabusIn(BaseModel):
    subject: str
    source: str = "import"
    items: list[SyllabusItemIn] = Field(max_length=MAX_ITEMS)
    book: BookIn | None = None


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


@router.post("/classes/{class_id}/syllabus")
def save_syllabus(class_id: int, body: SyllabusIn, teacher: Teacher = Depends(current_teacher),
                  db: Session = Depends(get_db)):
    subject = resolve_subject(db, teacher.school_id, body.subject)
    cls = owned_class(class_id, teacher, db)
    if body.source not in SOURCES:
        raise HTTPException(422, f"source must be one of {', '.join(SOURCES)}")
    if not body.items:
        raise HTTPException(422, "syllabus needs at least one topic")
    content = get_content()
    # keep the sender's order: by position when given, otherwise as listed
    ordered = sorted(enumerate(body.items), key=lambda p: (p[1].position if p[1].position is not None else p[0], p[0]))
    rows, created, seen = [], [], set()
    made: dict[tuple[str, str], str] = {}  # (chapter, custom title) -> new checkpoint id, for the book record
    for _, it in ordered:
        cid = _clean(it.checkpoint_id)
        chapter = _clean(it.chapter)
        if cid:
            cp = content.checkpoints.get(cid)
            own = cid in content.custom_ids and cid.startswith(f"C{cls.school_id}-")
            if cp is None or (cid in content.custom_ids and not own):
                raise HTTPException(422, f"unknown checkpoint {cid}")
            if cp.subject != subject:
                raise HTTPException(422, f"checkpoint {cid} belongs to {cp.subject}, not {subject}")
            if cid in seen:
                continue
            seen.add(cid)
            rows.append({"chapter": chapter or cp.chapter, "checkpoint_id": cid, "custom_title": None})
        else:
            title = _clean(it.custom_title)
            if not title:
                raise HTTPException(422, "each topic needs a checkpoint_id or a custom_title")
            row = coverage.new_custom_checkpoint(db, cls, teacher, subject, chapter or coverage.DEFAULT_CHAPTER,
                                                 title, _clean(it.custom_title_hi) or title)
            created.append(row)
            made.setdefault((chapter or coverage.DEFAULT_CHAPTER, title), row.id)
            rows.append({"chapter": chapter or coverage.DEFAULT_CHAPTER, "checkpoint_id": row.id,
                         "custom_title": None})
    coverage.write_version(db, cls, teacher, subject, body.source, rows)
    for row in created:
        coverage.register(row)
    if body.book is not None:
        _save_book(db, cls, teacher, subject, body.book, made)
    return _with_book(db, cls, subject, coverage.syllabus(db, cls, subject))


def _save_book(db: Session, cls: Classroom, teacher: Teacher, subject: str, book: BookIn,
               made: dict[tuple[str, str], str]) -> None:
    chapters = []
    for ch in book.chapters:
        title = _clean(ch.title)
        if not title:
            continue
        topics = []
        for t in ch.topics:
            text, cid = _clean(t.text), _clean(t.checkpoint_id) or None
            # a custom topic just saved on the syllabus: point the book record at its new checkpoint
            cid = cid or made.get((title, text))
            if text or cid:
                topics.append({"text": text, "checkpoint_id": cid})
        chapters.append({"title": title, "inferred": ch.inferred, "basis": _clean(ch.basis) or "page",
                         "topics": topics})
    db.add(TextbookMap(school_id=cls.school_id, class_id=cls.id, subject=subject, title=_clean(book.title),
                       grade=book.grade, board=_clean(book.board), publisher=_clean(book.publisher),
                       mapping={"chapters": chapters}, created_by=teacher.id))
    db.flush()


class TopicIn(BaseModel):
    subject: str
    chapter: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    title_hi: str | None = Field(default=None, max_length=120)


@router.post("/classes/{class_id}/syllabus/topics")
def add_topic(class_id: int, body: TopicIn, teacher: Teacher = Depends(current_teacher),
              db: Session = Depends(get_db)):
    subject = resolve_subject(db, teacher.school_id, body.subject)
    cls = owned_class(class_id, teacher, db)
    chapter, title = _clean(body.chapter), _clean(body.title)
    if not chapter or not title:
        raise HTTPException(422, "chapter and title are required")
    prev, rows = coverage.effective_items(db, cls, subject)  # template is materialised by the new version
    if len(rows) >= MAX_ITEMS:
        raise HTTPException(422, f"a syllabus can hold at most {MAX_ITEMS} topics")
    rows = sorted(rows, key=lambda r: r["position"])
    cp = coverage.new_custom_checkpoint(db, cls, teacher, subject, chapter, title, _clean(body.title_hi) or title)
    new = {"chapter": chapter, "checkpoint_id": cp.id, "custom_title": None}
    # slot it after the last topic of the same chapter, else at the end
    last = max((i for i, r in enumerate(rows) if r["chapter"] == chapter), default=len(rows) - 1)
    rows.insert(last + 1, new)
    coverage.write_version(db, cls, teacher, subject, prev.source if prev else "template", rows)
    coverage.register(cp)
    return coverage.topic_view(db, cls, subject, cp.id)


@router.delete("/classes/{class_id}/syllabus/topics/{checkpoint_id}")
def remove_topic(class_id: int, checkpoint_id: str, subject: str, teacher: Teacher = Depends(current_teacher),
                 db: Session = Depends(get_db)):
    subject = resolve_subject(db, teacher.school_id, subject)
    cls = owned_class(class_id, teacher, db)
    prev, rows = coverage.effective_items(db, cls, subject)
    rows = sorted(rows, key=lambda r: r["position"])
    kept = [r for r in rows if r["checkpoint_id"] != checkpoint_id]
    if len(kept) == len(rows):
        raise HTTPException(404, "topic not on this syllabus")
    # the topic's checkpoint and any evidence stay; only this class's syllabus stops listing it
    coverage.write_version(db, cls, teacher, subject, prev.source if prev else "template", kept)
    return _with_book(db, cls, subject, coverage.syllabus(db, cls, subject))
