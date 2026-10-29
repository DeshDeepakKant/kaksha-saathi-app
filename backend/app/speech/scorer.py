"""Deterministic reading/pronunciation scorer.

Compares an ASR transcript against a *known* target text. The LLM never scores
pronunciation; it only interprets these judgments afterwards.

`lang` (default "hi") selects the language rules: Hindi number words and Hindi fillers apply only
to Hindi; every other language compares numbers as digits (of any script) only.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Devanagari digits → ASCII
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

HI_NUMBER_WORDS = {
    0: ["शून्य"], 1: ["एक"], 2: ["दो"], 3: ["तीन"], 4: ["चार"], 5: ["पाँच", "पांच"],
    6: ["छह", "छः"], 7: ["सात"], 8: ["आठ"], 9: ["नौ"], 10: ["दस"], 11: ["ग्यारह"],
    12: ["बारह"], 13: ["तेरह"], 14: ["चौदह"], 15: ["पंद्रह", "पन्द्रह"], 16: ["सोलह"],
    17: ["सत्रह"], 18: ["अठारह"], 19: ["उन्नीस"], 20: ["बीस"], 21: ["इक्कीस"], 22: ["बाईस"],
    23: ["तेईस", "तेइस"], 24: ["चौबीस"], 25: ["पच्चीस"], 26: ["छब्बीस"], 27: ["सत्ताईस"],
    28: ["अट्ठाईस", "अठ्ठाईस"], 29: ["उनतीस"], 30: ["तीस"], 31: ["इकतीस"], 32: ["बत्तीस"],
    33: ["तैंतीस", "तैतीस"], 34: ["चौंतीस"], 35: ["पैंतीस"], 36: ["छत्तीस"], 37: ["सैंतीस"],
    38: ["अड़तीस"], 39: ["उनतालीस"], 40: ["चालीस"], 41: ["इकतालीस"], 42: ["बयालीस"],
    43: ["तैंतालीस"], 44: ["चवालीस"], 45: ["पैंतालीस"], 46: ["छियालीस"], 47: ["सैंतालीस"],
    48: ["अड़तालीस"], 49: ["उनचास"], 50: ["पचास"], 51: ["इक्यावन"], 52: ["बावन"],
    53: ["तिरपन"], 54: ["चौवन"], 55: ["पचपन"], 56: ["छप्पन"], 57: ["सत्तावन"],
    58: ["अट्ठावन"], 59: ["उनसठ"], 60: ["साठ"], 61: ["इकसठ"], 62: ["बासठ"], 63: ["तिरसठ"],
    64: ["चौंसठ"], 65: ["पैंसठ"], 66: ["छियासठ"], 67: ["सड़सठ"], 68: ["अड़सठ"],
    69: ["उनहत्तर"], 70: ["सत्तर"], 71: ["इकहत्तर"], 72: ["बहत्तर"], 73: ["तिहत्तर"],
    74: ["चौहत्तर"], 75: ["पचहत्तर"], 76: ["छिहत्तर"], 77: ["सतहत्तर", "सत्तहत्तर"],
    78: ["अठहत्तर"], 79: ["उनासी"], 80: ["अस्सी"], 81: ["इक्यासी"], 82: ["बयासी"],
    83: ["तिरासी"], 84: ["चौरासी"], 85: ["पचासी"], 86: ["छियासी"], 87: ["सत्तासी"],
    88: ["अट्ठासी"], 89: ["नवासी"], 90: ["नब्बे"], 91: ["इक्यानवे"], 92: ["बानवे"],
    93: ["तिरानवे"], 94: ["चौरानवे"], 95: ["पंचानवे"], 96: ["छियानवे"], 97: ["सत्तानवे"],
    98: ["अट्ठानवे"], 99: ["निन्यानवे"], 100: ["सौ"],
}

NUMBER_WORD_TO_DIGIT = {w: n for n, words in HI_NUMBER_WORDS.items() for w in words}

_PUNCT = re.compile(r"[।॥,.;:!?\"'“”‘’()\[\]…\-–—]")
_FILLERS = {"हम्म", "हां", "हाँ", "अं", "उं", "अजी", "ओ"}


def _ascii_digits(t: str) -> str:
    return "".join(str(unicodedata.decimal(c)) if unicodedata.decimal(c, None) is not None else c for c in t)


def normalize(text: str, lang: str = "hi") -> list[str]:
    t = unicodedata.normalize("NFC", text or "")
    t = (t.translate(_DEV_DIGITS) if lang == "hi" else _ascii_digits(t)).lower()
    t = _PUNCT.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    fillers = _FILLERS if lang == "hi" else ()
    return [w for w in t.split(" ") if w and w not in fillers]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class ItemScore:
    target: str
    heard: str | None
    judged: str  # correct | close | wrong | omitted
    similarity: float
    note_hi: str = ""


@dataclass
class ScoreResult:
    items: list[ItemScore] = field(default_factory=list)
    accuracy: float = 0.0
    insertions: list[str] = field(default_factory=list)
    n_correct: int = 0
    n_close: int = 0
    n_wrong: int = 0
    n_omitted: int = 0

    def summary_hi(self) -> str:
        return f"{self.n_correct} सही, {self.n_close} करीब, {self.n_wrong} गलत, {self.n_omitted} छूटे"

    def to_dict(self) -> dict:
        return {
            "items": [i.__dict__ for i in self.items],
            "accuracy": round(self.accuracy, 3),
            "insertions": self.insertions,
            "counts": {"correct": self.n_correct, "close": self.n_close,
                       "wrong": self.n_wrong, "omitted": self.n_omitted},
            "summary_hi": self.summary_hi(),
        }


def _is_number_token(t: str, lang: str = "hi") -> bool:
    return t.isdigit() or (lang == "hi" and t in NUMBER_WORD_TO_DIGIT)


def _as_number(t: str, lang: str = "hi") -> int | None:
    if t.isdigit():
        return int(t)
    return NUMBER_WORD_TO_DIGIT.get(t) if lang == "hi" else None  # no number-word table: digits only


def _pair_sim(target: str, heard: str, lang: str = "hi") -> float:
    """Similarity of one target token to one heard token, with number equivalence."""
    if target == heard:
        return 1.0
    a, b = _as_number(target, lang), _as_number(heard, lang)
    if a is not None and b is not None:
        return 1.0 if a == b else 0.0
    if a is not None or b is not None:
        # one side is a number, the other is not a number at all (e.g. "पचास" vs "कमल")
        return 0.0
    if len(target) == 1 and len(heard) == 1:
        # Single-letter checkpoints: स/श, न/ण, ब/व confusions are the pedagogically useful
        # signal, but SequenceMatcher scores any two different 1-char strings as 0.
        return 0.7
    return similarity(target, heard)


CORRECT_SIM = 0.9
CLOSE_SIM = 0.65
ATTEMPT_SIM = 0.45


def score_read(target_items: list[str], transcript: str, lang: str = "hi") -> ScoreResult:
    """Judge each target item against a monotonic reading of the transcript.

    The child reads left to right, so alignment is strictly sequential: target i is compared
    with the next spoken tokens. A token that was spoken but differs is *wrong* or *close*;
    *omitted* means the child produced no token there at all (silence / shorter reading).
    """
    res = ScoreResult()
    heard_all = normalize(transcript, lang)
    used: set[int] = set()
    cursor = 0
    for target in target_items:
        t_tokens = normalize(target, lang)
        if not t_tokens:
            continue
        n = len(t_tokens)
        window = heard_all[cursor:cursor + n]
        if not window:
            res.items.append(ItemScore(target, None, "omitted", 0.0))
            res.n_omitted += 1
            continue
        sims = [_pair_sim(a, b, lang) for a, b in zip(t_tokens, window)]
        sim = sum(sims) / len(sims)
        used.update(range(cursor, cursor + len(window)))
        if sim >= CORRECT_SIM:
            judged = "correct"
        elif sim >= CLOSE_SIM:
            judged = "close"
        else:
            judged = "wrong"
        note = _diff_note_hi(t_tokens, window) if judged == "close" and lang == "hi" else ""
        res.items.append(ItemScore(target, " ".join(window), judged, round(sim, 3), note))
        if judged == "correct":
            res.n_correct += 1
        elif judged == "close":
            res.n_close += 1
        else:
            res.n_wrong += 1
        cursor += len(window)
    res.insertions = [w for i, w in enumerate(heard_all) if i not in used]
    total = max(1, len(res.items))
    res.accuracy = (res.n_correct + 0.5 * res.n_close) / total
    return res


def _diff_note_hi(a: list[str], b: list[str]) -> str:
    for x, y in zip(a, b):
        if x != y:
            return f"'{x}' की जगह '{y}' जैसा सुनाई दिया"
    return ""
