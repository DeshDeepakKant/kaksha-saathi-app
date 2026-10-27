"""Parent-session harness. Code controls the path; Claude only writes the language.

A session is a sequence of activities built from the child's top gaps (confirmed at school)
plus a couple of maintenance/enrichment items. Each activity is judged deterministically
(tap → exact; speech → ASR + constrained match). Two tries, then move on. Never stuck.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai import features
from app.config import get_settings
from app.speech.scorer import normalize
from app.services.content import Content

MAX_ACTIVITIES = 8
MAX_ATTEMPTS = 2
SMALL_PRAISE = ["शाबाश!", "बहुत अच्छा!", "सही!"]


def _now():
    return datetime.now(timezone.utc)


@dataclass
class Activity:
    ref: str
    item_id: str
    checkpoint_id: str
    type: str
    prompt_hi: str
    target: str
    accept: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    letters: list[str] = field(default_factory=list)
    base: str = ""
    tier: int = 1


def choose_focus(status_by_cp: dict[str, str], content: Content, max_items: int = 8) -> list[dict]:
    """Gap-first: needs_intervention, needs_practice, then a maintenance item from on_track."""
    order = {"needs_intervention": 0, "needs_practice": 1, "on_track": 2, "not_started": 3}
    gaps = sorted([(order.get(s, 3), cp, s) for cp, s in status_by_cp.items() if s in ("needs_intervention", "needs_practice")],
                  key=lambda x: (x[0], x[1]))
    focus = [{"checkpoint_id": cp, "status": s, "reason": "gap"} for _, cp, s in gaps]
    on_track = [cp for cp, s in status_by_cp.items() if s == "on_track"]
    if on_track and len(focus) < max_items:
        focus.append({"checkpoint_id": sorted(on_track)[0], "status": "on_track", "reason": "maintenance"})
    return focus


def build_plan(child_name: str, status_by_cp: dict[str, str], content: Content) -> dict:
    focus = choose_focus(status_by_cp, content)
    activities: list[Activity] = []
    if not focus:
        # brand-new child: use the first graph checkpoints for the grade
        focus = [{"checkpoint_id": c.id, "status": "not_started", "reason": "starter"}
                 for c in content.for_grade("numeracy", 1)[:2] + content.for_grade("literacy", 1)[:1]]
    for f in focus:
        for item in content.items_for(f["checkpoint_id"], limit=3):
            activities.append(_to_activity(item))
    activities = activities[:MAX_ACTIVITIES]
    # interleave numeracy/literacy so a session isn't one monotone skill
    num = [a for a in activities if a.checkpoint_id.startswith("N.")]
    lit = [a for a in activities if not a.checkpoint_id.startswith("N.")]
    mixed: list[Activity] = []
    while num or lit:
        if lit:
            mixed.append(lit.pop(0))
        if num:
            mixed.append(num.pop(0))
    return {"child_name": child_name, "focus": focus, "activities": [a.__dict__ for a in mixed],
            "max_activities": MAX_ACTIVITIES}


def activity_from_dict(item: dict) -> Activity:
    """Rebuild an Activity from a plan/pack dict (camel-free keys)."""
    return Activity(ref=item["ref"], item_id=item["item_id"], checkpoint_id=item["checkpoint_id"],
                    type=item["type"], prompt_hi=item["prompt_hi"], target=item["target"],
                    accept=list(item.get("accept") or []), options=list(item.get("options") or []),
                    letters=list(item.get("letters") or []), base=item.get("base", ""), tier=int(item.get("tier", 1)))


def _to_activity(item: dict) -> Activity:
    t = item["type"]
    target = str(item.get("target") or item.get("correct") or item.get("answer") or "")
    prompt = item.get("prompt_hi") or (f"बोलो: {target}" if t in ("say_word", "say_number") else "बोलो")
    return Activity(ref=item["id"], item_id=item["id"], checkpoint_id=item["checkpoint_id"], type=t,
                    prompt_hi=prompt, target=target,
                    accept=[str(x) for x in item.get("accept", [])],
                    options=list(item.get("options") or _order_options(item, target)),
                    letters=list(item.get("letters", [])),
                    base=item.get("base", ""), tier=int(item.get("tier", 1)))


def _order_options(item: dict, target: str) -> list[str]:
    """tap_order items carry letters, not options; the app taps one whole answer, so offer candidates."""
    letters = list(item.get("letters") or [])
    if item.get("type") != "tap_order" or not letters:
        return []
    if item.get("base"):
        return [item["base"] + l for l in letters]
    words = ["".join(p) for p in itertools.permutations(letters)]
    others = [w for w in dict.fromkeys(words) if w != target][:3]
    return sorted([target, *others])


def find_activity(ref: str, content: Content) -> Activity | None:
    item = next((i for i in content.practice_items if i["id"] == ref), None)
    return _to_activity(item) if item else None


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "")).strip()


def judge(activity: Activity, *, transcript: str | None, tap: str | None) -> str:
    """correct | wrong. Deterministic; the model never decides this."""
    if activity.type in ("tap_choice",):
        return "correct" if _norm(tap) == _norm(activity.target) else "wrong"
    if activity.type == "tap_order":
        return "correct" if _norm(tap) == _norm(activity.target) else "wrong"
    heard = " ".join(normalize(transcript or ""))
    accepts = [_norm(a) for a in ([activity.target] + activity.accept) if a]
    if not heard:
        return "wrong"
    for a in accepts:
        if heard == " ".join(normalize(a)):
            return "correct"
    # short single-word tolerance: 1 char off on ≥ 3-letter targets (ASR spelling noise)
    for a in accepts:
        na, nh = "".join(normalize(a)), "".join(normalize(heard))
        if len(na) >= 3 and (na in nh or nh in na):
            return "correct"
    return "wrong"


def fixed_intro(activity: Activity, name: str) -> str:
    if activity.type == "say_word":
        return f"{name}, यह शब्द देखो और ज़ोर से बोलो: {activity.prompt_hi}"
    return f"{name}, {activity.prompt_hi}"


def next_turn(session: Session, *, child_name: str, plan: dict, index: int, attempt: int,
              activity: Activity, transcript: str | None, tap: str | None, school_id: int,
              offline: bool) -> dict:
    """One turn of the harness. Returns what the app should show/say and the outcome."""
    verdict = judge(activity, transcript=transcript, tap=tap)
    attempts_left = attempt + 1 < MAX_ATTEMPTS  # attempt is 0-based
    situation = "praise" if verdict == "correct" else ("feedback_wrong" if attempts_left else "comfort")
    if offline:
        line = features.FALLBACK_LINES[situation].format(prompt=activity.prompt_hi)
        status = "fallback"
    else:
        line, status = features.tutor_line(session, school_id=school_id, situation=situation,
                                           activity_title=activity.prompt_hi, prompt_text=activity.prompt_hi,
                                           target=activity.target, heard=transcript or tap or "",
                                           judged=verdict)
    advance = verdict == "correct" or not attempts_left
    activities = plan["activities"]
    next_activity = activities[index + 1] if advance and index + 1 < len(activities) else None
    done = advance and next_activity is None
    return {
        "judged": verdict,
        "line_hi": line,
        "line_status": status,
        "attempt": attempt + (0 if verdict == "correct" else 1),
        "advance": advance,
        "next_index": index + 1 if advance else index,
        "next_activity": next_activity,
        "done": done,
        "record_evidence": (verdict == "correct") or (not attempts_left),
    }


def record_evidence(session: Session, *, school_id: int, class_id: int, child_id: int, activity: Activity,
                    verdict: str, home_session_id: int) -> None:
    from app.models.tables import Evidence
    session.add(Evidence(school_id=school_id, class_id=class_id, child_id=child_id,
                         checkpoint_id=activity.checkpoint_id,
                         result="correct" if verdict == "correct" else "incorrect",
                         source="home_voice" if activity.type.startswith("say") else "home_tap",
                         confidence=0.8, session_id=None, status="confirmed", quote=None))
    # note: the FK points at capture sessions (teacher captures); home evidence links via source
