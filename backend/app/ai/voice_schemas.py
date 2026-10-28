"""JSON schemas + validators for the 30-minute voice session's Claude calls (app/ai/voice_tutor.py).

Code is the gate: every generated item, tutor line, open-answer verdict and report narrative is
checked here before it reaches a child or a parent. The same item validator also checks the
reviewed fallback bank (content/voice_bank.json) in the tests, so AI items and bank items obey one
set of rules. Validators raise `ValueError` (which gives Claude one corrective retry in
`llm.structured`) or return a list of problems for per-item filtering.
"""
from __future__ import annotations

import re
import unicodedata

from app.ai.schemas import BANNED_PERSONAL, BANNED_SHAME, INJECTION_MARKERS
from app.services.voice_types import KINDS, LANGS, STAGES

# ---------------------------------------------------------------- item shape rules
STAGE_KINDS: dict[str, tuple[str, ...]] = {
    "letter": ("read_letter", "say_sound"),
    "word_build": ("build_word",),
    "word_read": ("read_word",),
    "sentence_build": ("make_sentence",),
    "reading": ("read_sentence", "read_paragraph"),   # answer_question only as a paragraph followup
}
# Recording window per kind (seconds); paragraphs scale with length (see record_seconds).
RECORD_S = {"read_letter": 4, "say_sound": 4, "build_word": 5, "read_word": 5, "make_sentence": 10,
            "read_sentence": 8, "read_paragraph": 30, "answer_question": 10}
PARA_MAX_WORDS = {1: 45, 2: 60}        # grade -> longest paragraph; grade 3+ -> 70
PARA_MIN_WORDS, PARA_MAX_WORDS_TOP = 25, 70
SENTENCE_WORDS = (3, 10)
WORD_CHARS = (1, 12)
ITEM_KEYS = ("id", "stage", "kind", "lang", "checkpoint_id", "prompt", "display", "target", "accept",
             "required_words", "keywords", "max_record_s", "difficulty", "source", "followups")
NO_REVEAL_KINDS = ("build_word", "answer_question")   # the child must work the answer out
REVEAL_FROM_ATTEMPT = 4

# Small token-level blocklist (exact tokens after normalisation; inflections listed explicitly).
UNSAFE_HI = {
    "मार", "मारो", "मारा", "मारी", "मारे", "मारना", "मारेगा", "मरना", "मरा", "मरी", "मरे", "मर", "मौत",
    "मृत्यु", "खून", "ख़ून", "हत्या", "क़त्ल", "कत्ल", "बंदूक", "बन्दूक", "चाकू", "छुरा", "तलवार", "बम",
    "युद्ध", "लाश", "शराब", "दारू", "सिगरेट", "बीड़ी", "तंबाकू", "गुटखा", "जुआ", "नशा", "गाली", "ज़हर",
    "जहर", "आत्महत्या", "पिटाई", "थप्पड़", "बेवकूफ", "बेवकूफ़", "मूर्ख", "नालायक", "कमीना", "चुड़ैल",
    "डरावना", "डरावनी", "सेक्स", "शत्रु", "दुश्मन", "गांधी", "गाँधी", "मोदी", "नेहरू",
}
UNSAFE_EN = {
    "kill", "kills", "killed", "killing", "die", "died", "dies", "dying", "dead", "death", "blood",
    "bloody", "gun", "guns", "knife", "knives", "sword", "bomb", "bombs", "war", "shoot", "shot",
    "murder", "beer", "wine", "alcohol", "drunk", "cigarette", "tobacco", "drug", "drugs", "gamble",
    "stupid", "idiot", "dumb", "hate", "poison", "slap", "sex", "sexy", "scary", "ghost", "enemy",
    "gandhi", "modi", "nehru",
}
SHAME_EN = re.compile(r"\b(weak|slow|lazy|bad|dull|useless|failure)\b", re.IGNORECASE)

PUNCT = "।॥.,?!'\"“”‘’-–—:;…()"
_PUNCT_RE = re.compile("[" + re.escape(PUNCT) + "]")
_NAME = "{name}"


# ---------------------------------------------------------------- text helpers
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def norm(s: str) -> str:
    """Comparison form: NFC, lower-case, no punctuation, single spaces."""
    s = _PUNCT_RE.sub(" ", nfc(s).replace(_NAME, " ").lower())
    return " ".join(s.split())


def tokens(s: str) -> list[str]:
    return norm(s).split()


def word_count(s: str) -> int:
    return len(tokens(s))


