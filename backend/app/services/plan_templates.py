"""Deterministic template plans — the fallback that keeps the flagship feature available offline.

Written by the team; reviewed by the education mentor (same review workflow as activities).
If a group's checkpoint has no reviewed template, a generic gap-practice template is used.
"""
from __future__ import annotations

from app.services.content import Content

GENERIC_TEMPLATE = {
    "title_hi": "साथ में दोहराएँ",
    "steps_hi": [
        "बोर्ड पर एक उदाहरण धीरे-धीरे करके दिखाएँ।",
        "दूसरा उदाहरण बच्चों से पूछ-पूछकर करें।",
        "तीन सवाल कॉपी में करवाएँ।",
        "हर बच्चे का एक सवाल जाँचें।",
    ],
    "materials_hi": "कोई नहीं",
    "duration_min": 8,
    "blackboard_hi": "",
    "reassessment": {"ask_hi": "(दोहराए गए अभ्यास से एक सवाल)", "expected": ""},
}


TOTAL_BUDGET_MIN = 25
MIN_BLOCK_MIN = 5


def template_plan(groups: list[dict], content: Content, budget_min: int = TOTAL_BUDGET_MIN) -> dict:
    """`groups` items: {key, checkpoint_id, title_hi, chapter, members, status}.

    Fits the plan into the teacher's time budget (docs/03 §4.2). Groups that do not fit are
    still listed (so membership is never lost) but marked `deferred` for the next day.
    """
    out_groups, remaining = [], budget_min
    for i, g in enumerate(groups):
        acts = content.activities_for({g["checkpoint_id"]})
        a = acts[0] if acts else None
        base = dict(why_hi=f"{g['title_hi']} पर अभी अभ्यास चाहिए।")
        if a:
            base.update({"activity_id": a["id"], "teacher_script_hi": " ".join(a["steps_hi"])[:600],
                         "reassessment": a.get("reassessment", {"ask_hi": "", "expected": ""})})
            want = int(a["duration_min"])
        else:
            base.update({"activity_id": "generic", "teacher_script_hi": " ".join(GENERIC_TEMPLATE["steps_hi"]),
                         "reassessment": GENERIC_TEMPLATE["reassessment"],
                         "generic_steps_hi": GENERIC_TEMPLATE["steps_hi"]})
            want = GENERIC_TEMPLATE["duration_min"]
        if remaining < MIN_BLOCK_MIN:
            base.update({"time_min": 0, "deferred": True,
                         "defer_note_hi": "आज समय नहीं: कल इस समूह से शुरू करें।"})
        else:
            base.update({"time_min": max(MIN_BLOCK_MIN, min(want, remaining)), "deferred": False})
            remaining -= base["time_min"]
        base.update({"key": g["key"], "order": i + 1})
        out_groups.append(base)
    notes = []
    if any(g.get("unassessed") for g in groups):
        notes.append("जिन बच्चों का मूल्यांकन बाकी है, उनसे 3 सवाल पूछें।")
    if any(g.get("deferred") for g in out_groups):
        notes.append("जो समूह आज नहीं आए, वे कल पहले।")
    return {"groups": out_groups, "whole_class_note_hi": " ".join(notes),
            "today_observation_to_collect_hi": "आज के अभ्यास के बाद 2 बच्चों का सवाल जाँचें।",
            "template": True}


def render_group(group: dict, children_by_roll: dict[int, dict]) -> dict:
    """Replace {R12} tokens with display names (server-side, after validation)."""
    import re

    def sub(text: str) -> str:
        if not isinstance(text, str):
            return text
        def repl(m):
            rolls = [int(x) for x in re.findall(r"\d+", m.group(1))]
            names = [children_by_roll[r]["first_name"] for r in rolls if r in children_by_roll]
            return ", ".join(names) if names else m.group(0)
        return re.sub(r"\{([Rr][\d,\sRr]+)\}", repl, text)

    out = dict(group)
    for k in ("why_hi", "teacher_script_hi", "whole_class_note_hi"):
        if k in out:
            out[k] = sub(out[k])
    return out
