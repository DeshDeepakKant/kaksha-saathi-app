"""Deterministic mastery engine.

Status is ALWAYS computed by this module from confirmed evidence — never by an LLM.
Rules (docs/03 §3): source-weighted, confidence-weighted, exponentially decayed;
home-only evidence cannot exceed `needs_practice`; two most recent wrongs cap the status.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.content import Content

STATUSES = ("not_started", "needs_intervention", "needs_practice", "on_track")
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}

SOURCE_WEIGHTS = {
    "teacher_tap": 1.0,
    "guided_probe": 1.0,
    "photo_work": 0.9,
    "class_voice": 0.8,
    "teacher_note": 0.7,
    "home_voice": 0.5,
    "home_tap": 0.4,
}
HOME_SOURCES = {"home_voice", "home_tap"}

WINDOW_DAYS = 21
DECAY_DAYS = 14
MIN_VOLUME = 0.8

RESULT_VALUES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


@dataclass(frozen=True)
class Ev:
    result: str
    source: str
    confidence: float
    at: datetime
    id: int = 0
    misconception: str | None = None


@dataclass(frozen=True)
class StatusResult:
    status: str
    score: float
    confidence: float
    evidence_volume: float
    improving: bool
    # True when home-only evidence wants to say on_track but the ceiling applies
    ceiling_applied: bool = False


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def status_for(evidences: list[Ev], now: datetime | None = None) -> StatusResult:
    now = _aware(now or datetime.now(timezone.utc))
    evs = [e for e in evidences if e.result in RESULT_VALUES]
    if not evs:
        return StatusResult("not_started", 0.0, 0.0, 0.0, False)
    evs = sorted(evs, key=lambda e: (_aware(e.at), e.id), reverse=True)
    recent = [e for e in evs if (now - _aware(e.at)).days <= WINDOW_DAYS]

    num = den = volume = 0.0
    for e in recent:
        w = SOURCE_WEIGHTS.get(e.source, 0.6) * max(0.0, min(1.0, e.confidence))
        decay = math.exp(-max(0.0, (now - _aware(e.at)).total_seconds() / 86400) / DECAY_DAYS)
        num += RESULT_VALUES[e.result] * w * decay
        den += w * decay
        volume += w

    if volume < MIN_VOLUME:
        return StatusResult("not_started", 0.0, 1 - math.exp(-volume), volume, False)
    score = num / den
    latest_two = evs[:2]
    latest_wrong = len(latest_two) == 2 and all(e.result == "incorrect" for e in latest_two)
    last_correct = evs[0].result == "correct"

    if score >= 0.75 and last_correct and sum(1 for e in latest_two if e.result == "correct") >= 2:
        status = "on_track"
    elif score < 0.35 or (last_correct is False and score < 0.5):
        status = "needs_intervention"
    else:
        status = "needs_practice"

    if latest_wrong and STATUS_RANK[status] > STATUS_RANK["needs_practice"]:
        status = "needs_practice"

    ceiling_applied = False
    if status == "on_track" and HOME_SOURCES.issuperset({e.source for e in recent}):
        status = "needs_practice"
        ceiling_applied = True

    improving = _trend_improving(recent[:4])
    return StatusResult(status, round(score, 3), round(1 - math.exp(-volume), 3), round(volume, 3),
                        improving, ceiling_applied)


def _trend_improving(recent_desc: list[Ev]) -> bool:
    """Oldest→newest values rise, with at least one wrong followed by a right."""
    seq = [RESULT_VALUES[e.result] for e in reversed(recent_desc)]  # oldest first
    if len(seq) < 3:
        return False
    if not any(v < 1.0 for v in seq[:-1]):
        return False
    # least-squares slope
    n = len(seq)
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(seq) / n
    denom = sum((x - mx) ** 2 for x in xs) or 1
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, seq)) / denom
    return slope > 0.05


# ---------------------------------------------------------------- prerequisites / gaps
def prerequisite_closure(content: Content, cid: str) -> list[str]:
    """All ancestors of a checkpoint (excluding itself), nearest first."""
    seen: list[str] = []
    frontier = list(content.prereqs(cid))
    while frontier:
        cur = frontier.pop(0)
        if cur in seen or cur not in content.checkpoints:
            continue
        seen.append(cur)
        frontier.extend(content.prereqs(cur))
    return seen


@dataclass(frozen=True)
class Gap:
    child_id: int
    checkpoint_id: str
    status: str  # status of the checkpoint that is failing (intervention root)
    target_id: str  # grade-level checkpoint the child failed (needs_practice secondary)
    rank: int  # lower = more foundational
    reason: str  # needs_intervention_root | needs_practice_root | direct


def find_gap(content: Content, statuses: dict[str, str]) -> Gap | None:
    """Find a child's most foundational failing checkpoint.

    Walk down from each failing checkpoint (needs_intervention preferred). If a prerequisite
    itself has failing evidence (intervention), the prerequisite becomes the root — the
    intervention should start where the foundation breaks, not at the grade-level topic.
    """
    failing_interv = [c for c, s in statuses.items() if s == "needs_intervention"]
    failing_practice = [c for c, s in statuses.items() if s == "needs_practice"]

    best: tuple[int, str, str, str] | None = None  # (rank, cp, target, reason)
    for target in failing_interv + failing_practice:
        if target not in content.checkpoints:
            continue
        primary = statuses.get(target) == "needs_intervention"
        root, root_status = target, statuses.get(target)
        for p in prerequisite_closure(content, target):
            ps = statuses.get(p)
            if ps in ("needs_intervention", "needs_practice"):
                if root_status == "needs_intervention" and ps == "needs_practice":
                    continue  # keep the more severe root
                root, root_status = p, ps
        if root == target:
            reason = "direct"
        elif root_status == "needs_intervention":
            reason = "needs_intervention_root"
        else:
            reason = "needs_practice_root"
        sev = 0 if root_status == "needs_intervention" else 1
        grade = content.checkpoints[root].grade
        rank = sev * 1000 + grade * 10 + (0 if primary else 1)
        key = (rank, root, target, reason)
        if best is None or (rank, root, target) < best[:3]:
            best = key
    if best is None:
        return None
    rank, root, target, reason = best
    return Gap(0, root, statuses.get(root, "needs_practice"), target, rank, reason)