def _is_deva(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def _is_deva_mark(ch: str) -> bool:
    o = ord(ch)
    return (0x0900 <= o <= 0x0903 or 0x093A <= o <= 0x094F or 0x0951 <= o <= 0x0957
            or 0x0962 <= o <= 0x0963 or ch in "‌‍")


def graphemes(s: str) -> list[str]:
    """Aksharas for Devanagari (base + matras/nukta/virama-joined consonants), chars otherwise."""
    out: list[str] = []
    for ch in nfc(s).strip():
        if out and (_is_deva_mark(ch) or out[-1].endswith("्")):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def script_ok(text: str, lang: str, *, allow_name: bool = False) -> bool:
    """hi: Devanagari letters only; en: ASCII letters only. Spaces/punctuation allowed either way."""
    t = nfc(text)
    if allow_name:
        t = t.replace(_NAME, " ")
    if "{" in t or "}" in t:
        return False
    has_letter = False
    for ch in t:
        if ch.isspace() or ch in PUNCT:
            continue
        if lang == "hi":
            if not _is_deva(ch) and ch not in "‌‍":
                return False
            if ch.isdigit() or ch in "०१२३४५६७८९":
                return False
        else:
            if not ("a" <= ch.lower() <= "z"):
                return False
        has_letter = True
    return has_letter


def unsafe_words(text: str) -> list[str]:
    toks = set(tokens(text))
    return sorted(toks & (UNSAFE_HI | UNSAFE_EN))


def record_seconds(kind: str, text: str = "") -> int:
    if kind == "read_paragraph":
        return max(30, min(90, round(word_count(text) * 1.5)))
    return RECORD_S.get(kind, 8)


def para_max_words(grade: int | None) -> int:
    g = max(1, int(grade or 3))
    return PARA_MAX_WORDS.get(g, PARA_MAX_WORDS_TOP)


def _contains(hay: str, needle: str, lang: str) -> bool:
    """Whole-word containment for English, substring for Devanagari (aksharas glue inside words)."""
    h, n = norm(hay), norm(needle)
    if not n:
        return False
    if lang == "en":
        return re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", h) is not None
    return n in h


def _strs(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


# ---------------------------------------------------------------- item validator
def item_problems(item: dict, *, lang: str, stage: str | None = None, grade: int | None = None,
                  avoid: set[str] | None = None, followup: bool = False, context: str = "") -> list[str]:
    """Every rule an item must pass before a child sees it. [] means valid."""
    p: list[str] = []
    if not isinstance(item, dict):
        return ["not an object"]
    for k in ITEM_KEYS:
        if k not in item:
            p.append(f"missing {k}")
    if p:
        return p
    kind, st = item["kind"], item["stage"]
    if item["lang"] != lang or lang not in LANGS:
        p.append("wrong lang")
    if st not in STAGES or (stage and st != stage):
        p.append(f"wrong stage {st}")
    if kind not in KINDS:
        return p + [f"unknown kind {kind}"]
    if followup:
        if kind != "answer_question":
            p.append("followup must be answer_question")
    elif kind not in STAGE_KINDS.get(st, ()):
        p.append(f"kind {kind} not allowed in stage {st}")
    if not isinstance(item["id"], str) or not item["id"]:
        p.append("bad id")
    if item["difficulty"] not in (1, 2, 3):
        p.append("difficulty must be 1..3")
    if not isinstance(item["max_record_s"], int) or not 2 <= item["max_record_s"] <= 120:
        p.append("bad max_record_s")
    if item["source"] not in ("ai", "bank"):
        p.append("bad source")
    disp = item["display"] if isinstance(item["display"], dict) else {}
    if not isinstance(item["display"], dict):
        p.append("display must be an object")
    prompt = item["prompt"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 220:
        p.append("bad prompt")
    elif not script_ok(prompt, lang, allow_name=True):
        p.append("prompt in wrong script")
    for k in ("accept", "required_words", "keywords"):
        if not isinstance(item[k], list) or len(_strs(item[k])) != len(item[k]):
            p.append(f"{k} must be a list of strings")
    target = item["target"]
    text = disp.get("text") if isinstance(disp.get("text"), str) else None
    texts = [prompt if isinstance(prompt, str) else "", target or "", text or "",
             str(disp.get("question") or ""), *_strs(disp.get("tiles")), *_strs(disp.get("words")),
             *_strs(item["accept"]), *_strs(item["required_words"]), *_strs(item["keywords"])]
    for t in texts[1:]:
        if t and not script_ok(t, lang):
            p.append(f"wrong script: {t[:30]}")
            break
    bad = unsafe_words(" ".join(texts))
    if bad:
        p.append(f"unsafe words: {bad}")
    if avoid:
        for v in (item["id"], target or "", text or ""):
            if v and (v in avoid or norm(v) in avoid):
                p.append("item is in avoid list")
                break

    def single_word(w) -> bool:
        return isinstance(w, str) and len(tokens(w)) == 1 and WORD_CHARS[0] <= len(norm(w)) <= WORD_CHARS[1]

    if kind == "read_letter":
        if not isinstance(target, str) or text != target:
            p.append("read_letter: display.text must equal target")
        elif not 1 <= len(graphemes(target)) <= 2 or len(tokens(target)) != 1:
            p.append("read_letter: 1-2 graphemes")
    elif kind == "say_sound":
        if not isinstance(target, str) or not 1 <= len(graphemes(target)) <= 2:
            p.append("say_sound: target must be 1-2 graphemes")
        elif not single_word(text):
            p.append("say_sound: display.text must be one word")
        elif not norm(text).startswith(norm(target)):
            p.append("say_sound: word must start with target")
    elif kind == "build_word":
        tiles = _strs(disp.get("tiles"))
        if not single_word(target):
            p.append("build_word: target must be one word of 1-12 chars")
        elif not 2 <= len(tiles) <= 5 or len(tiles) != len(disp.get("tiles") or []):
            p.append("build_word: 2-5 tiles")
        elif nfc("".join(tiles)) != nfc(target):
            p.append("build_word: tiles do not join to target")
        elif lang == "hi" and any(_is_deva_mark(t[0]) or t.endswith("\u094d") for t in map(nfc, tiles)):
            p.append("build_word: each Hindi tile must be a whole akshara (no lone matra or half letter)")
        if text:
            p.append("build_word: display.text would reveal the answer")
        if isinstance(target, str) and isinstance(prompt, str) and _contains(prompt, target, lang):
            p.append("build_word: prompt reveals the answer")
    elif kind == "read_word":
        if not single_word(target) or text != target:
            p.append("read_word: one word of 1-12 chars, display.text == target")
    elif kind == "make_sentence":
        req = _strs(item["required_words"])
        if target is not None:
            p.append("make_sentence: target must be null")
        if not 2 <= len(req) <= 3 or not all(single_word(w) for w in req):
            p.append("make_sentence: 2-3 single required words")
        elif [norm(w) for w in _strs(disp.get("words"))] != [norm(w) for w in req]:
            p.append("make_sentence: display.words must equal required_words")
        elif len({norm(w) for w in req}) != len(req):
            p.append("make_sentence: duplicate required words")
        for ex in _strs(item["accept"]):
            if not SENTENCE_WORDS[0] <= word_count(ex) <= SENTENCE_WORDS[1]:
                p.append("make_sentence: example must have 3-10 words")
            elif not all(norm(w) in tokens(ex) for w in req):
                p.append("make_sentence: example misses a required word")
    elif kind == "read_sentence":
        if not isinstance(target, str) or text != target:
            p.append("read_sentence: display.text must equal target")
        elif not SENTENCE_WORDS[0] <= word_count(target) <= SENTENCE_WORDS[1]:
            p.append("read_sentence: 3-10 words")
    elif kind == "read_paragraph":
        fus = item["followups"] if isinstance(item["followups"], list) else []
        if not isinstance(target, str) or text != target:
            p.append("read_paragraph: display.text must equal target")
        else:
            wc = word_count(target)
            if not PARA_MIN_WORDS <= wc <= para_max_words(grade):
                p.append(f"read_paragraph: {wc} words, allowed {PARA_MIN_WORDS}-{para_max_words(grade)}")
        if not 1 <= len(fus) <= 2:
            p.append("read_paragraph: needs 1-2 answer_question followups")
        for f in fus:
            fp = item_problems(f, lang=lang, stage="reading", grade=grade, followup=True, context=text or "")
            p.extend(f"followup: {x}" for x in fp)
    elif kind == "answer_question":
        q = disp.get("question")
        kws = _strs(item["keywords"])
        if not isinstance(q, str) or not q.strip() or len(q) > 160 or not script_ok(q, lang):
            p.append("answer_question: bad question")
        elif not isinstance(target, str) or not target.strip() or word_count(target) > 6:
            p.append("answer_question: target must be a short answer")
        elif not 1 <= len(kws) <= 4 or not all(norm(k) for k in kws):
            p.append("answer_question: 1-4 keywords")
        else:
            if _contains(q, target, lang) or all(_contains(q, k, lang) for k in kws):
                p.append("answer_question: question gives the answer away")
            if context and not all(_contains(context, k, lang) for k in kws):
                p.append("answer_question: keyword not found in the paragraph")
    if not followup and kind != "read_paragraph" and item["followups"]:
        p.append("only read_paragraph may have followups")
    return p


# ---------------------------------------------------------------- Claude: item generation
_RAW_FOLLOWUP = {
    "type": "object",
    "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                   "accept": {"type": "array", "items": {"type": "string"}},
                   "keywords": {"type": "array", "items": {"type": "string"}},
                   "inferential": {"type": "boolean"}},
    "required": ["question", "answer", "keywords"],
}
ITEMS_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": [k for k in KINDS if k != "answer_question"]},
        "checkpoint_id": {"type": ["string", "null"]},
        "prompt": {"type": "string"},
        "text": {"type": "string"},
        "tiles": {"type": "array", "items": {"type": "string"}},
        "words": {"type": "array", "items": {"type": "string"}},
        "target": {"type": ["string", "null"]},
        "accept": {"type": "array", "items": {"type": "string"}},
        "example": {"type": "string"},
        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
        "followups": {"type": "array", "items": _RAW_FOLLOWUP},
    }, "required": ["kind", "prompt", "difficulty"]}}},
    "required": ["items"],
}

