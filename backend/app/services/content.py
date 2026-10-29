"""Read-only content: competency graph, activity library, practice items, probes.

Loaded once from `content/` (validated at startup). The graph is the authority for
prerequisite reasoning; runtime AI may only *select* from reviewed entries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@dataclass(frozen=True)
class Checkpoint:
    id: str
    subject: str
    grade: int
    domain: str
    chapter: str
    title_hi: str
    title_en: str
    prereqs: tuple[str, ...]
    misconceptions: tuple[str, ...]
    assess_via: tuple[str, ...]
    item_types: tuple[str, ...]
    nipun_ref: str
    language: str


@dataclass
class Content:
    checkpoints: dict[str, Checkpoint]
    activities: dict[str, dict]
    practice_items: list[dict]
    probes: dict[str, dict]
    subjects: list[str] = field(default_factory=lambda: ["numeracy", "literacy"])
    # Ids of teacher-created topics registered at runtime (see register_custom). They live in
    # `checkpoints` so every existing code path works, but they belong to one school, so the
    # generic listings below (template roadmap, for_grade) never include them.
    custom_ids: set[str] = field(default_factory=set)

    def register_custom(self, cp: Checkpoint) -> None:
        self.checkpoints[cp.id] = cp
        self.custom_ids.add(cp.id)

    # -- graph helpers
    def prereqs(self, cid: str) -> tuple[str, ...]:
        return self.checkpoints[cid].prereqs

    def descendants_ok(self) -> bool:
        """Every prerequisite exists and the graph is acyclic."""
        for c in self.checkpoints.values():
            for p in c.prereqs:
                if p not in self.checkpoints:
                    return False
        seen: set[str] = set()
        stack: set[str] = set()

        def visit(cid: str) -> bool:
            if cid in stack:
                return False
            if cid in seen:
                return True
            stack.add(cid)
            ok = all(visit(p) for p in self.prereqs(cid))
            stack.discard(cid)
            seen.add(cid)
            return ok

        return all(visit(c.id) for c in self.checkpoints.values())

    def for_grade(self, subject: str, grade: int, window: int = 1) -> list[Checkpoint]:
        return sorted(
            (c for c in self.checkpoints.values()
             if c.subject == subject and abs(c.grade - grade) <= window and c.id not in self.custom_ids),
            key=lambda c: (c.grade, c.chapter, c.id),
        )

    def template_roadmap(self, subject: str, grade: int) -> list[dict]:
        """Deterministic starting roadmap: all checkpoints up to the class grade (and one below)."""
        items, seen = [], set()
        for c in sorted(self.checkpoints.values(), key=lambda c: (c.grade, c.chapter, c.title_hi)):
            if c.subject != subject or c.grade > grade or c.id in self.custom_ids:
                continue
            chapter = c.chapter if c.grade == grade else f"{c.chapter} ({c.grade})"
            key = (chapter, c.id)
            if key in seen:
                continue
            seen.add(key)
            items.append({"chapter": chapter, "checkpoint_id": c.id})
        for i, it in enumerate(items):
            it["position"] = i
        return items

    def activities_for(self, checkpoint_ids: set[str], reviewed_only: bool = True) -> list[dict]:
        out = []
        for a in self.activities.values():
            if reviewed_only and not a.get("reviewed"):
                continue
            if set(a["checkpoint_ids"]) & checkpoint_ids:
                out.append(a)
        return out

    def items_for(self, checkpoint_id: str, limit: int = 10) -> list[dict]:
        return [i for i in self.practice_items if i["checkpoint_id"] == checkpoint_id][:limit]


def match_checkpoint(content: Content, text: str, subject: str, grade: int, threshold: int = 70) -> str | None:
    """Best fuzzy match of free text (a printed topic or chapter title) to a reviewed checkpoint, or None."""
    from rapidfuzz import fuzz
    best, best_score = None, 0
    for c in content.for_grade(subject, grade):
        s = max(fuzz.partial_ratio(text, c.title_hi), fuzz.partial_ratio(text, c.title_en))
        if s > best_score:
            best, best_score = c.id, s
    return best if best_score >= threshold else None


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def get_content() -> Content:
    base = get_settings().content_dir
    graph = _load_json(base / "competency_graph.json")
    checkpoints: dict[str, Checkpoint] = {}
    for n in graph["nodes"]:
        cp = Checkpoint(
            id=n["id"], subject=n["subject"], grade=int(n["grade"]), domain=n["domain"],
            chapter=n["chapter"], title_hi=n["title_hi"], title_en=n["title_en"],
            prereqs=tuple(n.get("prereqs", [])), misconceptions=tuple(n.get("misconceptions", [])),
            assess_via=tuple(n.get("assess_via", [])), item_types=tuple(n.get("item_types", [])),
            nipun_ref=n.get("nipun_ref", ""), language=n.get("language", "hi"),
        )
        checkpoints[cp.id] = cp
    activities = {a["id"]: a for a in _load_json(base / "activities.json")["activities"]}
    practice = _load_json(base / "practice_items.json")["items"]
    probes = {p["checkpoint_id"]: p for p in _load_json(base / "probes.json")["probes"]}
    content = Content(checkpoints=checkpoints, activities=activities, practice_items=practice, probes=probes)
    if not content.descendants_ok():
        raise RuntimeError("competency graph is invalid (missing prereq or cycle)")
    return content


# ------------------------------------------------------------------ teacher-created topics (overlay)
def checkpoint_from_row(row) -> Checkpoint:
    """A `CustomCheckpoint` row as a plain checkpoint: no prerequisites, no misconceptions, no
    practice items. The teacher marks it by tap, so that is the only assessment route."""
    return Checkpoint(
        id=row.id, subject=row.subject, grade=int(row.grade), domain="custom", chapter=row.chapter,
        title_hi=row.title_hi, title_en=row.title_en, prereqs=(), misconceptions=(),
        assess_via=("teacher_tap",), item_types=(), nipun_ref="", language="hi",
    )


def load_custom_checkpoints(content: Content | None = None, db=None) -> int:
    """Register every school's custom checkpoints into `content` (the cached one by default).

    Called from the app lifespan after `init_db()`. The registry is per process, so this relies on
    a single uvicorn worker (a second worker would only see topics created after its own start).
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.tables import CustomCheckpoint

    content = content if content is not None else get_content()
    own = db is None
    db = db or SessionLocal()
    try:
        rows = list(db.scalars(select(CustomCheckpoint)))
    finally:
        if own:
            db.close()
    for r in rows:
        content.register_custom(checkpoint_from_row(r))
    return len(rows)
