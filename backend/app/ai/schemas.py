"""JSON schemas + validators for every structured AI output.

The validator receives the raw tool input and returns a normalised dict or raises
`ValueError` (which triggers one corrective retry in `llm.structured`).
"""
from __future__ import annotations

import re

RESULTS = {"correct", "partial", "incorrect", "unattempted"}

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "taught": {"type": "array", "items": {"type": "object", "properties": {
            "checkpoint_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["checkpoint_id"]}},
        "children": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "status": {"type": "string", "enum": ["absent", "present", "correct", "partial", "incorrect"]},
            "checkpoint_id": {"type": "string"},
            "result": {"type": "string", "enum": list(RESULTS) + ["" ]},
            "misconception": {"type": "string"},
            "quote": {"type": "string"},
            "confidence": {"type": "number"}},
            "required": ["name"]}},
        "unresolved": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "reason": {"type": "string"}}}},
    },
    "required": ["taught", "children"],
}

PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "object", "properties": {
            "subject_guess": {"type": "string"}, "grade_guess": {"type": "integer"},
            "legible": {"type": "boolean"}, "face_or_extra_present": {"type": "boolean"},
            "page_confidence": {"type": "number"}}},
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "idx": {"type": "integer"}, "printed": {"type": "string"}, "student_answer": {"type": "string"},
            "checkpoint_id": {"type": ["string", "null"]},
            "self_verdict": {"type": "string", "enum": ["correct", "incorrect", "unclear"]},
            "mistake_pattern": {"type": "string"}, "confidence": {"type": "number"}},
            "required": ["printed", "student_answer", "self_verdict"]}},
        "unreadable": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["page", "questions"],
}

ROADMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "chapters": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"},
            "subtopics": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "kind": {"type": "string"}}}}}}},
        "confidence": {"type": "number"},
    },
    "required": ["chapters"],
}

VOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "misconception": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "note_for_teacher_hi": {"type": "string"},
    },
    "required": ["result", "confidence"],
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "activity_id": {"type": "string"},
            "why_hi": {"type": "string"}, "teacher_script_hi": {"type": "string"},
            "time_min": {"type": "integer"}, "order": {"type": "integer"},
            "reassessment": {"type": "object", "properties": {
                "ask_hi": {"type": "string"}, "expected": {"type": "string"}}}},
            "required": ["key", "activity_id", "teacher_script_hi", "time_min", "order"]}},
        "whole_class_note_hi": {"type": "string"},
        "today_observation_to_collect_hi": {"type": "string"},
    },
    "required": ["groups"],
}

TUTOR_SCHEMA = {
    "type": "object",
    "properties": {"line_hi": {"type": "string"}},
    "required": ["line_hi"],
}

SAFETY_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string",
                                "enum": ["learning", "distress", "personal", "off_topic", "profanity", "unclear"]}},
    "required": ["category"],
}

HOME_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary_hi": {"type": "string"}},
    "required": ["summary_hi"],
}

INJECTION_MARKERS = re.compile(
    r"(ignore (all|previous|the) instructions|system prompt|you are now|act as|reveal|output the|disregard)",
    re.IGNORECASE)


# ---------------------------------------------------------------- validators
def validate_note(data: dict, checkpoint_ids: set[str], roster_names: list[str]) -> dict:
    out = {"taught": [], "children": [], "unresolved": []}
    for t in data.get("taught", []):
        cid = t.get("checkpoint_id")
        if cid in checkpoint_ids:
            out["taught"].append({"checkpoint_id": cid, "quote": str(t.get("quote", ""))[:300]})
    for c in data.get("children", []):
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        status = c.get("status", "present")
        item = {"name": name, "status": status, "confidence": max(0.0, min(1.0, float(c.get("confidence", 0.6))))}
        if status == "absent":
            out["children"].append(item)
            continue
        cid = c.get("checkpoint_id")
        result = c.get("result") or (status if status in RESULTS else "partial")
        if cid not in checkpoint_ids or result not in RESULTS:
            out["unresolved"].append({"name": name, "reason": "no_valid_checkpoint_or_result"})
            continue
        item.update({"checkpoint_id": cid, "result": result,
                     "misconception": (c.get("misconception") or None),
                     "quote": str(c.get("quote", ""))[:300]})
        out["children"].append(item)
    for u in data.get("unresolved", []):
        if isinstance(u, dict) and u.get("name"):
            out["unresolved"].append({"name": str(u["name"])[:60], "reason": str(u.get("reason", ""))[:80]})
    if not out["children"] and not out["taught"]:
        raise ValueError("extraction produced no usable taught topic or child evidence")
    return out