# ---------------------------------------------------------------- Claude: tutor line
TUTOR_LINE_SCHEMA = {
    "type": "object",
    "properties": {"line": {"type": "string"}},
    "required": ["line"],
}


def validate_tutor_text(text: str, *, lang: str, item: dict | None = None, attempt: int = 1) -> str:
    """<= 2 short sentences, right script, kind, no answer reveal before attempt 4."""
    t = " ".join(nfc(text).split())
    if not t:
        raise ValueError("empty line")
    if len(t) > 180:
        raise ValueError("line longer than 180 characters")
    sentences = [s for s in re.split(r"[।.?!]+", t) if s.strip()]
    if len(sentences) > 2:
        raise ValueError("more than 2 sentences")
    if not script_ok(t, lang, allow_name=True):
        raise ValueError(f"line must be in {'Devanagari Hindi' if lang == 'hi' else 'plain English'} only")
    if unsafe_words(t) or BANNED_PERSONAL.search(t) or BANNED_SHAME.search(t) or SHAME_EN.search(t):
        raise ValueError("line contains blocked words")
    if INJECTION_MARKERS.search(t):
        raise ValueError("line repeats instructions")
    if item and item.get("kind") in NO_REVEAL_KINDS and attempt < REVEAL_FROM_ATTEMPT:
        secrets = [item.get("target") or "", *(item.get("accept") or [])]
        if item.get("kind") == "answer_question":
            secrets += list(item.get("keywords") or [])
        if any(s and _contains(t, s, lang) for s in secrets):
            raise ValueError("line gives the answer away; hint without saying it")
    return t


