"""Deterministic classroom grouping: children with the same foundational gap form a group."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.content import Content
from app.services.mastery import Gap, find_gap

MIN_GROUP = 3
MAX_GROUP = 12


@dataclass
class Group:
    key: str
    checkpoint_id: str
    chapter: str
    title_hi: str
    status: str
    members: list[int] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    reason: str = ""
    whole_class_flag: bool = False
    title_en: str = ""


@dataclass
class Grouping:
    groups: list[Group]
    on_track: list[int]
    unassessed: list[int]
    gaps: dict[int, Gap]


def group_class(content: Content, child_statuses: dict[int, dict[str, str]],
                needs_assessment: set[int] | None = None) -> Grouping:
    needs_assessment = needs_assessment or set()
    gaps: dict[int, Gap] = {}
    for child_id, st in child_statuses.items():
        if child_id in needs_assessment:
            continue
        g = find_gap(content, st)
        if g is None:
            continue
        gaps[child_id] = Gap(child_id=child_id, checkpoint_id=g.checkpoint_id, status=g.status,
                             target_id=g.target_id, rank=g.rank, reason=g.reason)

    buckets: dict[str, list[int]] = {}
    for cid, g in gaps.items():
        buckets.setdefault(g.checkpoint_id, []).append(cid)

    groups: list[Group] = []
    for cp_id, members in buckets.items():
        cp = content.checkpoints.get(cp_id)
        if cp is None:
            continue
        groups.append(Group(key=cp_id, checkpoint_id=cp_id, chapter=cp.chapter, title_hi=cp.title_hi,
                            title_en=cp.title_en, status=gaps[members[0]].status, members=sorted(members),
                            whole_class_flag=len(members) > MAX_GROUP,
                            reason=gaps[members[0]].reason))

    # Merge small groups within the same chapter (never across chapters / concepts).
    merged: list[Group] = []
    used: set[str] = set()
    for g in sorted(groups, key=lambda x: (x.chapter, x.checkpoint_id)):
        if g.key in used:
            continue
        if len(g.members) < MIN_GROUP:
            for other in groups:
                if other.key == g.key or other.key in used or other.chapter != g.chapter:
                    continue
                # only merge if at least one is a prerequisite of the other's target family
                rel = (other.checkpoint_id in content.prereqs(g.checkpoint_id)
                       or g.checkpoint_id in content.prereqs(other.checkpoint_id))
                if not rel:
                    continue
                g.members = sorted(set(g.members) | set(other.members))
                g.merged_from.append(other.key)
                used.add(other.key)
                if len(g.members) >= MIN_GROUP:
                    break
        used.add(g.key)
        merged.append(g)

    # Foundation-first ordering; earlier (lower grade) gaps surface first.
    merged.sort(key=lambda x: (x.chapter, content.checkpoints[x.checkpoint_id].grade if x.checkpoint_id in content.checkpoints else 9,
                               -len(x.members)))
    on_track, unassessed = [], []
    for child_id in child_statuses:
        if child_id in needs_assessment:
            unassessed.append(child_id)
        elif child_id not in gaps:
            on_track.append(child_id)
    return Grouping(groups=merged, on_track=sorted(on_track), unassessed=sorted(unassessed), gaps=gaps)
