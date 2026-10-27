"""Syllabus coverage: every topic of a class + subject with how many children are done, in progress
or not started. Deterministic; reads the same roadmap and mastery statuses the board uses.

A child has "done" a topic when its status is `on_track`; `needs_practice` / `needs_intervention`
are in progress; `not_started` means no evidence yet.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import Classroom, CustomCheckpoint, Roadmap, RoadmapItem, Teacher
from app.services import ledger
from app.services.content import Content, checkpoint_from_row, get_content

STATUSES = ("on_track", "needs_practice", "needs_intervention", "not_started")
DEFAULT_CHAPTER = "अन्य"


def effective_items(db: Session, cls: Classroom, subject: str) -> tuple[Roadmap | None, list[dict]]:
    """The class's confirmed roadmap, or the template one (same fallback `ledger.build_groups` uses)."""
    rm = ledger.current_roadmap(db, cls.id, subject)
    if rm:
        return rm, [{"chapter": i.chapter, "checkpoint_id": i.checkpoint_id,
                     "custom_title": i.custom_title, "position": i.position} for i in rm.items]
    return None, [{"chapter": i["chapter"], "checkpoint_id": i["checkpoint_id"],
                   "custom_title": None, "position": i["position"]}
                  for i in get_content().template_roadmap(subject, cls.grade)]


def _empty_counts() -> dict[str, int]:
    return {s: 0 for s in STATUSES}


def _pct(counts: dict[str, int], total: int) -> float:
    return round(counts["on_track"] / total, 3) if total else 0.0


def _topic(content: Content, row: dict, order: int, child_ids: list[int], st: dict) -> dict:
    cid = row["checkpoint_id"]
    cp = content.checkpoints.get(cid)
    counts = _empty_counts()
    for ch in child_ids:
        r = st.get(ch, {}).get(cid) if cid else None
        s = r.status if r is not None else "not_started"
        counts[s if s in counts else "not_started"] += 1
    total = len(child_ids)
    return {
        "checkpoint_id": cid,
        "title_hi": cp.title_hi if cp else (row.get("custom_title") or cid),
        "title_en": cp.title_en if cp else (row.get("custom_title") or ""),
        "custom": (cid in content.custom_ids) if cid else True,
        "nipun_ref": cp.nipun_ref if cp else "",
        "position": order,
        "total": total,
        "assessed": total - counts["not_started"],
        "counts": counts,
        "pct_done": _pct(counts, total),
    }


def _rollup(topics: list[dict]) -> dict:
    counts = _empty_counts()
    for t in topics:
        for k in STATUSES:
            counts[k] += t["counts"][k]
    cells = sum(counts.values())
    return {"topics": len(topics), "counts": counts, "total": cells,
            "assessed": cells - counts["not_started"], "pct_done": _pct(counts, cells),
            "topics_done": sum(1 for t in topics if t["total"] and t["counts"]["on_track"] == t["total"])}


def syllabus(db: Session, cls: Classroom, subject: str) -> dict:
    content = get_content()
    rm, rows = effective_items(db, cls, subject)
    children = ledger.class_children(db, cls.id)
    child_ids = [c.id for c in children]
    st = ledger.child_statuses(db, child_ids)
    rows = sorted(rows, key=lambda r: r["position"])
    chapters: dict[str, list[dict]] = {}  # insertion order = first appearance in the roadmap
    topics: list[dict] = []
    for n, row in enumerate(rows):
        t = _topic(content, row, n, child_ids, st)
        topics.append(t)
        chapters.setdefault(row["chapter"] or DEFAULT_CHAPTER, []).append(t)
    return {
        "subject": subject,
        "confirmed": rm is not None,
        "version": rm.version if rm else None,
        "source": rm.source if rm else "template",
        "children": len(children),
        "chapters": [{"chapter": ch, "totals": _rollup(ts), "topics": ts} for ch, ts in chapters.items()],
        "totals": _rollup(topics),
    }


def topic_view(db: Session, cls: Classroom, subject: str, checkpoint_id: str) -> dict:
    """One topic in the shape used inside `syllabus()`; None-safe for an id not on the roadmap."""
    for ch in syllabus(db, cls, subject)["chapters"]:
        for t in ch["topics"]:
            if t["checkpoint_id"] == checkpoint_id:
                return t
    return {}


def new_custom_checkpoint(db: Session, cls: Classroom, teacher: Teacher, subject: str, chapter: str,
                          title_en: str, title_hi: str) -> CustomCheckpoint:
    """Persist a teacher-made topic with the next id for the school (`C<school>-<n>`).

    Ids are never reused: removing a topic from a syllabus keeps the row, because evidence refers to it.
    Call `register()` once the request has been validated.
    """
    prefix = f"C{cls.school_id}-"
    used = [int(i[len(prefix):]) for i in db.scalars(
        select(CustomCheckpoint.id).where(CustomCheckpoint.school_id == cls.school_id))
        if i.startswith(prefix) and i[len(prefix):].isdigit()]
    row = CustomCheckpoint(id=f"{prefix}{max(used, default=0) + 1}", school_id=cls.school_id,
                           subject=subject, grade=cls.grade, chapter=chapter[:120],
                           title_en=title_en, title_hi=title_hi, created_by=teacher.id)
    db.add(row)
    db.flush()
    return row


def register(row: CustomCheckpoint) -> None:
    """Make a custom checkpoint a real one in the cached content (tap capture, board, plans, profile)."""
    get_content().register_custom(checkpoint_from_row(row))


def write_version(db: Session, cls: Classroom, teacher: Teacher, subject: str, source: str,
                  rows: list[dict]) -> Roadmap:
    """Store `rows` as a new confirmed roadmap version (positions renumbered 0..n-1)."""
    prev = ledger.current_roadmap(db, cls.id, subject)
    rm = Roadmap(school_id=cls.school_id, class_id=cls.id, subject=subject,
                 version=(prev.version + 1) if prev else 1, source=source, confirmed_by=teacher.id)
    db.add(rm)
    db.flush()
    for n, r in enumerate(rows):
        db.add(RoadmapItem(roadmap_id=rm.id, position=n, chapter=(r["chapter"] or DEFAULT_CHAPTER)[:120],
                           checkpoint_id=r["checkpoint_id"], custom_title=r.get("custom_title") or None))
    db.flush()
    db.refresh(rm)
    return rm
