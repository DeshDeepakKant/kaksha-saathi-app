"""The 30-minute voice learning session engine (docs/voice_session_contract.md, "Adaptivity rules").

Code owns the path: ladder stage, item queues, tries, streaks, timer, transcript, evidence and the
report assembly. Three other modules do the parts around it, called through the seams below:
`app/speech/assess.py` judges an answer, `app/ai/voice_tutor.py` makes items and Saathi's lines,
`app/services/voice_report.py` builds the deterministic report. Every seam has a small fallback,
so a session keeps running if one of them fails.

What a session practises is planned per child by `voice_plan.plan_session` from the teacher's evidence
(docs/voice_focus_contract.md): placement -> warm-up -> focus -> stretch, moving the focus up only on
mastery (at most once a session) and dropping a stage only for support. The outcome goes in the report.

All working memory lives in `VoiceSession.state` (JSON), so turns survive restarts. Turns are
idempotent by `client_turn_id`: the stored response is returned on a retry.

Language: a session runs in one content language (`state["lang"]`, default the parent's content
language, chosen by the API). It reaches every seam: items, judging (the item's `lang`), Saathi's
lines, speech-to-text (with the parent's preferred provider, `state["provider"]`) and the report.
Hindi and English behave exactly as before; other languages get their fixed lines translated once
at start (`voice_tutor.prepare_language`) and fall back to English lines, never to an empty turn.
"""
from __future__ import annotations

import copy
import dataclasses
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.ai import features
from app.models.tables import (
    Child, Classroom, CustomCheckpoint, CustomSubject, Evidence, VoiceSession, VoiceTurn,
)
from app.services import ledger, voice_plan
from app.services.content import get_content
from app.services.voice_types import (
    MAX_ATTEMPTS, KINDS, STAGE_CHECKPOINTS, STAGES, TARGET_MINUTES, Assessment, is_reviewed_lang, stage_checkpoints,
    voice_lang,
)

# The clock is injectable so tests can run a 30-minute session in milliseconds.
CLOCK: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731

TARGET_S = TARGET_MINUTES * 60
BREAK_AT_S = 15 * 60
IDLE_CAP_S = 180        # a longer gap between turns (app paused) adds at most this much session time
STALE_S = 60 * 60       # an active session untouched this long is finalised when someone opens it
BATCH = 6               # items generated per call
REFILL_BELOW = 2        # refill a stage's queue when fewer items than this are left
SILENT_CHECK_IN = 3     # silent turns in a row before Saathi checks in
OPEN_KINDS = ("make_sentence", "answer_question")
SECURE = "on_track"
MAX_WEAK = 8
# Session phases and their rules (docs/voice_focus_contract.md section 2)
PLACEMENT_ITEMS = 2     # items per placement probe; both must succeed to pass the stage
PLACEMENT_TRIES = 2     # tries per placement item
MAX_PROBES = 3
WARMUP_ITEMS = 2
STRETCH_ITEMS = 3
STRETCH_AT_S = 240      # stretch once this little time is left, when the focus was not mastered
MASTERY_MIN = 8         # judged focus items before mastery can count
MASTERY_WINDOW = 10
MASTERY_RATE = 0.8
SUPPORT_FAILS = 3       # failed items in a row at difficulty 1 drop one stage (support)
SUPPORT_BACK = 3        # successes there return to the focus

SAFETY_LINE = {"hi": "यह बात किसी बड़े — मम्मी, पापा या अध्यापक — को बताइए।",
               "en": "Please tell a grown-up — your mummy, papa or teacher — about this."}

_DEFAULT_RECORD_S = {"read_letter": 4, "say_sound": 4, "build_word": 5, "read_word": 5, "make_sentence": 10,
                     "read_sentence": 8, "read_paragraph": 30, "answer_question": 10}


_A_FIELDS = {f.name for f in dataclasses.fields(Assessment)}


class StaleItem(Exception):
    """The turn answers an item that is no longer the current one."""


# ------------------------------------------------------------------ seams (other agents' modules)
# Thin wrappers so the real modules are imported lazily and tests can monkeypatch these names.
def generate_items(db: Session, *, use_ai: bool = True, **kw) -> tuple[list[dict], str]:
    from app.ai import voice_tutor
    return voice_tutor.generate_items(db, use_ai=use_ai, **kw)


# ------------------------------------------------------------------ background item generation
# Claude takes ~8-11 s per batch, too long for a child to wait mid-turn. Turns refill from the reviewed
# bank instantly while Claude prepares the next batch on a thread; later refills use it. In memory:
# fine for the single uvicorn worker; a restart only means one more bank batch.
_PREFETCH: dict[tuple[int, str], list[dict]] = {}
_INFLIGHT: set[tuple[int, str]] = set()
_PF_LOCK = threading.Lock()


def _gen_kwargs(st: dict, stage: str, avoid: list[str]) -> dict:
    return dict(school_id=st["school_id"], lang=st["lang"], grade=st["grade"], stage=stage,
                topics=topics_for(st, stage), avoid=list(avoid), weak_sounds=list(st["weak_sounds"]), n=BATCH)


def _take_prefetched(st: dict, stage: str) -> list[dict]:
    with _PF_LOCK:
        return _PREFETCH.pop((st.get("sid"), stage), [])


def _prefetch(st: dict, stage: str, avoid: list[str]) -> None:
    """Ask Claude for this stage's next batch in the background (no-op without a key)."""
    from app.ai import voice_tutor
    sid = st.get("sid")
    if sid is None or not voice_tutor._ai_ready():
        return
    key = (sid, stage)
    with _PF_LOCK:
        if key in _INFLIGHT or _PREFETCH.get(key):
            return
        _INFLIGHT.add(key)
    kw = _gen_kwargs(st, stage, avoid)  # snapshot: the thread never touches the live state

    def run():
        from app.db import SessionLocal
        s = SessionLocal()
        try:
            items, source = generate_items(s, use_ai=True, **kw)
            s.commit()
            if source == "ai" and items:
                with _PF_LOCK:
                    _PREFETCH[key] = items
        except Exception:
            s.rollback()
        finally:
            s.close()
            with _PF_LOCK:
                _INFLIGHT.discard(key)

    threading.Thread(target=run, daemon=True, name=f"voice-prefetch-{sid}-{stage}").start()


def _drop_prefetch(sid: int) -> None:
    with _PF_LOCK:
        for key in [k for k in _PREFETCH if k[0] == sid]:
            _PREFETCH.pop(key, None)


def tutor_line(db: Session, **kw) -> tuple[str, str]:
    from app.ai import voice_tutor
    return voice_tutor.tutor_line(db, **kw)


def evaluate_open(db: Session, **kw):
    from app.ai import voice_tutor
    return voice_tutor.evaluate_open(db, **kw)


def write_narrative(db: Session, **kw) -> tuple[dict, str]:
    from app.ai import voice_tutor
    return voice_tutor.write_narrative(db, **kw)


def assess_item(item: dict, transcript: str, duration_s: float | None = None):
    from app.speech import assess
    return assess.assess_item(item, transcript, duration_s)


def build_report(**kw) -> dict:
    from app.services import voice_report
    return voice_report.build_report(**kw)


_ASR_CTX = threading.local()  # the turn's preferred speech provider (keeps the seam's 3-argument shape)


def transcribe(audio: bytes, filename: str, lang: str) -> str:
    """Speech-to-text in the session language with the parent's preferred provider; the speech layer
    falls back to the other provider. Older speech modules without `transcribe` use `get_asr()`."""
    from app import speech
    preferred = getattr(_ASR_CTX, "provider", None) or "sarvam"
    fn = getattr(speech, "transcribe", None)
    if fn is not None and _stt_configured(lang):
        return (fn(audio, filename, lang=lang, preferred=preferred).text or "")
    return speech.get_asr().transcribe(audio, filename, language=lang).text or ""  # no provider: mock


def _stt_configured(lang: str) -> bool:
    try:
        from app.speech import capabilities
        return bool(capabilities.providers_for("stt", lang))
    except Exception:
        return False


