"""Deterministic, offline extraction used when Claude is unavailable (or no key is configured).

Not as capable as the model, but it keeps the product usable: the teacher gets pre-filled
chips (names found in the transcript, checkpoint guessed from keywords) and confirms them.
Every rule here is visible in `docs/04_AI_SPECIFICATION.md` under fallbacks.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.services.content import Checkpoint
from app.services.resolver import Resolution, resolve_names

# Specific phrases win regardless of position ("जोड़ हासिल" is a carrying lesson even
# though "जोड़" appears first in the sentence).
PHRASES: list[tuple[tuple[str, ...], str]] = [
    (("बिना उधार", "without borrowing"), "N.G2.sub_2digit_no_borrow"),
    (("जोड़ हासिल", "हासिल के साथ", "हासिल वाला"), "N.G2.add_2digit_carry"),
    (("शब्द बना", "शब्द बनाना", "word formation"), "L.G2.word_formation"),
    (("तीन अंक", "3 अंक", "तीन-अंक"), "N.G3.add_sub_3digit"),
]

# keyword → checkpoint hint (lowercase substrings; Devanagari and English)
KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("बिना उधार",), "N.G2.sub_2digit_no_borrow"),
    (("उधार", "borrow", "उधारी"), "N.G2.sub_2digit_borrow"),
    (("तीन अंक", "3 अंक", "तीन-अंक"), "N.G3.add_sub_3digit"),
    (("घटाव", "घटा", "subtract"), "N.G1.sub_single"),
    (("हासिल", "carry"), "N.G2.add_2digit_carry"),
    (("जोड़", "जोड़ा", "add"), "N.G2.add_2digit_no_carry"),
    (("दहाई", "इकाई", "place value", "स्थानीय"), "N.G2.place_value_99"),
    (("पहाड़ा", "पहाड़े", "table"), "N.G3.tables_2_5"),
    (("गुणा", "multiply"), "N.G3.mult_concept"),
    (("स्वर",), "L.G1.swar"),
    (("व्यंजन",), "L.G1.vyanjan"),
    (("संयुक्ताक्षर", "संयुक्त"), "L.G2.conjuncts"),
    (("गिनती", "गिनो", "counting"), "N.G1.count_to_20"),
    (("मात्रा", "मात्राएँ", "मात्राएं"), "L.G1.matra_basic"),
    (("शब्द", "word"), "L.G1.blend_no_matra"),
    (("वाक्य", "sentence"), "L.G1.read_short_sentences"),
    (("पढ़", "पढ़ना", "read", "गति"), "L.G1.read_matra_words"),
]
NEG = ("नहीं", "समझ", "कठिन", "गलत", "फंस", "अटक", "भूल", "गलती", "अशुद्ध",
       "struggle", "hard", "wrong")
POS = ("सही", "खुद किए", "अच्छा", "ठीक", "आ गया", "correct", "all right", "सब")
ABSENT_STRONG = ("अनुपस्थित", "गैरहाज़िर", "गैरहाजिर", "absent", "छुट्टी", "बीमार")
# "नहीं आया" alone is ambiguous: "मीना को उधार समझ नहीं आया" means she did not understand.
ABSENT_WEAK = ("नहीं आए", "नहीं आया", "नहीं आई")
ABSENT_MEANING_MARKERS = ("समझ", "आता", "आती", "पढ़", "करने", "जमा", "हुआ")


def is_absent(clause: str) -> bool:
    if any(w in clause for w in ABSENT_STRONG):
        return True
    return (any(w in clause for w in ABSENT_WEAK)
            and not any(w in clause for w in ABSENT_MEANING_MARKERS))


def _all_keyword_checkpoints(cps: list[Checkpoint]) -> list[str]:
    return [c.id for c in cps]


def guess_checkpoint(text: str, checkpoints: list[Checkpoint]) -> str | None:
    """Pick the checkpoint whose trigger word appears EARLIEST in the note (ties: list order).

    'बिना उधार' is listed before 'उधार' and appears earlier, so a no-borrow note is not
    mistaken for a borrowing note; 'तीन अंक' before 'जोड़' keeps 3-digit work at grade 3.
    """
    ids = {c.id for c in checkpoints}
    low = text.lower()
    for words, cid in PHRASES:
        if cid in ids and any(w in low for w in words):
            return cid
    best: tuple[int, int, str] | None = None
    for order, (words, cid) in enumerate(KEYWORDS):
        if cid not in ids:
            continue
        positions = [low.find(w) for w in words if w in low]
        if not positions:
            continue
        pos = min(positions)
        key = (pos, order, cid)
        if best is None or key < best:
            best = key
    return best[2] if best else None


def extract_note_rules(transcript: str, children: list, checkpoints: list[Checkpoint]) -> dict:
    text = transcript.strip()
    cid = guess_checkpoint(text, checkpoints)
    # split into clauses so a status near a name is attributed correctly
    clauses = re.split(r"[।.,;!\n]+", text)
    out_children, unresolved = [], []
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        found: list[Resolution] = []
        for ch in children:
            if ch.first_name and ch.first_name in clause:
                found.append(Resolution(ch, "matched", [ch]))
        if not found:
            # fuzzy: look for names with 1–2 char edits inside the clause
            for ch in children:
                if len(ch.first_name) >= 3 and fuzz.partial_ratio(ch.first_name, clause) >= 90 and ch.first_name not in clause:
                    found.append(Resolution(ch, "fuzzy", [ch]))
        for r in found:
            ch = r.child
            if is_absent(clause):
                out_children.append({"name": ch.first_name, "status": "absent", "confidence": 0.9, "roll": ch.roll_no})
                continue
            if not cid:
                unresolved.append({"name": ch.first_name, "reason": "no_checkpoint_guessed"})
                continue
            if any(w in clause for w in NEG):
                result = "incorrect"
            elif any(w in clause for w in POS):
                result = "correct"
            else:
                unresolved.append({"name": ch.first_name, "reason": "no_status_word"})
                continue
            out_children.append({"name": ch.first_name, "roll": ch.roll_no, "status": "present",
                                 "checkpoint_id": cid, "result": result, "confidence": 0.6,
                                 "quote": clause[:200]})
    taught = [{"checkpoint_id": cid, "quote": text[:200]}] if cid else []
    return {"taught": taught, "children": out_children, "unresolved": unresolved,
            "rules_only": True}


_MATH = re.compile(r"(\d{1,4})\s*([+\-−×x*])\s*(\d{1,4})\s*=\s*(\d{1,5})")


def extract_photo_rules(ocr_text: str | None, checkpoints: list[Checkpoint]) -> dict:
    """Used only when the client sends an OCR/typed transcription of the page (no vision available)."""
    questions = []
    for m in _MATH.finditer(ocr_text or ""):
        a, op, b, ans = m.group(1), m.group(2), m.group(3), m.group(4)
        op_n = "−" if op in "-−" else ("×" if op in "×x*" else "+")
        cid = None
        if op_n == "−":
            cid = "N.G2.sub_2digit_borrow" if len(a) > 1 and int(a[-1]) < int(b[-1]) else "N.G1.sub_single"
        elif op_n == "+":
            cid = "N.G2.add_2digit_carry" if (int(a[-1]) + int(b[-1])) >= 10 else "N.G1.add_single"
        elif op_n == "×":
            cid = "N.G3.mult_concept"
        if cid not in {c.id for c in checkpoints}:
            cid = None
        questions.append({"printed": f"{a} {op_n} {b} =", "student_answer": ans, "checkpoint_id": cid,
                          "self_verdict": "unclear", "confidence": 0.7, "mistake_pattern": ""})
    return {"page": {"legible": bool(questions), "page_confidence": 0.6, "subject_guess": "numeracy"},
            "questions": questions, "rules_only": True}
