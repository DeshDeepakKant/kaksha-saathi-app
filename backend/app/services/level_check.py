"""First-week / end-of-term level check (ASER/TaRL style). Deterministic; no AI.

The ladder for each subject lives in `content/level_check.json`. The teacher starts a child at
level 0 and moves up; the check stops at the first level the child does not pass. Each tested level
becomes one confirmed `guided_probe` evidence row on that level's checkpoint, and one `LevelCheck`
row keeps the placement (highest level passed, -1 = beginner) so first vs latest can be compared.
Contract: docs/teacher_loop_contract.md ("Backend-Manage").
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.tables import Child, Classroom, Evidence, LevelCheck, Teacher
from app.services import ledger
from app.services.content import get_content

BEGINNER = -1


class LadderError(ValueError):
    """A level check request that breaks the stop rule (start at level 0, no gaps, stop at first fail)."""


@lru_cache
def load_ladders() -> dict[str, dict]:
    """`subjects` from content/level_check.json, validated against the competency graph.

    Raises RuntimeError on bad content (same fail-fast rule as `get_content`).
    """
    with (get_settings().content_dir / "level_check.json").open(encoding="utf-8") as f:
        subjects = json.load(f)["subjects"]
    cps = get_content().checkpoints
    for subject, lad in subjects.items():
        levels = lad.get("levels") or []
        if not levels or not lad.get("beginner", {}).get("key"):
            raise RuntimeError(f"level_check {subject}: needs a beginner and at least one level")
        keys = [lv["key"] for lv in levels] + [lad["beginner"]["key"]]
        if len(set(keys)) != len(keys):
            raise RuntimeError(f"level_check {subject}: level keys must be unique")
        for lv in levels:
            cp = cps.get(lv["checkpoint_id"])
            if cp is None or cp.subject != subject:
                raise RuntimeError(f"level_check {subject}/{lv['key']}: unknown checkpoint {lv['checkpoint_id']}")
            if lv["of"] != len(lv["items"]) or not 1 <= lv["pass_min"] <= lv["of"]:
                raise RuntimeError(f"level_check {subject}/{lv['key']}: pass_min/of do not match the items")
    return subjects


def ladder(subject: str) -> dict | None:
    """The ladder for a subject, or None (only literacy and numeracy have one)."""
    return load_ladders().get(subject)


def level_ref(lad: dict, index: int) -> dict:
    """Key and titles for a placement index (-1 = beginner)."""
    lv = lad["beginner"] if index == BEGINNER else lad["levels"][index]
    return {"level_key": lv["key"], "title_en": lv["title_en"], "title_hi": lv["title_hi"]}


def placement(lad: dict, results: list[tuple[str, bool]]) -> int:
    """Highest level passed (-1 = beginner) for `(level_key, passed)` results in ladder order.

    Results must start at level 0 and follow the ladder with no gaps; nothing may follow the first fail.
    """
    if not results:
        raise LadderError("results must start at the first level")
    levels = lad["levels"]
    if len(results) > len(levels):
        raise LadderError("more results than levels")
    passed_to = BEGINNER
    for i, (key, passed) in enumerate(results):
        if key != levels[i]["key"]:
            raise LadderError(f"results must follow the ladder from the first level with no gaps "
                              f"(expected {levels[i]['key']} at position {i})")
        if i > 0 and not results[i - 1][1]:
            raise LadderError("the check stops at the first level not passed")
        if passed:
            passed_to = i
    return passed_to


def record(db: Session, cls: Classroom, child: Child, teacher: Teacher, subject: str, lad: dict,
           results: list[tuple[str, bool]], session_id: int | None = None) -> dict:
    """Write one evidence row per tested level and the `LevelCheck` row; returns the placement."""
    index = placement(lad, results)
    now = datetime.now(timezone.utc)
    for (key, passed), lv in zip(results, lad["levels"]):
        db.add(Evidence(school_id=cls.school_id, class_id=cls.id, child_id=child.id,
                        checkpoint_id=lv["checkpoint_id"], result="correct" if passed else "incorrect",
                        score=1.0 if passed else 0.0, source="guided_probe", confidence=1.0,
                        status="confirmed", created_by=teacher.id, session_id=session_id, at=now))
    ref = level_ref(lad, index)
    db.add(LevelCheck(school_id=cls.school_id, class_id=cls.id, child_id=child.id, subject=subject,
                      level_index=index, level_key=ref["level_key"], at=now, created_by=teacher.id))
    db.flush()
    return {"level_index": index, **ref}


def _check(row: LevelCheck | None) -> dict | None:
    if row is None:
        return None
    return {"level_index": row.level_index, "level_key": row.level_key, "at": row.at.isoformat()}


def class_view(db: Session, cls: Classroom, subject: str, lad: dict) -> dict:
    """The ladder, each active child's first and latest check, and the class summary.

    Checks follow the child (looked up by child id), so a child moved between classes keeps them.
    """
    children = ledger.class_children(db, cls.id)
    first: dict[int, LevelCheck] = {}
    latest: dict[int, LevelCheck] = {}
    if children:
        rows = db.scalars(select(LevelCheck).where(
            LevelCheck.child_id.in_([c.id for c in children]), LevelCheck.subject == subject)
            .order_by(LevelCheck.at, LevelCheck.id))
        for r in rows:
            first.setdefault(r.child_id, r)
            latest[r.child_id] = r
    keys = [lad["beginner"]["key"]] + [lv["key"] for lv in lad["levels"]]
    counts_first = dict.fromkeys(keys, 0)
    counts_latest = dict.fromkeys(keys, 0)
    moved_up = 0
    for cid in first:
        counts_first[first[cid].level_key] = counts_first.get(first[cid].level_key, 0) + 1
        counts_latest[latest[cid].level_key] = counts_latest.get(latest[cid].level_key, 0) + 1
        moved_up += latest[cid].level_index > first[cid].level_index
    return {
        "subject": subject, "title_en": lad["title_en"], "title_hi": lad["title_hi"],
        "beginner": {k: lad["beginner"][k] for k in ("key", "title_en", "title_hi")},
        "levels": [{"index": i, "key": lv["key"], "title_en": lv["title_en"], "title_hi": lv["title_hi"],
                    "checkpoint_id": lv["checkpoint_id"], "ask_en": lv["ask_en"], "ask_hi": lv["ask_hi"],
                    "items": [{"show": it["show"], "expect": it.get("expect")} for it in lv["items"]],
                    "pass_min": lv["pass_min"], "of": lv["of"]} for i, lv in enumerate(lad["levels"])],
        "children": [{"child_id": c.id, "first_name": c.first_name, "roll_no": c.roll_no,
                      "first": _check(first.get(c.id)), "latest": _check(latest.get(c.id))} for c in children],
        "summary": {"total": len(children), "checked": len(first), "moved_up": moved_up,
                    "first": counts_first, "latest": counts_latest},
    }


# ------------------------------------------------------------------ demo data
# Placements for DEMO class 2A by roll-order index, chosen to agree with the evidence story in seed.py
# (literacy gap = index % 5; numeracy groups: 0-4 borrowing, 5-8 carrying, 9-11 place value, 12-13 new).
def _demo_latest(subject: str, idx: int) -> int | None:
    if subject == "literacy":
        return {0: -1, 1: 0, 2: 0, 3: 1, 4: 2}[idx % 5]
    if 12 <= idx < 14:
        return None
    return 2 if idx < 5 else 3 if idx < 9 else 1 if idx < 12 else 3


def demo_seed(db: Session, school_id: int) -> int:
    """Give the school's class 2A first-week checks ~3 weeks ago and later checks for some children.

    Writes `LevelCheck` rows only, no evidence: the demo's evidence story is seeded separately and
    extra probe rows would shift the board it sets up. Idempotent (skips a class that already has
    checks); flushes, does not commit. Returns the number of rows written.
    """
    cls = db.scalar(select(Classroom).where(Classroom.school_id == school_id, Classroom.grade == 2,
                                            Classroom.section == "A"))
    if cls is None or db.scalar(select(LevelCheck.id).where(LevelCheck.class_id == cls.id).limit(1)):
        return 0
    kids = ledger.class_children(db, cls.id)
    now = datetime.now(timezone.utc)
    n = 0
    for subject, first_upto, later_upto in (("literacy", 20, 12), ("numeracy", 20, 10)):
        lad = ladder(subject)
        for idx, k in enumerate(kids[:first_upto]):
            latest = _demo_latest(subject, idx)
            if latest is None:
                continue
            first = max(BEGINNER, latest - 1) if idx % 3 else latest
            checks = [(first, now - timedelta(days=21 + idx % 3, hours=2))]
            if idx < later_upto:
                checks.append((latest, now - timedelta(days=2 + idx % 3, hours=3)))
            for index, at in checks:
                db.add(LevelCheck(school_id=school_id, class_id=cls.id, child_id=k.id, subject=subject,
                                  level_index=index, level_key=level_ref(lad, index)["level_key"], at=at,
                                  created_by=cls.teacher_id))
                n += 1
    db.flush()
    return n


def delete_for_school(db: Session, school_id: int) -> None:
    """Remove a school's checks (call before deleting its children, e.g. when re-seeding DEMO)."""
    db.execute(delete(LevelCheck).where(LevelCheck.school_id == school_id))