# ---------------------------------------------------------------- Claude: open answers
OPEN_EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "close", "wrong"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


def validate_open_eval(data: dict) -> dict:
    v = data.get("verdict")
    if v not in ("correct", "close", "wrong"):
        raise ValueError("verdict must be correct, close or wrong")
    reason = " ".join(str(data.get("reason", "")).split())[:200]
    if not reason:
        raise ValueError("reason required")
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.7))))
    except (TypeError, ValueError):
        conf = 0.7
    return {"verdict": v, "confidence": conf, "reason": reason}

# ---------------------------------------------------------------- Claude: report narrative
NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "object", "properties": {
            "parent_hi": {"type": "string"}, "parent_en": {"type": "string"},
            "teacher_en": {"type": "string"}, "teacher_hi": {"type": "string"}},
            "required": ["parent_hi", "parent_en", "teacher_en", "teacher_hi"]},
        "next_steps": {"type": "object", "properties": {
            "hi": {"type": "array", "items": {"type": "string"}},
            "en": {"type": "array", "items": {"type": "string"}}},
            "required": ["hi", "en"]},
    },
    "required": ["narrative", "next_steps"],
}
_NUM_RE = re.compile(r"[0-9०-९]+(?:[.,][0-9०-९]+)?")
_QUOTED_RE = re.compile(r"[\"'“‘]([^\"'”’]{1,40})[\"'”’]")
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.findall(text):
        try:
            out.append(float(m.translate(_DEVA_DIGITS).replace(",", ".")))
        except ValueError:
            pass
    return out