# ------------------------------------------------------------------ small helpers
def _now() -> datetime:
    t = CLOCK()
    return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _naive(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(tzinfo=None)


def iso(t: datetime | None) -> str | None:
    if t is None:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()


def _a2d(a) -> dict:
    """An Assessment (dataclass or dict) as a plain dict with every field present."""
    d = a.to_dict() if hasattr(a, "to_dict") else dict(a or {})
    base = Assessment(verdict="wrong", score=0.0, heard="").to_dict()
    base.update({k: v for k, v in d.items() if v is not None or k == "fluency"})
    return base


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    return " ".join("".join(ch if ch.isalnum() or ch.isspace() or unicodedata.category(ch).startswith("M")
                            else " " for ch in s).split())


def item_key(it: dict) -> str:
    d = it.get("display") or {}
    return (it.get("target") or d.get("text") or d.get("question") or " ".join(d.get("words") or [])
            or it.get("prompt") or it.get("id") or "")


def _state(vs: VoiceSession) -> dict:
    return copy.deepcopy(vs.state or {})


def _save(vs: VoiceSession, st: dict) -> None:
    vs.state = st
    vs.stage = st["stage"]
    vs.elapsed_s = st["elapsed_s"]
    flag_modified(vs, "state")


def _tick(st: dict, now: datetime) -> None:
    """Add the time since the last turn, capped so a paused app doesn't eat the session."""
    last = datetime.fromisoformat(st["last_at"])
    gap = max(0.0, (now - last).total_seconds())
    st["elapsed_s"] = round(st["elapsed_s"] + min(gap, IDLE_CAP_S), 1)
    st["last_at"] = now.isoformat()


def remaining_s(st: dict) -> float:
    return 0.0 if st.get("done") else round(max(0.0, TARGET_S - st["elapsed_s"]), 1)


# ------------------------------------------------------------------ syllabus and start stage
def _topic(cp_id: str, custom: bool) -> dict:
    cp = get_content().checkpoints.get(cp_id)
    return {"checkpoint_id": cp_id, "title_hi": cp.title_hi if cp else cp_id,
            "title_en": cp.title_en if cp else cp_id, "custom": custom}


def _english_cps(db: Session, cls: Classroom) -> list[str]:
    """What an English session practises: the class's built-in English roadmap (`E.*`; the grade's template
    when the class has none), plus the topics of a school's own legacy custom subject named "english"."""
    content = get_content()
    ids = ledger.class_roadmap_cps(db, cls, "english")
    subj = db.scalar(select(CustomSubject).where(
        CustomSubject.school_id == cls.school_id,
        (func.lower(CustomSubject.key) == "english") | (func.lower(CustomSubject.name_en) == "english"))
        .order_by(CustomSubject.id).limit(1))
    if subj:
        own = ledger.roadmap_checkpoint_ids(ledger.current_roadmap(db, cls.id, subj.key))
        if not own:
            rows = list(db.scalars(select(CustomCheckpoint).where(CustomCheckpoint.school_id == cls.school_id,
                                                                  CustomCheckpoint.subject == subj.key)))
            own = [r.id for r in rows if r.grade == cls.grade] or [r.id for r in rows]
        template = [i["checkpoint_id"] for i in content.template_roadmap("english", cls.grade)]
        # a legacy roadmap that holds only the school's own topics still practises the built-in ones
        ids = (ids if any(i in template for i in ids) else template + ids) + own
    return [i for i in dict.fromkeys(ids) if i in content.checkpoints]


def _syllabus(db: Session, cls: Classroom, lang: str) -> dict:
    content = get_content()
    ids = ledger.roadmap_checkpoint_ids(ledger.current_roadmap(db, cls.id, "literacy")) or [
        i["checkpoint_id"] for i in content.template_roadmap("literacy", cls.grade)]
    builtin = [i for i in ids if i in content.checkpoints and i not in content.custom_ids]
    custom = [i for i in ids if i in content.custom_ids]
    english = _english_cps(db, cls) if lang == "en" else []
    return {"builtin": builtin, "custom": custom, "english": english}


def _plan_cps(st: dict, stage: str) -> tuple[list[str], list[str]]:
    """(built-in, custom) checkpoints the plan picked, when `stage` is the planned focus stage."""
    plan = st.get("plan") or {}
    if not plan or stage != st.get("focus_stage") or stage != plan.get("focus_stage"):
        return [], []
    content = get_content()
    cps = [c for c in plan.get("focus_checkpoints") or [] if c in content.checkpoints]
    return [c for c in cps if c not in content.custom_ids], [c for c in cps if c in content.custom_ids]


def topics_for(st: dict, stage: str) -> list[dict]:
    """The class syllabus filtered to `stage` (built-ins), plus every custom topic (the AI decides).
    English sessions use the English syllabus (`E.*` built-ins for the stage, then the school's own topics).
    In the focus stage the built-ins are the plan's focus checkpoints (the child's weak ones)."""
    content = get_content()
    syl = st["syllabus"]
    focus, focus_custom = _plan_cps(st, stage)
    if st.get("lang") == "en":
        stage_cps = stage_checkpoints("en", stage)
        eng = syl["english"]
        builtin = (focus or [c for c in eng if c in stage_cps and c not in content.custom_ids]
                   or [c for c in stage_cps if c in content.checkpoints])
        custom = list(dict.fromkeys(focus_custom + [c for c in eng if c in content.custom_ids]))
        return [_topic(c, False) for c in builtin] + [_topic(c, True) for c in custom]
    stage_cps = STAGE_CHECKPOINTS[stage]
    builtin = (focus or [c for c in syl["builtin"] if c in stage_cps]
               or [c for c in stage_cps if c in content.checkpoints])
    custom = list(dict.fromkeys(focus_custom + syl["custom"] + syl["english"]))
    return [_topic(c, False) for c in builtin] + [_topic(c, True) for c in custom]


def start_stage(db: Session, child: Child, lang: str, english_cps: list[str]) -> int:
    """Before per-child plans (kept for reference; sessions now start from `voice_plan.plan_session`).
    One stage below the lowest stage that is not secure (at least half its checkpoints assessed,
    and every assessed one on track); English
    starts at `letter` unless the child's English checkpoints are all on track."""
    statuses = {cp: r.status for cp, r in ledger.child_statuses(db, [child.id])[child.id].items()}
    if lang == "en":
        seen = [statuses[c] for c in english_cps if statuses.get(c, "not_started") != "not_started"]
        return 1 if seen and all(s == SECURE for s in seen) else 0
    for i, stage in enumerate(STAGES):
        cps = STAGE_CHECKPOINTS[stage]
        seen = [statuses[c] for c in cps if statuses.get(c, "not_started") != "not_started"]
        if 2 * len(seen) < len(cps) or any(s != SECURE for s in seen):
            return max(0, i - 1)
    return max(0, len(STAGES) - 2)


# ------------------------------------------------------------------ items
_EMERGENCY = {
    "hi": {"letter": ["क", "म", "ल", "र", "स", "न"], "word_build": ["कमल", "घर", "नल", "जल", "मटर", "बस"],
           "word_read": ["आम", "नाक", "दिन", "मीठा", "पानी", "किताब"],
           "sentence_build": [["राम", "आम"], ["बिल्ली", "दूध"], ["बस", "घर"]],
           "reading": ["राम आम खाता है।", "माँ घर पर है।", "बस जल्दी आई।"]},
    "en": {"letter": ["a", "m", "s", "t", "p", "b"], "word_build": ["cat", "sun", "pen", "dog", "hat", "bus"],
           "word_read": ["fish", "tree", "ball", "milk", "book", "cake"],
           "sentence_build": [["cat", "milk"], ["sun", "hot"], ["dog", "run"]],
           "reading": ["I can run.", "The cat is big.", "We like to play."]},
}
_EMERGENCY_PROMPT = {
    "hi": {"read_letter": "{name}, यह अक्षर पढ़ो।", "build_word": "{name}, इन अक्षरों को जोड़कर शब्द बोलो।",
           "read_word": "{name}, यह शब्द पढ़ो।", "make_sentence": "{name}, इन शब्दों से एक वाक्य बोलो।",
           "read_sentence": "{name}, यह वाक्य पढ़ो।"},
    "en": {"read_letter": "{name}, read this letter.", "build_word": "{name}, join these sounds and say the word.",
           "read_word": "{name}, read this word.", "make_sentence": "{name}, say a sentence with these words.",
           "read_sentence": "{name}, read this sentence."},
}


# Other languages: the same six letters (ka ma la ra sa na) in each script. Letters are the one thing
# that is certainly right without a reviewed bank, so every stage falls back to reading them.
_EMERGENCY_LETTERS = {
    "mr": "कमलरसन", "bn": "কমলরসন", "gu": "કમલરસન", "pa": "ਕਮਲਰਸਨ", "or": "କମଲରସନ",
    "ta": "கமலரபந", "te": "కమలరసన", "kn": "ಕಮಲರಸನ", "ml": "കമലരസന",
}


def _fixed(table: dict, lang: str, key: str) -> str:
    """A fixed line in the session language: hand-written for hi/en, else translated English."""
    if lang in table:
        return table[lang].get(key, "") if isinstance(table[lang], dict) else table[lang]
    from app.ai import voice_tutor
    en = table["en"].get(key, "") if isinstance(table["en"], dict) else table["en"]
    return voice_tutor.local(lang, en) if en else ""


def _emergency_items(lang: str, stage: str) -> list[dict]:
    """Last resort when item generation fails outright. No checkpoint, so no evidence is written."""
    if lang not in _EMERGENCY:
        letters = _EMERGENCY_LETTERS.get(lang) or _EMERGENCY_LETTERS["mr"]
        return [{"id": f"x-{stage}-{n}", "stage": stage, "kind": "read_letter", "lang": lang, "checkpoint_id": None,
                 "prompt": _fixed(_EMERGENCY_PROMPT, lang, "read_letter"), "display": {"text": x}, "target": x,
                 "accept": [], "required_words": [], "keywords": [], "difficulty": 1 + n % 3, "source": "bank"}
                for n, x in enumerate(letters)]
    out = []
    for n, x in enumerate(_EMERGENCY[lang][stage]):
        kind = {"letter": "read_letter", "word_build": "build_word", "word_read": "read_word",
                "sentence_build": "make_sentence", "reading": "read_sentence"}[stage]
        it = {"id": f"x-{stage}-{n}", "stage": stage, "kind": kind, "lang": lang, "checkpoint_id": None,
              "prompt": _EMERGENCY_PROMPT[lang][kind], "display": {}, "target": None, "accept": [],
              "required_words": [], "keywords": [], "difficulty": 1 + n % 3, "source": "bank"}
        if kind == "make_sentence":
            it["display"] = {"words": x}
            it["required_words"] = list(x)
        elif kind == "build_word":
            it["display"] = {"tiles": _graphemes(x)}
            it["target"] = x
        else:
            it["display"] = {"text": x}
            it["target"] = x
        out.append(it)
    return out


def _graphemes(word: str) -> list[str]:
    out: list[str] = []
    for ch in word:
        if out and (unicodedata.category(ch).startswith("M") or out[-1].endswith("्")):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _clean_item(raw: dict, stage: str, lang: str) -> dict | None:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    it = dict(raw)
    it["stage"] = it.get("stage") if it.get("stage") in STAGES else stage
    it["lang"] = lang
    it["display"] = dict(it.get("display") or {})
    for k in ("accept", "required_words", "keywords"):
        it[k] = list(it.get(k) or [])
    try:
        it["difficulty"] = min(3, max(1, int(it.get("difficulty") or 1)))
    except (TypeError, ValueError):
        it["difficulty"] = 1
    it.setdefault("checkpoint_id", None)
    it.setdefault("target", None)
    it.setdefault("prompt", "")
    it.setdefault("source", "bank")
    it["max_record_s"] = it.get("max_record_s") or _DEFAULT_RECORD_S[it["kind"]]
    it["id"] = str(it.get("id") or f"{stage}-{item_key(it)}")[:60]
    return it


def _register(st: dict, it: dict) -> str:
    """Store an item under a session-unique id; read_paragraph followups become their own items."""
    base, n, iid = it["id"], 1, it["id"]
    while iid in st["items"]:
        n += 1
        iid = f"{base}~{n}"
    it["id"] = iid
    fids = []
    for f in it.pop("followups", None) or []:
        fc = _clean_item(f, it["stage"], it["lang"])
        if fc:
            fc.setdefault("checkpoint_id", it.get("checkpoint_id"))
            fids.append(_register(st, fc))
    if fids:
        it["followup_ids"] = fids
    st["items"][iid] = it
    return iid


def _refill(db: Session, st: dict, stage: str) -> None:
    queue = st["queues"].setdefault(stage, [])
    queued = {_norm(item_key(st["items"][i])) for i in queue}
    avoid = list(dict.fromkeys(st["seen"][-40:] + [item_key(st["items"][i]) for i in queue]))
    raw, source = _take_prefetched(st, stage), "ai"
    if not raw:
        try:  # reviewed bank: instant, so the child never waits on Claude mid-turn
            raw, source = generate_items(db, use_ai=False, **_gen_kwargs(st, stage, avoid))
        except Exception:
            raw, source = [], "failed"
    if not raw and not queue and not is_reviewed_lang(st["lang"]):
        # Nothing left to serve and no reviewed bank (or per-language file) for this language: wait
        # for Claude this once rather than serve only letters; later refills use the background batch.
        try:
            raw, source = generate_items(db, use_ai=True, **_gen_kwargs(st, stage, avoid))
        except Exception:
            raw, source = [], "failed"
    cleaned = [c for c in (_clean_item(r, stage, st["lang"]) for r in raw or []) if c and c["stage"] == stage]
    seen = {_norm(s) for s in st["seen"]} | queued
    fresh = [c for c in cleaned if _norm(item_key(c)) not in seen]
    if not fresh and not queue:
        fresh = cleaned or _emergency_items(st["lang"], stage)  # repeats beat an empty session
        source = source if cleaned else "emergency"
    st["sources"][source] = st["sources"].get(source, 0) + len(fresh)
    for c in fresh:
        queue.append(_register(st, c))
    # Claude prepares the next batch for this stage, and the stage above, while the child works
    _prefetch(st, stage, avoid + [item_key(c) for c in fresh])
    up = STAGES.index(stage) + 1
    if up < len(STAGES) and not st["queues"].get(STAGES[up]):
        _prefetch(st, STAGES[up], st["seen"][-40:])


def _next_item(db: Session, st: dict) -> str | None:
    """Comprehension followups first, else the queued item closest to the wanted difficulty
    (easier on a tie). Refills the stage's queue before it runs dry."""
    stage = st["stage"]
    if st["pending"]:  # cleared on every stage change
        return st["pending"].pop(0)
    queue = st["queues"].setdefault(stage, [])
    want = st["difficulty"]
    if not any(st["items"][i]["difficulty"] <= want for i in queue):
        _refill(db, st, stage)  # nothing easy enough left (or nothing at all)
    if not queue:
        return None
    best = min(range(len(queue)), key=lambda i: (abs(st["items"][queue[i]]["difficulty"] - want),
                                                 st["items"][queue[i]]["difficulty"] > want, i))
    iid = queue.pop(best)
    if len(queue) < REFILL_BELOW:
        _refill(db, st, stage)
    return iid


def _serve(st: dict, iid: str | None) -> None:
    st["current"] = iid
    st["attempt"] = 1
    if iid:
        it = st["items"][iid]
        st["seen"].append(item_key(it))
        st["order"].append(iid)
        st["outcomes"][iid] = {"attempts": [], "result": None, "stage": it["stage"]}


# ------------------------------------------------------------------ language (Saathi's lines)
_FALLBACK = {
    "hi": {"greet": "नमस्ते {name}! चलो साथ में पढ़ते हैं।", "praise": "शाबाश!", "retry_hint": "कोई बात नहीं, एक बार और बोलो।",
           "move_on": "कोई बात नहीं, इसे हम फिर करेंगे। चलो अगला।", "stage_up": "वाह! अब थोड़ा कठिन करते हैं।",
           "stage_down": "चलो, थोड़ा आसान करते हैं।", "break": "थोड़ा आराम कर लो, फिर आगे चलते हैं।",
           "silent": "{name}, क्या तुम वहाँ हो? थोड़ा ज़ोर से बोलो।", "wrap_up": "आज तुमने बहुत अच्छा अभ्यास किया। शाबाश!"},
    "en": {"greet": "Hello {name}! Let's read together.", "praise": "Well done!", "retry_hint": "That's okay, try once more.",
           "move_on": "That's okay, we'll practise this again. Let's do the next one.",
           "stage_up": "Wow! Let's try something harder.", "stage_down": "Let's make it a little easier.",
           "break": "Take a little rest, then we'll go on.", "silent": "{name}, are you there? Speak a little louder.",
           "wrap_up": "You practised really well today. Well done!"},
}


def _line(db: Session, st: dict, situation: str, item: dict | None = None, assessment: dict | None = None,
          attempt: int = 1) -> str:
    try:
        a = Assessment(**{k: v for k, v in assessment.items() if k in _A_FIELDS}) if assessment else None
        text, _ = tutor_line(db, school_id=st["school_id"], lang=st["lang"], situation=situation, item=item,
                             assessment=a, attempt=attempt)
        if text and text.strip():
            return text.strip()
    except Exception:
        pass
    if situation == "intro_item":
        return (item or {}).get("prompt") or ""
    return _fixed(_FALLBACK, st["lang"], situation)


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------ judging
def _hear(audio: bytes, filename: str, transcript: str | None, lang: str,
          provider: str | None = None) -> tuple[str, str]:
    if transcript is not None and transcript.strip():
        return transcript.strip(), "provided"
    if audio:
        _ASR_CTX.provider = provider
        try:
            text = transcribe(audio, filename or "turn.wav", lang).strip()
        except Exception:  # ASR outage: treated as unheard rather than failing the turn
            return "", "failed"
        finally:
            _ASR_CTX.provider = None
        return (text, "asr") if text else ("", "silent")
    return "", "silent"


def _needs_safety(item: dict, heard: str) -> bool:
    if item["kind"] in OPEN_KINDS:
        return True
    target = item_key(item)
    return len(heard) > 2 * len(target) + 20


def _fallback_assess(item: dict, heard: str) -> dict:
    """Used only if the assessment module fails: plain normalised match."""
    h = _norm(heard)
    if item["kind"] == "make_sentence":
        words = h.split()
        ok = len(words) >= 3 and all(_norm(w) in h for w in item.get("required_words") or [])
    elif item["kind"] == "answer_question":
        ok = any(_norm(k) and _norm(k) in h for k in (item.get("keywords") or []) + (item.get("accept") or []))
    else:
        targets = [t for t in [item.get("target")] + list(item.get("accept") or []) if t]
        ok = any(_norm(t) == h or (len(_norm(t)) > 3 and _norm(t) in h) for t in targets)
    return Assessment(verdict="correct" if ok else "wrong", score=1.0 if ok else 0.0, heard=heard).to_dict()


def _assess(db: Session, st: dict, item: dict, heard: str, duration_s: float | None) -> dict:
    try:
        code = assess_item(item, heard, duration_s)
    except Exception:
        return _fallback_assess(item, heard)
    if item["kind"] in OPEN_KINDS:
        try:
            refined = evaluate_open(db, school_id=st["school_id"], lang=st["lang"], item=item,
                                    transcript=heard, code=code)
            code = refined or code
        except Exception:
            pass
    return _a2d(code)


def _note_weak(st: dict, errors: list[dict]) -> None:
    for e in errors or []:
        if e.get("type") in ("substitution", "matra", "omission") and e.get("target"):
            s = str(e["target"])[:8]
            if s in st["weak_sounds"]:
                st["weak_sounds"].remove(s)
            st["weak_sounds"].append(s)
            st["sound_counts"][s] = st["sound_counts"].get(s, 0) + 1
    st["weak_sounds"] = st["weak_sounds"][-MAX_WEAK:]


# ------------------------------------------------------------------ evidence
def _evidence_ok(st: dict, cp: str | None) -> bool:
    """English answers only count for the class's English topics (`E.*`, or the school's own), never for
    the Hindi map, and a home-language session never writes to an English topic."""
    content = get_content()
    if not cp or cp not in content.checkpoints:
        return False
    english = set(st["syllabus"]["english"])
    if st["lang"] == "en":
        return cp in english
    return cp not in english and content.checkpoints[cp].subject != "english"


def _write_evidence(db: Session, vs: VoiceSession, st: dict, item: dict, result: str, score: float) -> str | None:
    ev = {"first_try": "correct", "after_retry": "correct" if st["attempt"] <= 2 else "partial",
          "failed": "incorrect"}.get(result)
    cp = item.get("checkpoint_id")
    if not ev or not _evidence_ok(st, cp):
        return None
    child = db.get(Child, vs.child_id)
    db.add(Evidence(school_id=vs.school_id, class_id=child.class_id, child_id=child.id, checkpoint_id=cp,
                    result=ev, score=round(float(score or 0), 3), source="home_voice", confidence=0.8,
                    session_id=None, status="confirmed", quote=None, at=_naive(_now())))
    st["evidence"] += 1
    return ev


# ------------------------------------------------------------------ transcript rows
def _row(db: Session, vs: VoiceSession, role: str, text: str, *, item_id: str | None = None,
         verdict: str | None = None, words: list | None = None, client_turn_id: str | None = None,
         at: datetime | None = None) -> VoiceTurn:
    r = VoiceTurn(session_id=vs.id, role=role, text=text or "", item_id=item_id, verdict=verdict, words=words,
                  client_turn_id=client_turn_id, at=_naive(at or _now()))
    db.add(r)
    return r


def line_view(r: VoiceTurn) -> dict:
    d = {"role": r.role, "text": r.text, "at": iso(r.at)}
    if r.item_id:
        d["item_id"] = r.item_id
    if r.verdict:
        d["verdict"] = r.verdict
    if r.words:
        d["words"] = r.words
    return d


def transcript(db: Session, vs: VoiceSession) -> list[dict]:
    rows = db.scalars(select(VoiceTurn).where(VoiceTurn.session_id == vs.id).order_by(VoiceTurn.id))
    return [line_view(r) for r in rows if r.text]


def _replay(db: Session, vs: VoiceSession, client_turn_id: str | None) -> dict | None:
    if not client_turn_id:
        return None
    r = db.scalar(select(VoiceTurn).where(VoiceTurn.session_id == vs.id,
                                          VoiceTurn.client_turn_id == client_turn_id))
    return copy.deepcopy(r.response) if r and r.response is not None else None


# ------------------------------------------------------------------ public engine API
def _tutor(text: str, lang: str) -> dict:
    """The `tutor` payload; lines of a language without hand-written text are labelled."""
    out = {"text": text, "lang": lang}
    if not is_reviewed_lang(lang):
        out["machine_translated"] = True
    return out


def _extra_lines() -> list[str]:
    """The engine's own English fallback lines, translated with Saathi's templates at start."""
    from app.services import voice_bank
    return (list(_FALLBACK["en"].values()) + [SAFETY_LINE["en"]] + list(_EMERGENCY_PROMPT["en"].values())
            + list(voice_bank._LADDER_PROMPT_EN.values()))


def start(db: Session, *, child: Child, lang: str, provider: str | None = None) -> VoiceSession:
    cls = db.get(Classroom, child.class_id)
    lang = voice_lang(lang)
    if not is_reviewed_lang(lang):
        from app.ai import voice_tutor
        try:  # once per language (cached); bounded wait, English lines meanwhile
            voice_tutor.prepare_language(db, lang, school_id=cls.school_id, extra=_extra_lines())
        except Exception:
            pass
    now = _now()
    syl = _syllabus(db, cls, lang)
    plan = voice_plan.plan_session(db, child, lang, syl, now=now)
    st = {"v": 1, "lang": lang, "grade": cls.grade, "school_id": cls.school_id, "syllabus": syl,
          "stage": plan["focus_stage"], "highest_stage": plan["focus_stage"], "start_stage": plan["focus_stage"],
          "queues": {}, "items": {}, "outcomes": {}, "order": [], "pending": [],
          "current": None, "attempt": 1, "success_streak": 0, "fail_streak": 0, "silent_streak": 0,
          "difficulty": 1, "weak_sounds": list(reversed(plan["target_sounds"]))[-MAX_WEAK:], "sound_counts": {},
          "seen": [], "sources": {}, "break_given": False, "done": False, "wrap_up": None, "elapsed_s": 0.0,
          "last_at": now.isoformat(), "safety_flags": [], "evidence": 0, "provider": provider,
          # the plan and where the session is in it (docs/voice_focus_contract.md section 2)
          "plan": plan, "phase": "focus", "focus_stage": plan["focus_stage"], "focus_log": [], "moves_up": 0}
    _phase_defaults(st)
    st["focus_difficulty"] = plan["start_difficulty"]
    if plan["placement"]:
        st["phase"] = "placement"
        st["probes"] = [{"stage": plan["focus_stage"], "results": []}]
        _set_stage(st, plan["focus_stage"], 1)
    else:
        _enter_warmup(st)
    st["start_stage"] = st["highest_stage"] = st["stage"]
    vs = VoiceSession(school_id=cls.school_id, child_id=child.id, lang=lang, status="active",
                      stage=st["stage"], started_at=_naive(now), state={})
    db.add(vs)
    db.flush()
    st["sid"] = vs.id
    _serve(st, _next_item(db, st))
    item = st["items"].get(st["current"]) if st["current"] else None
    text = _join(_line(db, st, "greet"), _line(db, st, "intro_item", item) if item else "")
    _row(db, vs, "tutor", text, item_id=st["current"], at=now)
    _save(vs, st)
    db.flush()
    return vs


def session_view(db: Session, vs: VoiceSession) -> dict:
    st = vs.state or {}
    lines = transcript(db, vs)
    last_tutor = next((l["text"] for l in reversed(lines) if l["role"] == "tutor"), "")
    cur = st.get("current")
    return {"id": vs.id, "lang": vs.lang, "status": vs.status, "started_at": iso(vs.started_at),
            "elapsed_s": st.get("elapsed_s", vs.elapsed_s), "remaining_s": remaining_s(st) if st else 0.0,
            "target_minutes": TARGET_MINUTES, "stage": st.get("stage", vs.stage),
            "item": copy.deepcopy(st["items"][cur]) if cur and vs.status == "active" and not st.get("done") else None,
            "attempt": st.get("attempt", 1), "attempts_left": _max_tries(st) - st.get("attempt", 1) + 1,
            "done": bool(st.get("done")) or vs.status == "ended", "transcript": lines,
            "tutor": _tutor(last_tutor, vs.lang), "safety_flag": vs.safety_flag,
            "phase": st.get("phase"), "focus_stage": st.get("focus_stage"),
            "plan": copy.deepcopy(st.get("plan"))}


def _turn_base(st: dict, **kw) -> dict:
    cur = st["current"]
    out = {"verdict": "silent", "score": 0.0, "heard": "", "words": [], "errors": [],
           "attempt": st["attempt"], "attempts_left": _max_tries(st) - st["attempt"] + 1,
           "next_item": copy.deepcopy(st["items"][cur]) if cur and not st["done"] else None,
           "stage": st["stage"], "stage_changed": False, "elapsed_s": st["elapsed_s"],
           "remaining_s": remaining_s(st), "done": st["done"], "asr": "silent",
           "phase": st.get("phase"), "focus_stage": st.get("focus_stage")}
    out.update(kw)
    return out


def _finish_turn(db: Session, vs: VoiceSession, st: dict, *, client_turn_id: str | None, child_text: str,
                 child_verdict: str, child_item: str | None, words: list | None, tutor_text: str,
                 base: dict) -> dict:
    now = _now()
    child = _row(db, vs, "child", child_text, item_id=child_item, verdict=child_verdict, words=words or None,
                 client_turn_id=client_turn_id, at=now)
    tutor = _row(db, vs, "tutor", tutor_text, item_id=st["current"] if not st["done"] else None, at=now)
    resp = _turn_base(st, **base)
    resp["tutor"] = _tutor(tutor_text, st["lang"])
    resp["transcript_append"] = [line_view(r) for r in (child, tutor) if r.text]
    child.response = resp
    if st["done"] and st["wrap_up"] is None:
        st["wrap_up"] = {**resp, "transcript_append": []}
    _save(vs, st)
    db.flush()
    return copy.deepcopy(resp)


def _wrap_reply(db: Session, vs: VoiceSession, st: dict) -> dict:
    """What every turn gets once time is up (or the session has ended)."""
    if st.get("wrap_up") is None:
        st["done"] = True
        st["current"] = None
        text = _line(db, st, "wrap_up")
        _row(db, vs, "tutor", text)
        st["wrap_up"] = {**_turn_base(st), "tutor": _tutor(text, st["lang"]), "transcript_append": []}
        _save(vs, st)
        db.flush()
    return copy.deepcopy(st["wrap_up"])


def _time_up(st: dict) -> bool:
    return st["elapsed_s"] >= TARGET_S


# ------------------------------------------------------------------ the plan's phases
# placement -> warmup -> focus -> stretch -> focus ... Code moves between them; the stage of the current
# item (`stage`) follows the phase. The focus stage changes at most once a session (mastery, one up).
def _phase_defaults(st: dict) -> dict:
    """Fill the phase fields (also for a session started before plans existed: all focus, no plan)."""
    st.setdefault("plan", None)
    st.setdefault("phase", "focus")
    st.setdefault("focus_stage", st.get("stage"))
    st.setdefault("focus_log", [])
    st.setdefault("moves_up", 0)
    st.setdefault("focus_hist", {})       # stage -> [bool] of every judged focus item there
    st.setdefault("mastered", [])         # focus stages mastered this session
    st.setdefault("moved_up_to", None)
    st.setdefault("focus_difficulty", 1)
    st.setdefault("support", False)
    st.setdefault("support_ok", 0)
    st.setdefault("easy_fails", 0)
    st.setdefault("phase_n", 0)
    st.setdefault("probes", [])
    st.setdefault("stretch", {"stage": None, "items": 0, "correct": 0, "done": False})
    return st


def _max_tries(st: dict) -> int:
    return PLACEMENT_TRIES if st.get("phase") == "placement" else MAX_ATTEMPTS


def _set_stage(st: dict, stage: str, difficulty: int) -> None:
    if stage != st["stage"]:
        st["pending"] = []
    st["stage"] = stage
    st["difficulty"] = difficulty
    st["success_streak"] = st["fail_streak"] = 0
    if STAGES.index(stage) > STAGES.index(st.get("highest_stage") or stage):
        st["highest_stage"] = stage


def _enter_focus(st: dict) -> None:
    st["phase"], st["phase_n"], st["support"] = "focus", 0, False
    _set_stage(st, st["focus_stage"], st["focus_difficulty"])


def _enter_warmup(st: dict) -> None:
    warm = voice_plan.below(st["focus_stage"])
    if warm is None:
        _enter_focus(st)
        return
    st["phase"], st["phase_n"] = "warmup", 0
    _set_stage(st, warm, 1)


def _enter_stretch(st: dict) -> None:
    up = voice_plan.above(st["focus_stage"])
    st["focus_difficulty"] = st["difficulty"]
    st["phase"], st["phase_n"] = "stretch", 0
    st["stretch"]["stage"] = up
    _set_stage(st, up, 1)


def _adapt_difficulty(st: dict, result: str, tried: int) -> None:
    """Inside a stage, as before: 2 successes in a row -> harder, a miss -> easier."""
    if result == "first_try" or (result == "after_retry" and tried <= 2):
        st["success_streak"] += 1
        st["fail_streak"] = 0
        if st["success_streak"] >= 2:
            st["difficulty"] = min(3, st["difficulty"] + 1)
            st["success_streak"] = 0
    elif result == "after_retry":
        st["success_streak"] = st["fail_streak"] = 0
    else:
        st["success_streak"] = 0
        st["fail_streak"] += 1
        st["difficulty"] = max(1, st["difficulty"] - 1)


def _mastered(log: list[bool]) -> bool:
    last = log[-MASTERY_WINDOW:]
    return len(log) >= MASTERY_MIN and sum(last) >= MASTERY_RATE * len(last)


def _end_placement(db: Session, vs: VoiceSession, st: dict) -> None:
    failed = [STAGES.index(p["stage"]) for p in st["probes"] if not p.get("passed")]
    focus = STAGES[min(failed)] if failed else STAGES[-1]
    plan = st["plan"]
    child = db.get(Child, vs.child_id)
    try:
        statuses = {cp: r.status for cp, r in ledger.child_statuses(db, [child.id]).get(child.id, {}).items()}
    except Exception:
        statuses = {}
    plan.update(focus_stage=focus, warmup_stage=voice_plan.below(focus), stretch_stage=voice_plan.above(focus),
                source="placement", start_difficulty=1,
                focus_checkpoints=voice_plan.focus_checkpoints(st["lang"], st["syllabus"], focus, statuses),
                probes=[{"stage": p["stage"], "passed": bool(p.get("passed"))} for p in st["probes"]])
    plan["reason_en"], plan["reason_hi"] = voice_plan.placement_reason(focus)
    st["focus_stage"] = focus
    st["focus_difficulty"] = 1
    _enter_warmup(st)


def _placement_step(db: Session, vs: VoiceSession, st: dict, ok: bool) -> None:
    """Probe 2 items a stage from word_read: both right -> the stage above, else below; stop when the
    direction reverses, the ladder ends or after 3 probes."""
    probe = st["probes"][-1]
    probe["results"].append(ok)
    if len(probe["results"]) < PLACEMENT_ITEMS:
        return
    probe["passed"] = all(probe["results"])
    step = 1 if probe["passed"] else -1
    first = st["probes"][0]
    direction = 1 if first.get("passed") else -1
    nxt = STAGES.index(probe["stage"]) + step
    if step != direction or not 0 <= nxt < len(STAGES) or len(st["probes"]) >= MAX_PROBES:
        _end_placement(db, vs, st)
        return
    st["probes"].append({"stage": STAGES[nxt], "results": []})
    _set_stage(st, STAGES[nxt], 1)


def _after_item(db: Session, vs: VoiceSession, st: dict, result: str, tried: int) -> None:
    """Move through the plan after an item ends (`result`: first_try|after_retry|failed|skipped)."""
    ok = result == "first_try" or (result == "after_retry" and tried <= 2)
    judged = result in ("first_try", "after_retry", "failed")
    phase = st["phase"]
    if phase == "placement":
        _placement_step(db, vs, st, ok)  # a skipped probe item counts as not managed
        return
    if phase in ("warmup", "stretch"):
        st["phase_n"] += 1
        if phase == "stretch":
            st["stretch"]["items"] += 1
            st["stretch"]["correct"] += int(ok)
        if st["phase_n"] >= (WARMUP_ITEMS if phase == "warmup" else STRETCH_ITEMS):
            if phase == "stretch":
                st["stretch"]["done"] = True
            _enter_focus(st)
        return
    if judged:
        easy = st["difficulty"] == 1
        _adapt_difficulty(st, result, tried)
        if st["support"]:
            st["support_ok"] += int(ok)
            if st["support_ok"] >= SUPPORT_BACK:
                st["support"] = False
                _set_stage(st, st["focus_stage"], 1)
            return
        focus = st["focus_stage"]
        st["focus_log"].append(ok)
        st["focus_hist"].setdefault(focus, []).append(ok)
        if ok:
            st["easy_fails"] = 0
        elif result == "failed" and easy:
            st["easy_fails"] += 1
        if st["easy_fails"] >= SUPPORT_FAILS:
            st["easy_fails"] = 0
            down = voice_plan.below(focus)
            if down:  # support: one stage easier for a while; not a level change
                st["support"], st["support_ok"] = True, 0
                _set_stage(st, down, 1)
                return
        if focus not in st["mastered"] and _mastered(st["focus_log"]):
            st["mastered"].append(focus)
            up = voice_plan.above(focus)
            if st["moves_up"] == 0 and up:  # at most one move up a session
                st["moves_up"] = 1
                st["moved_up_to"] = up
                st["focus_stage"] = up
                st["focus_log"] = []
                _set_stage(st, up, 1)
                return
    if (not st["support"] and st["moves_up"] == 0 and st["stretch"]["items"] == 0
            and st["focus_stage"] not in st["mastered"] and voice_plan.above(st["focus_stage"])
            and remaining_s(st) <= STRETCH_AT_S):
        _enter_stretch(st)


def _close_current(st: dict, result: str) -> None:
    """Mark the current item as ended without a judgement (unfinished or skipped)."""
    cur = st["current"]
    if not cur:
        return
    out = st["outcomes"].get(cur)
    if out is None:
        return
    if result == "unfinished" and not out["attempts"]:
        del st["outcomes"][cur]  # served but never answered: not attempted
        st["order"] = [i for i in st["order"] if i != cur]
    else:
        out["result"] = result


def turn(db: Session, vs: VoiceSession, *, item_id: str, client_turn_id: str, transcript_text: str | None = None,
         duration_s: float | None = None, audio: bytes = b"", filename: str = "turn.wav") -> dict:
    prior = _replay(db, vs, client_turn_id)
    if prior is not None:
        return prior
    st = _phase_defaults(_state(vs))
    if vs.status == "ended" or st["done"]:
        return _wrap_reply(db, vs, st)
    if item_id != st["current"]:
        raise StaleItem(st["current"])
    _tick(st, _now())
    item = st["items"][st["current"]]
    lang = st["lang"]
    heard, asr = _hear(audio, filename, transcript_text, lang, st.get("provider"))
    time_up = _time_up(st)
    breather = ""
    if not time_up and not st["break_given"] and st["elapsed_s"] >= BREAK_AT_S:
        st["break_given"] = True
        breather = _line(db, st, "break")

    # -- child-safety check on open answers and runaway transcripts: redirect, don't advance
    if heard and _needs_safety(item, heard):
        category = features.classify_child_input(db, school_id=vs.school_id, text=heard)
        if category in ("distress", "personal"):
            st["silent_streak"] = 0
            st["safety_flags"].append({"category": category, "item_id": item["id"], "at": _now().isoformat()})
            vs.safety_flag = category
            if time_up:
                st["done"], st["current"] = True, None
            text = _join(_fixed(SAFETY_LINE, lang, ""), _line(db, st, "wrap_up") if time_up else "")
            return _finish_turn(db, vs, st, client_turn_id=client_turn_id, child_text="", child_verdict="flagged",
                                child_item=item["id"], words=None, tutor_text=text,
                                base={"verdict": "none", "safety_flag": category, "asr": asr})

    a = _assess(db, st, item, heard, duration_s) if heard else None
    if a is None or a["verdict"] == "silent":
        # -- nothing heard: no try used; re-ask, and check in after a few silences
        st["silent_streak"] += 1
        if time_up:
            st["done"], st["current"] = True, None
            text = _line(db, st, "wrap_up")
        elif st["silent_streak"] % SILENT_CHECK_IN == 0:
            text = _join(breather, _line(db, st, "silent", item, None, st["attempt"]))
        else:
            text = _join(breather, _line(db, st, "intro_item", item))
        return _finish_turn(db, vs, st, client_turn_id=client_turn_id, child_text="", child_verdict="silent",
                            child_item=item["id"], words=None, tutor_text=text,
                            base={"verdict": "silent", "heard": heard, "asr": asr})

    # -- judged answer
    st["silent_streak"] = 0
    tried = st["attempt"]
    out = st["outcomes"][item["id"]]
    out["attempts"].append({"attempt": tried, "verdict": a["verdict"], "score": a["score"], "heard": a["heard"] or heard,
                            "errors": a["errors"], "words": a["words"], "fluency": a.get("fluency"),
                            "at": _now().isoformat()})
    _note_weak(st, a["errors"])
    parts: list[str] = []
    stage_changed = False
    finished = None
    if a["verdict"] == "correct":
        finished = "first_try" if tried == 1 else "after_retry"
        parts.append(_line(db, st, "praise", item, a, tried))
    elif tried >= _max_tries(st):
        finished = "failed"
        parts.append(_line(db, st, "move_on", item, a, tried))
    else:
        st["attempt"] += 1
        parts.append(_line(db, st, "retry_hint", item, a, tried))

    if finished:
        out["result"] = finished
        out["final"] = a
        out["evidence"] = _write_evidence(db, vs, st, item, finished, a["score"])
        if item["kind"] == "read_paragraph" and finished != "failed":
            st["pending"] = list(item.get("followup_ids") or []) + st["pending"]
        _after_item(db, vs, st, finished, tried)  # the plan decides the next stage; no climbing on streaks
        stage_changed = st["stage"] != item["stage"]

    if time_up:
        if not finished:
            _close_current(st, "unfinished")
        st["done"], st["current"] = True, None
        parts.append(_line(db, st, "wrap_up"))
    elif finished:
        _serve(st, _next_item(db, st))
        nxt = st["items"].get(st["current"]) if st["current"] else None
        if stage_changed:
            parts.append(_line(db, st, "stage_up" if STAGES.index(st["stage"]) > STAGES.index(item["stage"])
                               else "stage_down", nxt, None, 1))
        parts.append(breather)
        parts.append(_line(db, st, "intro_item", nxt) if nxt else "")
    else:
        parts.append(breather)

    return _finish_turn(db, vs, st, client_turn_id=client_turn_id, child_text=heard, child_verdict=a["verdict"],
                        child_item=item["id"], words=a["words"], tutor_text=_join(*parts),
                        base={"verdict": a["verdict"], "score": a["score"], "heard": a["heard"] or heard,
                              "words": a["words"], "errors": a["errors"], "stage_changed": stage_changed,
                              "asr": asr, "item_result": finished})


def skip(db: Session, vs: VoiceSession, *, item_id: str, client_turn_id: str | None = None) -> dict:
    prior = _replay(db, vs, client_turn_id)
    if prior is not None:
        return prior
    st = _phase_defaults(_state(vs))
    if vs.status == "ended" or st["done"]:
        return _wrap_reply(db, vs, st)
    if item_id != st["current"]:
        # a double tap: the item already moved on, so report where we are without changing anything
        return {**_turn_base(st, verdict="skipped"), "tutor": _tutor("", st["lang"]),
                "transcript_append": []}
    _tick(st, _now())
    item = st["items"][st["current"]]
    _close_current(st, "skipped")
    st["silent_streak"] = 0
    stage_changed = False
    if _time_up(st):
        st["done"], st["current"] = True, None
        text = _line(db, st, "wrap_up")
    else:
        _after_item(db, vs, st, "skipped", st["attempt"])
        stage_changed = st["stage"] != item["stage"]
        _serve(st, _next_item(db, st))
        nxt = st["items"].get(st["current"]) if st["current"] else None
        text = _line(db, st, "intro_item", nxt) if nxt else ""
    return _finish_turn(db, vs, st, client_turn_id=client_turn_id, child_text="", child_verdict="skipped",
                        child_item=item["id"], words=None, tutor_text=text,
                        base={"verdict": "skipped", "asr": "silent", "item_result": "skipped",
                              "stage_changed": stage_changed})


# ------------------------------------------------------------------ end and report
def _report_inputs(st: dict) -> tuple[list[dict], dict[str, dict]]:
    """`turns`: the child's judged tries (and skips) in the order the items were met, each with its
    assessment; `items`: every item met, with the engine's outcome. Silent and safety-redirected
    turns used no try, so they are not in `turns`. Tutor lines are not turns."""
    turns, items = [], {}
    for iid in st["order"]:
        out = st["outcomes"].get(iid)
        if out is None or out.get("result") is None and not out.get("attempts"):
            continue
        it = {k: v for k, v in st["items"][iid].items() if k not in ("followups", "followup_ids")}
        items[iid] = {**it, **out, "attempts_used": len(out["attempts"]),
                      "heard": out["attempts"][-1]["heard"] if out["attempts"] else "",
                      "errors": [e for t in out["attempts"] for e in t.get("errors") or []]}
        for a in out["attempts"]:
            turns.append({"role": "child", "item_id": iid, "kind": it["kind"], "stage": it["stage"], **a})
        if out.get("result") == "skipped":
            turns.append({"role": "child", "item_id": iid, "kind": it["kind"], "stage": it["stage"],
                          "verdict": "skipped", "skipped": True, "heard": "", "errors": []})
    return turns, items


def _fallback_report(vs: VoiceSession, st: dict, items: dict[str, dict]) -> dict:
    """Minimal report if voice_report fails: counts the engine already knows."""
    res = [i["result"] for i in items.values()]
    judged = [r for r in res if r in ("first_try", "after_retry", "failed")]
    stages = []
    for s in STAGES:
        its = [i for i in items.values() if i["stage"] == s and i["result"] in ("first_try", "after_retry", "failed")]
        if its:
            stages.append({"stage": s, "attempted": len(its),
                           "correct": sum(i["result"] != "failed" for i in its),
                           "failed": sum(i["result"] == "failed" for i in its)})
    wcpm = [a["fluency"]["wcpm"] for i in items.values() if i["kind"] == "read_paragraph"
            for a in i["attempts"][-1:] if a.get("fluency") and a["fluency"].get("wcpm")]
    return {"lang": vs.lang, "items_attempted": len(judged),
            "first_try": res.count("first_try"), "after_retry": res.count("after_retry"),
            "failed": res.count("failed"), "skipped": res.count("skipped"),
            "accuracy": round((len(judged) - res.count("failed")) / len(judged), 2) if judged else 0.0,
            "highest_stage": st["highest_stage"], "stages": stages, "strengths": [], "weaknesses": [],
            "mistakes": [{"item": item_key(i), "stage": i["stage"], "heard": i["heard"], "attempts": i["attempts_used"],
                          "errors": [f"{e.get('target', '')}→{e.get('heard', '')}" for e in i["errors"]]}
                         for i in items.values() if i["result"] == "failed"],
            "difficult_words": [item_key(i) for i in items.values() if i["result"] == "failed"],
            "difficult_sounds": [{"sound": s, "confused_with": "", "count": n}
                                 for s, n in sorted(st["sound_counts"].items(), key=lambda x: -x[1])],
            "topics_attention": [], "fluency": {"wcpm": round(sum(wcpm) / len(wcpm), 1) if wcpm else None,
                                               "paragraphs": len(wcpm)},
            "next_steps": {"hi": [], "en": []}}


def _fallback_narrative(report: dict) -> dict:
    n, acc = report.get("items_attempted", 0), round(100 * float(report.get("accuracy") or 0))
    m = report.get("minutes", 0)
    en = f"{{name}} practised for {m} minutes with Saathi: {n} questions, {acc}% right."
    hi = f"{{name}} ने साथी के साथ {m} मिनट अभ्यास किया: {n} सवाल, {acc}% सही।"
    return {"parent_hi": hi, "parent_en": en, "teacher_en": en, "teacher_hi": hi}


def outcome(st: dict) -> dict | None:
    """How the session went against its plan, and what the next one should practise (code decides)."""
    plan = st.get("plan")
    if not plan:
        return None
    focus = plan["focus_stage"]
    log = st["focus_hist"].get(focus, [])
    acc = round(sum(log) / len(log), 2) if log else 0.0
    mastered = focus in st["mastered"]
    moved = st.get("moved_up_to")
    sx = st["stretch"]
    stretch_ok = bool(sx["stage"]) and sx["done"] and sx["items"] > 0 and sx["correct"] == sx["items"]
    unplaced = st.get("phase") == "placement"  # stopped before the level was found: find it next time
    nxt = None if unplaced else (moved or (sx["stage"] if stretch_ok else focus))
    L = voice_plan.label
    if unplaced:
        en, hi = "Saathi will find the level again next time.", "अगली बार साथी फिर से स्तर पता करेगा।"
    elif moved:
        en = f"Mastered {L(focus).lower()}, so next time: {L(moved).lower()}."
        hi = f"{L(focus, 'hi')} पक्का हुआ, अगली बार: {L(moved, 'hi')}।"
    elif stretch_ok:
        en = f"Got every {L(sx['stage']).lower()} challenge right, so next time: {L(sx['stage']).lower()}."
        hi = f"चुनौती ({L(sx['stage'], 'hi')}) में सब सही, अगली बार: {L(sx['stage'], 'hi')}।"
    elif mastered:
        en = f"Mastered {L(focus).lower()}: next time harder {L(focus).lower()}."
        hi = f"{L(focus, 'hi')} पक्का हुआ: अगली बार और कठिन अभ्यास।"
    else:
        pct = round(100 * acc)
        en = f"Keep practising {L(focus).lower()} ({len(log)} tries, {pct}% right)."
        hi = f"अभ्यास जारी रखें: {L(focus, 'hi')} ({len(log)} सवाल, {pct}% सही)।"
    return {"focus_stage": focus, "focus_items": len(log), "focus_accuracy": acc, "mastered": mastered,
            "moved_up_to": moved, "stretch_stage": sx["stage"], "stretch_items": sx["items"],
            "stretch_correct": sx["correct"], "next_focus_stage": nxt, "next_reason_en": en, "next_reason_hi": hi}


def end(db: Session, vs: VoiceSession, *, reason: str = "parent_stop") -> dict:
    _drop_prefetch(vs.id)
    if vs.status == "ended" and vs.report is not None:
        return copy.deepcopy(vs.report)
    st = _phase_defaults(_state(vs))
    now = _now()
    if not st["done"]:
        _tick(st, now)
        _close_current(st, "unfinished")
        st["current"] = None
        st["done"] = True
    turns, items = _report_inputs(st)
    vs.status, vs.ended_at, vs.end_reason = "ended", _naive(now), reason
    started = vs.started_at.replace(tzinfo=timezone.utc)
    try:
        report = dict(build_report(lang=vs.lang, started_at=started, ended_at=now, turns=turns, items=items,
                                   content=get_content(), session_id=vs.id))
    except Exception:
        report = _fallback_report(vs, st, items)
    minutes = round(st["elapsed_s"] / 60, 1)
    report["session_id"] = vs.id
    report.setdefault("lang", vs.lang)
    report["minutes"] = minutes  # active minutes (paused time excluded), the same figure the app's timer shows
    report["end_reason"] = reason
    report["safety_flags"] = sorted({f["category"] for f in st["safety_flags"]})
    if st.get("plan"):  # what the session set out to practise, and how it went
        report["plan"] = copy.deepcopy(st["plan"])
        report["outcome"] = outcome(st)
    # Claude's narrative takes 20-60 s (four texts, mostly Hindi), too long to hold the parent at
    # "end". Store the templated narrative now; a background thread upgrades it when Claude is done.
    from app.ai import voice_tutor
    ai_later = voice_tutor._ai_ready()
    try:
        if ai_later:
            _apply_narrative(report, voice_tutor.fallback_narrative(copy.deepcopy(report)), "pending")
        else:  # no key: the templated narrative is instant
            narr, status = write_narrative(db, school_id=vs.school_id, lang=vs.lang, report=copy.deepcopy(report))
            _apply_narrative(report, narr, status)
            report = _localize(db, vs.school_id, vs.lang, report)
    except Exception:
        report["narrative"] = _fallback_narrative(report)
        report["narrative_status"] = "fallback"
        ai_later = False
    if not report.get("narrative"):
        report["narrative"] = _fallback_narrative(report)
    report.setdefault("next_steps", {"hi": [], "en": []})
    vs.report = report
    _save(vs, st)
    db.flush()
    if ai_later:
        _narrate_later(vs.id, vs.school_id, vs.lang, copy.deepcopy(report))
    return copy.deepcopy(report)


def localize_report(db: Session, **kw) -> dict:
    from app.ai import voice_tutor
    return voice_tutor.localize_report(db, **kw)


def _localize(db: Session, school_id: int, lang: str, report: dict) -> dict:
    """Report texts in the session language (other languages only; hi/en reports are unchanged)."""
    if is_reviewed_lang(lang):
        return report
    try:
        return localize_report(db, school_id=school_id, lang=lang, report=report)
    except Exception:
        return report


def _apply_narrative(report: dict, narr: dict, status: str) -> None:
    narr = dict(narr or {})
    for k in ("content_lang", "machine_translated", "untranslated"):  # labels of a translated narrative
        if k in narr:
            report[f"narrative_{k}" if k != "content_lang" else k] = narr.pop(k)
    if "narrative" in narr:
        report["narrative"] = narr["narrative"]
        if narr.get("next_steps"):
            report["next_steps"] = narr["next_steps"]
    else:
        steps = narr.pop("next_steps", None)
        report["narrative"] = narr
        if steps:
            report["next_steps"] = steps
    report["narrative_status"] = status


def _narrate_later(session_id: int, school_id: int, lang: str, report: dict) -> None:
    """Write Claude's narrative off the request and swap it into the stored report when ready."""
    import time

    def run():
        from app.db import SessionLocal
        try:
            with SessionLocal() as s:
                narr, status = write_narrative(s, school_id=school_id, lang=lang, report=copy.deepcopy(report))
                s.commit()
        except Exception:
            narr, status = None, "fallback"
        local = None
        if not is_reviewed_lang(lang):
            try:
                with SessionLocal() as s:
                    local = _localize(s, school_id, lang, copy.deepcopy(report))
                    s.commit()
            except Exception:
                local = None
        for _ in range(20):  # the ending request may not have committed yet
            with SessionLocal() as s:
                vs = s.get(VoiceSession, session_id)
                if vs is None:
                    return
                if vs.report is None:
                    time.sleep(1)
                    continue
                new = copy.deepcopy(vs.report)
                if local:  # translated report texts (additive keys only)
                    new.update({k: v for k, v in local.items()
                                if k in ("strengths", "weaknesses", "topics_attention", "mistakes",
                                         "content_lang", "machine_translated")})
                if status == "ai" and narr:
                    _apply_narrative(new, narr, "ai")
                elif narr and not is_reviewed_lang(lang):
                    _apply_narrative(new, narr, "fallback")  # templated, plus its translation
                else:
                    new["narrative_status"] = "fallback"
                vs.report = new
                s.commit()
                return

    threading.Thread(target=run, daemon=True, name=f"voice-narrative-{session_id}").start()


def finalize_if_stale(db: Session, vs: VoiceSession) -> None:
    """Build the report for a session whose time ran out (or was left open) but was never ended."""
    if vs.status != "active":
        return
    st = vs.state or {}
    idle = (_now() - datetime.fromisoformat(st["last_at"])).total_seconds() if st.get("last_at") else 0
    if st.get("done"):
        end(db, vs, reason="time_up")
    elif idle > STALE_S:
        end(db, vs, reason="abandoned")


def summary(vs: VoiceSession) -> dict:
    """One row of the past-sessions list."""
    st, rep = vs.state or {}, vs.report
    if rep:
        items, acc, high, minutes = (rep.get("items_attempted", 0), rep.get("accuracy", 0.0),
                                     rep.get("highest_stage"), rep.get("minutes", 0))
    else:
        res = [o.get("result") for o in (st.get("outcomes") or {}).values()]
        judged = [r for r in res if r in ("first_try", "after_retry", "failed")]
        items = len(judged)
        acc = round((items - res.count("failed")) / items, 2) if items else 0.0
        high, minutes = st.get("highest_stage", vs.stage), round(st.get("elapsed_s", 0) / 60, 1)
    plan = (rep or {}).get("plan") or st.get("plan") or {}
    oc = (rep or {}).get("outcome") or {}
    return {"id": vs.id, "lang": vs.lang, "started_at": iso(vs.started_at), "minutes": minutes, "items": items,
            "accuracy": acc, "highest_stage": high, "status": vs.status, "safety_flag": vs.safety_flag,
            "focus_stage": oc.get("focus_stage") or st.get("focus_stage") or plan.get("focus_stage"),
            "mastered": bool(oc.get("mastered")) if oc else (plan.get("focus_stage") in (st.get("mastered") or [])),
            "next_focus_stage": oc.get("next_focus_stage"), "plan_source": plan.get("source")}


def list_for_child(db: Session, child_id: int, limit: int = 30) -> list[dict]:
    rows = db.scalars(select(VoiceSession).where(VoiceSession.child_id == child_id)
                      .order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc()).limit(limit))
    return [summary(r) for r in rows]


def detail(db: Session, vs: VoiceSession) -> dict:
    finalize_if_stale(db, vs)
    return {"session": session_view(db, vs), "report": copy.deepcopy(vs.report) if vs.report else None}