def validate_photo(data: dict, checkpoint_ids: set[str]) -> dict:
    page = data.get("page") or {}
    result = {"page": {
        "subject_guess": str(page.get("subject_guess", ""))[:20],
        "grade_guess": int(page.get("grade_guess", 0) or 0),
        "legible": bool(page.get("legible", True)),
        "face_or_extra_present": bool(page.get("face_or_extra_present", False)),
        "page_confidence": max(0.0, min(1.0, float(page.get("page_confidence", 0.6)))),
    }, "questions": [], "unreadable": [int(i) for i in data.get("unreadable", []) if isinstance(i, (int, float))]}
    for q in data.get("questions", []):
        printed = str(q.get("printed", "")).strip()
        answer = str(q.get("student_answer", "")).strip()
        if not printed:
            continue
        cid = q.get("checkpoint_id")
        result["questions"].append({
            "printed": printed[:120], "student_answer": answer[:60],
            "checkpoint_id": cid if cid in checkpoint_ids else None,
            "self_verdict": q.get("self_verdict", "unclear") if q.get("self_verdict") in ("correct", "incorrect", "unclear") else "unclear",
            "mistake_pattern": str(q.get("mistake_pattern", ""))[:60],
            "confidence": max(0.0, min(1.0, float(q.get("confidence", 0.6)))),
        })
    if not result["questions"] and result["page"]["legible"]:
        raise ValueError("no questions extracted from a page marked legible")
    return result


def validate_roadmap(data: dict) -> dict:
    chapters = []
    for ch in data.get("chapters", []):
        title = str(ch.get("title", "")).strip()
        if not title:
            continue
        subs = [{"text": str(s.get("text", "")).strip(), "kind": str(s.get("kind", ""))}
                for s in ch.get("subtopics", []) if str(s.get("text", "")).strip()]
        chapters.append({"title": title[:120], "subtopics": subs[:40]})
    if not chapters:
        raise ValueError("no chapters found")
    return {"chapters": chapters[:40], "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.6))))}


def validate_voice(data: dict, misconceptions: set[str]) -> dict:
    if data.get("result") not in ("correct", "partial", "incorrect"):
        raise ValueError("bad voice result")
    misc = data.get("misconception")
    return {"result": data["result"], "misconception": misc if misc in misconceptions else None,
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.6)))),
            "note_for_teacher_hi": str(data.get("note_for_teacher_hi", ""))[:200]}


def validate_plan(data: dict) -> dict:
    groups = []
    for g in data.get("groups", []):
        if not g.get("key") or not g.get("activity_id"):
            continue
        groups.append({
            "key": g["key"], "activity_id": g["activity_id"],
            "why_hi": str(g.get("why_hi", ""))[:300],
            "teacher_script_hi": str(g.get("teacher_script_hi", ""))[:600],
            "time_min": int(g.get("time_min", 5)),
            "order": int(g.get("order", 99)),
            "reassessment": {"ask_hi": str((g.get("reassessment") or {}).get("ask_hi", ""))[:120],
                             "expected": str((g.get("reassessment") or {}).get("expected", ""))[:60]},
        })
    if not groups:
        raise ValueError("plan contained no groups")
    return {"groups": groups,
            "whole_class_note_hi": str(data.get("whole_class_note_hi", ""))[:300],
            "today_observation_to_collect_hi": str(data.get("today_observation_to_collect_hi", ""))[:200]}


BANNED_PERSONAL = re.compile(r"(मोबाइल|फोन|नंबर|पता|घर कहाँ|कहाँ रहते|मिलने|अकेले)", re.UNICODE)
BANNED_SHAME = re.compile(r"(कमज़ोर|कमजोर|बेवकूफ|धीमे|धीमा|गलत बच्चे|बुरा|नालायक)", re.UNICODE)


def validate_tutor_line(text: str) -> str:
    t = (text or "").strip()
    if not t:
        raise ValueError("empty tutor line")
    if len(t) > 200 or t.count("।") + t.count(".") + t.count("?") > 2:
        raise ValueError("tutor line too long")
    if BANNED_PERSONAL.search(t) or BANNED_SHAME.search(t):
        raise ValueError("tutor line contains blocked content")
    if INJECTION_MARKERS.search(t):
        raise ValueError("tutor line regurgitates instructions")
    return t


def validate_safety(data: dict) -> dict:
    cat = data.get("category")
    if cat not in ("learning", "distress", "personal", "off_topic", "profanity", "unclear"):
        raise ValueError("bad category")
    return {"category": cat}


def validate_home_summary(data: dict) -> dict:
    s = str(data.get("summary_hi", "")).strip()
    if not s:
        raise ValueError("empty summary")
    lines = [ln for ln in s.splitlines() if ln.strip()]
    if len(lines) > 3:
        raise ValueError("summary must be at most 3 lines")
    return {"summary_hi": "\n".join(lines)[:400]}
