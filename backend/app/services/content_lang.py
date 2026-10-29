"""The teacher's content language on classroom flows: STT, library text and lesson titles.

Content language = the language of learning content, AI-written classroom text and speech
(docs/lang_provider_contract.md §4). Hindi (`hi`) is the source language of the reviewed library, so a
Hindi teacher always gets the stored text untouched and nothing here looks anything up.
Library text in another language comes from `i18n.library.localized` and is labelled
`machine_translated`; it is only ever applied to responses, never written back to storage.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import prefs

SOURCE_LANG = "hi"


def for_teacher(db: Session, teacher) -> tuple[str, str]:
    """(content language, preferred voice provider) for this teacher."""
    return prefs.content_lang_for(db, teacher=teacher), prefs.provider_for(db, teacher=teacher)


def transcribe(audio: bytes, filename: str, lang: str = SOURCE_LANG, keyterms: list[str] | None = None,
               preferred: str = "sarvam"):
    """`app.speech.transcribe` (provider order + fallback per contract §2). Until that lands, the old
    single-provider client with the language passed through. Returns an object with `.text`."""
    import app.speech as speech
    fn = getattr(speech, "transcribe", None)
    if fn is not None:
        return fn(audio, filename, lang=lang, keyterms=keyterms, preferred=preferred)
    return speech.get_asr().transcribe(audio, filename, language=lang, keyterms=keyterms)


# Names used here (content-file style) -> names `i18n.library.localized` expects.
_LIB_KIND = {"activities": "activity", "probes": "probe", "checkpoint_titles": "checkpoint"}


def _lib_field(field: str) -> str:
    if field == "items_ask_hi":
        return "items"
    return field[:-3] if field.endswith("_hi") else field


def loc(kind: str, id: str, field: str, lang: str, source):
    """(value, machine_translated) for one library field in `lang`; the source for Hindi or on any miss.

    A localized value must have the source's shape (a string for a string, a list of the same length for a
    list); anything else is ignored so a bad translation file can never break a plan or probe."""
    if lang == SOURCE_LANG or source is None:
        return source, False
    try:
        from app.i18n import library
        r = library.localized(_LIB_KIND.get(kind, kind), id, _lib_field(field), lang)
    except Exception:
        return source, False
    if isinstance(r, dict) and "text" in r:
        val, mt = r["text"], bool(r.get("machine_translated"))
    else:
        val, mt = r, r != source
    if val is None or type(val) is not type(source) or (isinstance(val, list) and len(val) != len(source)):
        return source, False
    return val, mt and val != source


def checkpoint_title(content, cid: str, lang: str) -> tuple[str, bool]:
    """A lesson title in `lang`. English uses the reviewed `title_en`; a school's own topic keeps the
    title the teacher typed."""
    cp = content.checkpoints.get(cid)
    if cp is None:
        return cid, False
    if lang == SOURCE_LANG:
        return cp.title_hi, False
    if lang == "en" and cp.title_en:
        return cp.title_en, False
    if cid in content.custom_ids:
        return cp.title_hi or cp.title_en, False
    return loc("checkpoint_titles", cid, "title", lang, cp.title_hi)


def titles(content, lang: str, school_id: int | None) -> dict:
    """`GET /v1/content/titles` body: every lesson title this school can see, in `lang`."""
    out, mt = {}, False
    for cid in content.checkpoints:
        if cid in content.custom_ids and (school_id is None or not cid.startswith(f"C{school_id}-")):
            continue  # another school's custom topic
        out[cid], m = checkpoint_title(content, cid, lang)
        mt = mt or m
    return {"lang": lang, "titles": out, "machine_translated": mt}


ACTIVITY_FIELDS = ("title_hi", "steps_hi", "materials_hi", "blackboard_hi")


def activity(act: dict | None, lang: str) -> dict | None:
    """A copy of a library activity with its classroom text in `lang` (+ `machine_translated`).
    Hindi: the activity unchanged (same object, no new keys)."""
    if act is None or lang == SOURCE_LANG:
        return act
    out, mt = dict(act), False
    for f in ACTIVITY_FIELDS:
        if f in act:
            out[f], m = loc("activities", act.get("id", ""), f, lang, act[f])
            mt = mt or m
    re_ = act.get("reassessment")
    if isinstance(re_, dict) and re_.get("ask_hi"):
        ask, m = loc("activities", act.get("id", ""), "reassessment_ask_hi", lang, re_["ask_hi"])
        out["reassessment"] = {**re_, "ask_hi": ask}
        mt = mt or m
    out["machine_translated"] = mt
    return out


def probe(p: dict | None, cid: str, lang: str) -> dict | None:
    """A copy of a guided probe with its questions in `lang` (+ `machine_translated`). Hindi: unchanged."""
    if p is None or lang == SOURCE_LANG:
        return p
    out, mt = dict(p), False
    for f in ("title_hi", "tell_hi"):
        if f in p:
            out[f], m = loc("probes", cid, f, lang, p[f])
            mt = mt or m
    items = p.get("items")
    if isinstance(items, list):
        asks = [i.get("ask_hi", "") if isinstance(i, dict) else "" for i in items]
        new, m = loc("probes", cid, "items_ask_hi", lang, asks)
        out["items"] = [{**i, "ask_hi": a} if isinstance(i, dict) else i for i, a in zip(items, new)]
        mt = mt or m
    out["machine_translated"] = mt
    return out


def translate(db: Session, texts: list[str], lang: str, school_id: int | None = None) -> tuple[list[str], bool]:
    """Canned Hindi lines (template plans) in `lang` via `i18n.translate.translate_texts`. Never raises;
    returns the Hindi lines when translation is unavailable."""
    if lang == SOURCE_LANG or not texts:
        return texts, False
    try:
        from app.i18n.translate import translate_texts
        rows = translate_texts(db, texts, lang, source=SOURCE_LANG, school_id=school_id)
        out = [str(r.get("text") or t) for r, t in zip(rows, texts)]
        if len(out) != len(texts):
            return texts, False
        return out, any(r.get("machine_translated") for r in rows)
    except Exception:
        return texts, False