def report_numbers(report: dict) -> set[float]:
    """Every number a narrative may quote: counts, minutes, accuracy (fraction and %), wcpm."""
    nums: set[float] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.update({float(v), float(round(v)), round(float(v), 1)})
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("narrative", "next_steps", "session_id"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(report)
    acc = report.get("accuracy")
    if isinstance(acc, (int, float)) and acc <= 1:
        nums.update({float(round(acc * 100)), round(acc * 100, 1)})
    return nums


def report_vocab(report: dict) -> set[str]:
    """Practice words/sounds the narrative may name (normalised tokens and whole phrases)."""
    vocab: set[str] = set()

    def add(s):
        if isinstance(s, str) and s.strip():
            vocab.add(norm(s))
            vocab.update(tokens(s))
            vocab.update(norm(g) for g in graphemes(s.replace(" ", "")))

    for w in report.get("difficult_words") or []:
        add(w)
    for d in report.get("difficult_sounds") or []:
        add(d.get("sound")), add(d.get("confused_with"))
    for m in report.get("mistakes") or []:
        add(m.get("item")), add(m.get("heard"))
        for e in m.get("errors") or []:
            for part in re.split(r"[→>\-:,\s]+", str(e)):
                add(part)
    for key in ("strengths", "weaknesses", "topics_attention"):
        for x in report.get(key) or []:
            for v in x.values():
                add(v)
    return vocab


def validate_narrative(data: dict, *, report: dict, steps_fallback: dict | None = None) -> dict:
    """Narrative texts are strict (any problem rejects the output); next steps are lenient: a step that
    fails a check is dropped, and fewer than 2 surviving steps fall back to `steps_fallback`."""
    nar = data.get("narrative") or {}
    steps = data.get("next_steps") or {}
    out = {"narrative": {}, "next_steps": {}}
    lang = report.get("lang", "hi")
    vocab = report_vocab(report)
    nums = report_numbers(report)
    for key in ("parent_hi", "parent_en", "teacher_en", "teacher_hi"):
        t = " ".join(str(nar.get(key, "")).split())
        if not t:
            raise ValueError(f"{key} is empty")
        if len(t) > 700:
            raise ValueError(f"{key} is too long")
        n_sent = len([s for s in re.split(r"[।.?!]+", t) if s.strip()])
        if key.startswith("parent") and not 2 <= n_sent <= 6:
            raise ValueError(f"{key} must be 3-5 short sentences")
        out["narrative"][key] = t
    raw_steps = {}
    for key in ("hi", "en"):
        v = steps.get(key) or []
        if isinstance(v, str):  # one string with several steps
            v = re.split(r"\n+|(?<=[।.!?])\s+(?=\d|[-•])|^\s*\d+[.)]\s*", v)
        raw_steps[key] = [" ".join(str(x).split())[:200] for x in v if str(x).strip()]

    def check(key: str, t: str) -> None:
        text_lang = "hi" if key.endswith("hi") else "en"
        if "{" in t or "}" in t:
            raise ValueError("placeholders are not allowed in the narrative")
        if unsafe_words(t) or BANNED_SHAME.search(t) or SHAME_EN.search(t) or INJECTION_MARKERS.search(t):
            raise ValueError(f"{key}: blocked words")
        letters = [c for c in t if c.isalpha() or _is_deva(c)]
        deva = sum(1 for c in letters if _is_deva(c))
        if letters and (deva / len(letters) < 0.5 if text_lang == "hi" else deva / len(letters) > 0.5):
            raise ValueError(f"{key} is not mainly in {'Hindi' if text_lang == 'hi' else 'English'}")
        # Practice words must come from the report: anything quoted, and any word in the
        # session language's script inside text written in the other language.
        named = [q for q in _QUOTED_RE.findall(t)]
        if text_lang != lang:
            named += [w for w in tokens(t) if script_ok(w, lang)]
        for w in named:
            if norm(w) and norm(w) not in vocab and not all(x in vocab for x in tokens(w)):
                raise ValueError(f"{key} mentions '{w}', which is not in the report")
        is_step = key in ("hi", "en")
        for x in _numbers(t):
            if x not in nums and not (is_step and x <= 10):
                raise ValueError(f"{key} uses the number {x:g}, which is not in the report")

    for key, t in out["narrative"].items():
        check(key, t)
    for key in ("hi", "en"):
        good = []
        for t in raw_steps[key]:
            try:
                check(key, t)
                good.append(t)
            except ValueError:
                continue
        if len(good) < 2:
            good = list((steps_fallback or {}).get(key) or good)
        out["next_steps"][key] = good[:3]
    return out
