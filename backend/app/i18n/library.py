"""The content library in any content language.

Reviewed Hindi stays the source of truth (`content/*.json`). Other languages come from pre-translated
files in `content/i18n/<code>/` (written by backend/scripts/translate_content.py, all labelled
`machine_translated`), then from a live `translate_texts` call when a session is given, then from the
Hindi source. English checkpoint titles and level-check lines use the reviewed `*_en` source fields.

    localized("activity", "act_borrow_sticks", "steps", "mr")
      -> {"text": ["...", ...], "machine_translated": True}

Kinds and fields:
    activity     id = activity id        title | materials | steps | blackboard | reassessment_ask
    probe        id = checkpoint id      title | tell | pass_rule | items (list of ask lines)
    checkpoint   id = checkpoint id      title
    level_check  id = "<subject>/<level key>" (title | ask), or "<subject>" (title | beginner)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

SOURCE = "hi"
FILES = {"activity": "activities.json", "probe": "probes.json", "checkpoint": "checkpoint_titles.json",
         "level_check": "level_check_asks.json"}


def i18n_dir() -> Path:
    return get_settings().content_dir / "i18n"


@lru_cache(maxsize=256)
def _load(lang: str, name: str) -> dict | None:
    path = i18n_dir() / lang / name
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def reload() -> None:
    """Forget loaded files (after regenerating them)."""
    _load.cache_clear()


# ------------------------------------------------------------------ source (reviewed Hindi / English)
def _level_source(id: str, field: str, lang: str) -> str | None:
    from app.services.level_check import load_ladders
    subject, _, key = id.partition("/")
    lad = load_ladders().get(subject)
    if lad is None:
        return None
    if not key:
        node = lad if field == "title" else lad.get("beginner", {}) if field == "beginner" else None
        f = "title"
    else:
        node = next((lv for lv in lad["levels"] if lv["key"] == key), None)
        f = field if field in ("title", "ask") else None
    if node is None or f is None:
        return None
    return node.get(f"{f}_{lang}")


def source(kind: str, id: str, field: str, lang: str = SOURCE):
    """The reviewed source value (`lang` = 'hi', or 'en' where an English source exists), or None."""
    from app.services.content import get_content
    c = get_content()
    if kind == "activity":
        a = c.activities.get(id)
        if a is None or lang != SOURCE:
            return None
        if field == "reassessment_ask":
            return (a.get("reassessment") or {}).get("ask_hi")
        return a.get(f"{field}_hi")
    if kind == "probe":
        p = c.probes.get(id)
        if p is None or lang != SOURCE:
            return None
        if field == "items":
            return [it.get("ask_hi", "") for it in p.get("items", [])]
        return p.get("pass_rule") if field == "pass_rule" else p.get(f"{field}_hi")
    if kind == "checkpoint":
        cp = c.checkpoints.get(id)
        if cp is None or field != "title" or lang not in ("hi", "en"):
            return None
        return cp.title_hi if lang == "hi" else (cp.title_en or None)
    if kind == "level_check":
        return _level_source(id, field, lang) if lang in ("hi", "en") else None
    return None


# ------------------------------------------------------------------ pre-translated files
def _from_file(kind: str, id: str, field: str, lang: str):
    data = _load(lang, FILES.get(kind, ""))
    if not data:
        return None
    if kind == "activity":
        return (data.get("activities", {}).get(id) or {}).get(field)
    if kind == "probe":
        return (data.get("probes", {}).get(id) or {}).get(field)
    if kind == "checkpoint":
        return data.get("titles", {}).get(id) if field == "title" else None
    if kind == "level_check":
        subject, _, key = id.partition("/")
        node = data.get("subjects", {}).get(subject) or {}
        if key:
            return (node.get("levels", {}).get(key) or {}).get(field)
        return node.get(field)
    return None


def localized(kind: str, id: str, field: str, lang: str, db=None, school_id: int | None = None) -> dict:
    """`{text, machine_translated}` for one content field in `lang` (text is a list for steps/items).

    Order: reviewed source in that language → pre-translated file → live translation (only when `db`
    is given) → Hindi source with `untranslated: True`. Unknown ids give `{text: None, ...}`.
    """
    own = source(kind, id, field, lang)
    if own is not None:
        return {"text": own, "machine_translated": False}
    hit = _from_file(kind, id, field, lang)
    if hit is not None:
        return {"text": hit, "machine_translated": True}
    src = source(kind, id, field, SOURCE)
    if src is None:
        return {"text": None, "machine_translated": False, "untranslated": True}
    if db is not None:
        from app.i18n.translate import translate_texts
        items = src if isinstance(src, list) else [src]
        out = translate_texts(db, items, lang, SOURCE, school_id=school_id)
        if all(not o.get("untranslated") for o in out):
            texts = [o["text"] for o in out]
            return {"text": texts if isinstance(src, list) else texts[0],
                    "machine_translated": any(o["machine_translated"] for o in out)}
    return {"text": src, "machine_translated": False, "untranslated": True}


def checkpoint_titles(lang: str) -> dict[str, str]:
    """All checkpoint titles in `lang` that exist without a live call (reviewed or pre-translated).
    Hindi/English come from the graph; other languages from the file (missing ids are left out)."""
    from app.services.content import get_content
    c = get_content()
    if lang in ("hi", "en"):
        return {cid: (cp.title_hi if lang == "hi" else cp.title_en or cp.title_hi)
                for cid, cp in c.checkpoints.items()}
    data = _load(lang, FILES["checkpoint"]) or {}
    return dict(data.get("titles", {}))


def literacy_ladder(lang: str) -> dict | None:
    """The reading-level ladder generated natively in `lang` (`content/i18n/<lang>/level_check_literacy.json`),
    or None (Hindi uses the reviewed ladder in content/level_check.json). Not reviewed: `reviewed: false`."""
    if lang == SOURCE:
        return None
    return _load(lang, "level_check_literacy.json")


def available_languages() -> list[str]:
    """Languages that have pre-translated library files."""
    d = i18n_dir()
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / FILES["activity"]).exists())
