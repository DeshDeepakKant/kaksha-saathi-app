"""Deterministic end-of-session report for the 30-minute voice session.

Built only from the judged child turns and the items they answered: counts, per-stage results,
the exact mistakes (item, what was heard, which sound or matra), difficult words and sounds,
checkpoints needing attention, reading speed, and short bilingual strengths/weaknesses derived
from those numbers. Nothing is invented. The AI tutor later fills `narrative` and `next_steps`
(`voice_tutor.write_narrative`); until then they stay empty with `narrative_status="fallback"`.
Schema: docs/voice_session_contract.md (Report).
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import datetime

from app.services.voice_types import MAX_ATTEMPTS, STAGES
from app.speech.assess import aksharas, describe_error

STAGE_NAMES = {
    "letter": ("Letters", "अक्षर"),
    "word_build": ("Building words", "शब्द बनाना"),
    "word_read": ("Reading words", "शब्द पढ़ना"),
    "sentence_build": ("Making sentences", "वाक्य बनाना"),
    "reading": ("Reading", "पढ़ना"),
}
WORD_KINDS = {"read_word", "build_word"}
PASSAGE_KINDS = {"read_sentence", "read_paragraph"}
STRUGGLE_TRIES = 3          # an item that needed this many tries (or failed) is "difficult"
FLUENCY_GOAL_HI = (45, 60)  # L.G2.fluency_45_60


def _ts(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes(started_at, ended_at) -> float:
    a, b = _ts(started_at), _ts(ended_at)
    if not a or not b:
        return 0.0
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return round(max(0.0, (b - a).total_seconds()) / 60.0, 1)


def item_text(item: dict) -> str:
    """What the item was about, in words a parent or teacher recognises."""
    d = item.get("display") or {}
    if item.get("kind") == "answer_question":
        return d.get("question") or item.get("prompt") or ""
    if item.get("kind") == "make_sentence":
        return ", ".join(item.get("required_words") or d.get("words") or [])
    return (item.get("target") or d.get("text") or "".join(d.get("tiles") or [])
            or item.get("prompt") or "")


def _is_silent(t: dict) -> bool:
    return bool(t.get("silent")) or t.get("verdict") == "silent"


def _is_skip(t: dict) -> bool:
    return bool(t.get("skipped")) or t.get("verdict") == "skipped"


def _is_judged(t: dict) -> bool:
    return t.get("verdict") in ("correct", "close", "wrong") and not _is_skip(t)


def _checkpoint_titles(content, cid: str) -> tuple[str, str]:
    cps = getattr(content, "checkpoints", None)
    if cps is None and isinstance(content, dict):
        cps = content.get("checkpoints")
    cp = (cps or {}).get(cid)
    if cp is None:
        return cid, cid
    if isinstance(cp, dict):
        return cp.get("title_hi") or cid, cp.get("title_en") or cid
    return getattr(cp, "title_hi", "") or cid, getattr(cp, "title_en", "") or cid


def _item_summaries(turns: list[dict], items: dict[str, dict]) -> list[dict]:
    """One record per item, in the order the child met them.

    Accepts the contract's child-turn dicts, and also transcript lines (tutor lines are ignored)
    together with an item's own `attempts` list of judged tries, which then wins because it
    carries errors and fluency."""
    order: list[str] = []
    by_item: dict[str, list[dict]] = {}
    for t in turns:
        iid = t.get("item_id")
        if iid is None or t.get("role") == "tutor":
            continue
        if iid not in by_item:
            order.append(iid)
            by_item[iid] = []
        by_item[iid].append(t)
    order += [iid for iid, it in items.items()
              if iid not in by_item and isinstance(it, dict) and it.get("attempts")]
    out = []
    for iid in order:
        ts = by_item.get(iid, [])
        item = items.get(iid) or {}
        recorded = [a for a in item.get("attempts") or [] if isinstance(a, dict)]
        judged = [t for t in (recorded or ts) if _is_judged(t)]
        first_ok = None
        for n, t in enumerate(judged, start=1):
            if t.get("verdict") == "correct":
                first_ok = int(t.get("attempt") or n)
                judged = judged[:n]          # turns after a success (if any) don't count
                break
        tries = max([len(judged)] + [int(t.get("attempt") or 0) for t in judged])
        if first_ok == 1:
            outcome = "first_try"
        elif first_ok is not None:
            outcome = "after_retry"
        elif any(_is_skip(t) for t in ts) or item.get("result") == "skipped":
            outcome = "skipped"
        elif tries >= MAX_ATTEMPTS:
            outcome = "failed"
        else:
            outcome = "unfinished"           # session ended mid-item, or the engine moved on early
        kind = item.get("kind") or next((t.get("kind") for t in ts if t.get("kind")), "")
        stage = item.get("stage") or next((t.get("stage") for t in ts if t.get("stage")), "")
        out.append({"item_id": iid, "item": item, "kind": kind, "stage": stage, "turns": judged,
                    "tries": tries, "outcome": outcome,
                    "struggled": outcome == "failed" or tries >= STRUGGLE_TRIES})
    return out


def _turn_errors(t: dict) -> list[dict]:
    return [e for e in (t.get("errors") or []) if isinstance(e, dict)]


def _is_sound(s: str) -> bool:
    return bool(s) and len(aksharas(s)) == 1


def build_report(*, lang: str, started_at, ended_at, turns: list[dict], items: dict[str, dict],
                 content=None, session_id=None) -> dict:
    """Deterministic Report dict (docs/voice_session_contract.md); narrative left empty."""
    turns = list(turns or [])
    items = items or {}
    summaries = _item_summaries(turns, items)
    attempted = [s for s in summaries if s["tries"] > 0]
    count = Counter(s["outcome"] for s in summaries)
    first_try, after_retry, failed = count["first_try"], count["after_retry"], count["failed"]
    skipped = count["skipped"]
    accuracy = round((first_try + after_retry) / len(attempted), 3) if attempted else 0.0

    reached = [s["stage"] for s in attempted if s["stage"] in STAGES]
    highest = max(reached, key=STAGES.index) if reached else None

    stages = []
    for st in STAGES:
        group = [s for s in attempted if s["stage"] == st]
        if group:
            stages.append({"stage": st, "attempted": len(group),
                           "correct": sum(1 for s in group if s["outcome"] in ("first_try", "after_retry")),
                           "failed": sum(1 for s in group if s["outcome"] == "failed")})

    # Mistakes: every item that failed or needed more than one try.
    mistakes = []
    for s in attempted:
        if s["outcome"] != "failed" and s["tries"] < 2:
            continue
        wrong_turns = [t for t in s["turns"] if t.get("verdict") != "correct"]
        seen: list[tuple] = []
        en, hi = [], []
        for t in wrong_turns:
            for e in _turn_errors(t):
                key = (e.get("type"), e.get("target"), e.get("heard"), e.get("word"))
                if key in seen:
                    continue
                seen.append(key)
                d_en, d_hi = describe_error(e)
                en.append(d_en)
                hi.append(d_hi)
        last = wrong_turns[-1] if wrong_turns else s["turns"][-1]
        mistakes.append({"item": item_text(s["item"]), "item_id": s["item_id"], "stage": s["stage"],
                         "kind": s["kind"], "heard": last.get("heard") or "", "attempts": s["tries"],
                         "solved": s["outcome"] in ("first_try", "after_retry"),
                         "errors": en[:6], "errors_hi": hi[:6]})

    # Difficult words: word items that failed / took 3+ tries, and words missed or misread in
    # sentences/paragraphs that were difficult.
    difficult_words: list[str] = []
    for s in attempted:
        if not s["struggled"]:
            continue
        if s["kind"] in WORD_KINDS:
            w = item_text(s["item"])
            if w and w not in difficult_words:
                difficult_words.append(w)
        elif s["kind"] in PASSAGE_KINDS and s["turns"]:
            for w in s["turns"][-1].get("words") or []:
                tw = w.get("target") or ""
                if tw and w.get("status") in ("wrong", "missed", "close") and tw not in difficult_words:
                    difficult_words.append(tw)

    # Difficult sounds: consonant/vowel substitutions and matra slips, counted once per turn.
    sounds: Counter = Counter()
    judged_turns = [t for s in attempted for t in s["turns"]]
    for t in judged_turns:
        per_turn = set()
        for e in _turn_errors(t):
            tg, hd = e.get("target") or "", e.get("heard") or ""
            if e.get("type") == "substitution" and _is_sound(tg) and _is_sound(hd) and tg != hd:
                per_turn.add((tg, hd))
            elif e.get("type") == "matra" and tg != hd and (tg or hd):
                per_turn.add((tg, hd))
        sounds.update(per_turn)
    difficult_sounds = [{"sound": a, "confused_with": b, "count": n}
                        for (a, b), n in sorted(sounds.items(), key=lambda kv: (-kv[1], kv[0]))]

    # Topics needing attention: checkpoints of failed or struggled items.
    topics: dict[str, dict] = {}
    for s in attempted:
        cid = s["item"].get("checkpoint_id")
        if not cid or not s["struggled"]:
            continue
        rec = topics.setdefault(cid, {"failed": [], "hard": [], "first": len(topics)})
        (rec["failed"] if s["outcome"] == "failed" else rec["hard"]).append(item_text(s["item"]))
    topics_attention = []
    for cid, rec in sorted(topics.items(), key=lambda kv: (-len(kv[1]["failed"]), kv[1]["first"])):
        title_hi, title_en = _checkpoint_titles(content, cid)
        en, hi = [], []
        if rec["failed"]:
            ex = ", ".join(rec["failed"][:3])
            en.append(f"not solved after {MAX_ATTEMPTS} tries: {ex}")
            hi.append(f"{MAX_ATTEMPTS} कोशिशों में नहीं हुआ: {ex}")
        if rec["hard"]:
            ex = ", ".join(rec["hard"][:3])
            en.append(f"needed {STRUGGLE_TRIES}+ tries: {ex}")
            hi.append(f"{STRUGGLE_TRIES} या ज़्यादा कोशिशें लगीं: {ex}")
        topics_attention.append({"checkpoint_id": cid, "title_hi": title_hi, "title_en": title_en,
                                 "reason_en": _cap("; ".join(en)), "reason_hi": "; ".join(hi)})

    # Reading speed: best attempt per paragraph, then the mean over paragraphs.
    per_para = []
    for s in attempted:
        if s["kind"] != "read_paragraph":
            continue
        w = [float((t.get("fluency") or {}).get("wcpm")) for t in s["turns"]
             if (t.get("fluency") or {}).get("wcpm") is not None]
        if w:
            per_para.append(max(w))
    fluency = {"wcpm": round(sum(per_para) / len(per_para), 1) if per_para else None,
               "paragraphs": len(per_para),
               "best_wcpm": round(max(per_para), 1) if per_para else None}

    strengths, weaknesses = _strengths_weaknesses(
        lang=lang, attempted=attempted, first_try=first_try, stages=stages, fluency=fluency,
        difficult_sounds=difficult_sounds, turns=judged_turns, skipped=skipped)

    return {
        "session_id": session_id,
        "lang": lang,
        "minutes": _minutes(started_at, ended_at),
        "items_attempted": len(attempted),
        "first_try": first_try,
        "after_retry": after_retry,
        "failed": failed,
        "skipped": skipped,
        "accuracy": accuracy,
        "highest_stage": highest,
        "stages": stages,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "mistakes": mistakes,
        "difficult_words": difficult_words,
        "difficult_sounds": difficult_sounds,
        "topics_attention": topics_attention,
        "fluency": fluency,
        "narrative": {"parent_hi": "", "parent_en": "", "teacher_en": "", "teacher_hi": ""},
        "narrative_status": "fallback",
        "next_steps": {"hi": [], "en": []},
    }


def _is_vowel_sign(s: str) -> bool:
    return unicodedata.category(s[0]) in ("Mn", "Mc")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _bullet(en: str, hi: str) -> dict:
    return {"en": en, "hi": hi}


def _strengths_weaknesses(*, lang, attempted, first_try, stages, fluency, difficult_sounds,
                          turns, skipped) -> tuple[list[dict], list[dict]]:
    strengths: list[dict] = []
    weaknesses: list[dict] = []
    n = len(attempted)

    for st in stages:
        name_en, name_hi = STAGE_NAMES.get(st["stage"], (st["stage"], st["stage"]))
        if st["attempted"] >= 2 and st["correct"] == st["attempted"]:
            strengths.append(_bullet(f"{name_en}: all {st['attempted']} correct",
                                     f"{name_hi}: सभी {st['attempted']} सही"))
        elif st["failed"] >= 2 or (st["failed"] and st["failed"] * 2 >= st["attempted"]):
            weaknesses.append(_bullet(
                f"{name_en}: {st['failed']} of {st['attempted']} not solved after {MAX_ATTEMPTS} tries",
                f"{name_hi}: {st['attempted']} में से {st['failed']} पाँच कोशिशों में नहीं हुए"))

    if n >= 5 and first_try * 10 >= n * 7:
        strengths.insert(0, _bullet(f"Got {first_try} of {n} right on the first try",
                                    f"{n} में से {first_try} पहली बार में सही"))

    wcpm = fluency.get("wcpm")
    if wcpm is not None:
        if lang == "hi" and wcpm >= FLUENCY_GOAL_HI[0]:
            strengths.append(_bullet(f"Read paragraphs at {wcpm:g} correct words per minute",
                                     f"अनुच्छेद {wcpm:g} सही शब्द प्रति मिनट की गति से पढ़ा"))
        elif lang == "hi":
            lo, hi_ = FLUENCY_GOAL_HI
            weaknesses.append(_bullet(
                f"Reading speed {wcpm:g} correct words per minute (class 2 goal {lo}–{hi_})",
                f"पढ़ने की गति {wcpm:g} सही शब्द प्रति मिनट (कक्षा 2 का लक्ष्य {lo}–{hi_})"))

    for d in [d for d in difficult_sounds if d["count"] >= 2][:3]:
        s, c, k = d["sound"], d["confused_with"], d["count"]
        if not c:
            en, hi = f"Left out the {s} matra ({k} times)", f"{s} की मात्रा छोड़ी ({k} बार)"
        elif not s:
            en, hi = f"Added an extra {c} matra ({k} times)", f"{c} की मात्रा ज़्यादा लगाई ({k} बार)"
        elif _is_vowel_sign(s):
            en, hi = f"Read the {s} matra as {c} ({k} times)", f"{s} की मात्रा को {c} पढ़ा ({k} बार)"
        else:
            en, hi = f"Said {c} instead of {s} ({k} times)", f"{s} की जगह {c} बोला ({k} बार)"
        weaknesses.append(_bullet(en, hi))

    counts = Counter()
    for t in turns:
        for e in _turn_errors(t):
            counts[e.get("type")] += 1
    if counts["not_blended"] >= 2:
        k = counts["not_blended"]
        weaknesses.append(_bullet(f"Said the sounds separately instead of blending them ({k} times)",
                                  f"आवाज़ें जोड़कर शब्द बनाने की जगह अलग-अलग बोलीं ({k} बार)"))
    if counts["missing_word"] >= 3:
        k = counts["missing_word"]
        weaknesses.append(_bullet(f"Skipped words while reading or speaking ({k} words)",
                                  f"पढ़ते/बोलते समय शब्द छोड़े ({k} शब्द)"))
    if skipped >= 2:
        weaknesses.append(_bullet(f"Skipped {skipped} questions", f"{skipped} सवाल छोड़े"))
    return strengths[:4], weaknesses[:5]
