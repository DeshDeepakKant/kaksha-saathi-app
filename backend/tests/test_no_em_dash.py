"""The UI must never show an em dash: static text, reviewed content and model output."""
import json
from pathlib import Path

from app.ai.llm import plain_dashes

ROOT = Path(__file__).resolve().parents[2]
DASH = "—"


def test_plain_dashes_cleans_nested_model_output():
    out = plain_dashes({"a": f"one {DASH} two", "b": [f"{DASH}", {"c": f"x{DASH}y"}], "n": 3})
    assert out == {"a": "one, two", "b": ["-", {"c": "x-y"}], "n": 3}


def test_reviewed_content_has_no_em_dash():
    for f in (ROOT / "content").rglob("*.json"):  # includes content/i18n/<lang>/
        assert DASH not in f.read_text(encoding="utf-8"), str(f)


def test_translation_tables_have_no_em_dash():
    """assets/i18n keys are the English strings, so keys and values must change together."""
    for app in ("parent", "teacher"):
        for f in (ROOT / "apps" / app / "assets" / "i18n").glob("*.json"):
            assert DASH not in f.read_text(encoding="utf-8"), str(f)


def test_teacher_notes_have_no_em_dash():
    from app.ai import features
    for name in ("BOOK_FALLBACK_NOTE", "BOOK_UNKNOWN_NOTE", "REVISE_FALLBACK_NOTE"):
        assert DASH not in getattr(features, name), name


def test_app_screens_have_no_em_dash():
    for app in ("parent", "teacher"):
        for f in (ROOT / "apps" / app / "lib").rglob("*.dart"):
            assert DASH not in f.read_text(encoding="utf-8"), str(f)
