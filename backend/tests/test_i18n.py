"""Language registry, script checks, translate_texts fallbacks/cache, the content library, and the
generated content/i18n files (docs/lang_provider_contract.md §1, §3). No API key: deterministic paths."""
import importlib.util
import json

import pytest
from sqlalchemy import delete

from app.config import BACKEND_DIR, get_settings
from app.db import SessionLocal
from app.i18n import library
from app.i18n.languages import APP_LANGS, LANGUAGES, language, prompt_instruction
from app.i18n.script import graphemes, in_script
from app.i18n.translate import src_hash, text_problems, translate_texts
from app.models.tables import TranslationCache


# ------------------------------------------------------------------ registry
def test_registry_has_all_23_in_order():
    assert len(APP_LANGS) == 23 and tuple(LANGUAGES) == APP_LANGS
    assert language("or").name_en == "Odia" and language("or").script == "Odia"
    assert {c for c, lg in LANGUAGES.items() if lg.rtl} == {"ur", "sd", "ks"}
    for lg in LANGUAGES.values():  # every native name is written in its own script
        assert in_script(lg.name_native, lg.code), lg.code
    with pytest.raises(KeyError):
        language("xx")


def test_prompt_instruction():
    assert prompt_instruction("mr") == ("Write every learner-facing and classroom text in Marathi "
                                        "(मराठी, Devanagari script). Keep numerals as digits.")
    assert "English (Latin script)" in prompt_instruction("en")


# ------------------------------------------------------------------ script
@pytest.mark.parametrize("text,code,ok", [
    ("गाय घास खाती है।", "hi", True),
    ("गाय घास खाती है।", "mr", True),  # same script
    ("गाय घास खाती है।", "ta", False),
    ("45 − 18 = ? ₹52", "ta", True),  # no letters at all
    ("The cow eats grass.", "en", True),
    ("The cow खाती", "en", False),
    ("আমি স্কুলে যাই।", "bn", True),
    ("আমি স্কুলে যাই।", "as", True),
    ("ਮੈਂ ਸਕੂਲ ਜਾਂਦਾ ਹਾਂ।", "pa", True),
    ("நான் பள்ளிக்குச் செல்கிறேன்.", "ta", True),
    ("ମୁଁ ସ୍କୁଲ ଯାଏ।", "or", True),
    ("میں اسکول جاتا ہوں۔", "ur", True),
    ("ᱥᱟᱱᱛᱟᱲᱤ", "sat", True),
    ("ꯃꯤꯇꯩꯂꯣꯟ", "mni", True),
    ("", "kn", True),
])
def test_in_script(text, code, ok):
    assert in_script(text, code) is ok


@pytest.mark.parametrize("text,want", [
    ("किताब", ["कि", "ता", "ब"]),
    ("क्षमा", ["क्ष", "मा"]),
    ("स्कूल", ["स्कू", "ल"]),
    ("चिड़िया", ["चि", "ड़ि", "या"]),
    ("माँ", ["माँ"]),
    ("স্কুল", ["স্কু", "ল"]),
    ("ಅಕ್ಕ", ["ಅ", "ಕ್ಕ"]),
    ("అమ్మ", ["అ", "మ్మ"]),
    ("അമ്മ", ["അ", "മ്മ"]),
    ("ਪੰਜਾਬੀ", ["ਪੰ", "ਜਾ", "ਬੀ"]),
    ("க்க", ["க்", "க"]),  # Tamil pulli does not build a conjunct
    ("cat", ["c", "a", "t"]),
    ("a b", ["a", " ", "b"]),
])
def test_graphemes(text, want):
    assert graphemes(text) == want


# ------------------------------------------------------------------ translate_texts
def test_text_problems():
    assert text_problems("45 − 18 करो", "45 − 18 करा", "mr") == []
    assert any("numbers" in p for p in text_problems("45 − 18 करो", "45 − 81 करा", "mr"))
    assert any("script" in p for p in text_problems("बोलो: का", "சொல்: का", "ta"))
    assert text_problems("x", "  ", "ta") == ["empty"]
    assert any("placeholders" in p for p in text_problems("नमस्ते {name}", "Hello", "en"))


def test_translate_identity_and_no_key_fallback():
    with SessionLocal() as db:
        assert translate_texts(db, ["गाय"], "hi") == [{"text": "गाय", "machine_translated": False}]
        out = translate_texts(db, ["गाय घास खाती है। (परीक्षण)", "45 − 18 = ?", ""], "ta")
        assert out[0] == {"text": "गाय घास खाती है। (परीक्षण)", "machine_translated": False, "untranslated": True}
        assert out[1] == {"text": "45 − 18 = ?", "machine_translated": False}
        assert out[2] == {"text": "", "machine_translated": False}
        assert translate_texts(db, ["गाय"], "xx")[0]["untranslated"] is True
        assert translate_texts(db, [], "ta") == []
        db.rollback()


def test_translate_uses_cache_without_a_key():
    src = "यह वाक्य केवल कैश परीक्षण के लिए है।"
    with SessionLocal() as db:
        db.execute(delete(TranslationCache).where(TranslationCache.src_hash == src_hash(src)))
        db.add(TranslationCache(src_lang="hi", tgt_lang="mr", src_hash=src_hash(src), src=src,
                                text="हे वाक्य फक्त कॅशे चाचणीसाठी आहे."))
        db.commit()
        out = translate_texts(db, [src, src], "mr")
        assert out == [{"text": "हे वाक्य फक्त कॅशे चाचणीसाठी आहे.", "machine_translated": True}] * 2
        db.execute(delete(TranslationCache).where(TranslationCache.src_hash == src_hash(src)))
        db.commit()


# ------------------------------------------------------------------ library
def test_library_sources_and_fallbacks():
    hi = library.localized("activity", "act_borrow_sticks", "title", "hi")
    assert hi == {"text": "सींकों से उधार वाला घटाव", "machine_translated": False}
    steps = library.localized("activity", "act_borrow_sticks", "steps", "hi")["text"]
    assert isinstance(steps, list) and len(steps) == 5
    en = library.localized("checkpoint", "N.G1.count_to_20", "title", "en")
    assert en == {"text": "Count objects up to 20", "machine_translated": False}
    assert library.localized("level_check", "literacy/letter", "ask", "en")["text"].startswith("Point to")
    assert library.localized("level_check", "literacy", "beginner", "hi")["text"] == "शुरुआत (अक्षर अभी नहीं)"
    # a language with no pre-translated files and no live call: Hindi source, labelled untranslated
    sa = library.localized("probe", "L.G1.vyanjan", "items", "sa")
    assert sa["untranslated"] is True and sa["text"][0] == "ये बोलो: स, श"
    assert library.localized("activity", "no_such_activity", "title", "mr")["text"] is None
    with SessionLocal() as db:  # live translation path with no key also falls back
        assert library.localized("activity", "act_borrow_sticks", "title", "sa", db=db)["untranslated"] is True
        db.rollback()
    assert library.literacy_ladder("hi") is None
    assert library.checkpoint_titles("en")["N.G1.count_to_20"] == "Count objects up to 20"


def test_library_reads_pretranslated_files(tmp_path, monkeypatch):
    d = tmp_path / "i18n" / "mr"
    d.mkdir(parents=True)
    (d / "activities.json").write_text(json.dumps(
        {"activities": {"act_borrow_sticks": {"title": "काड्यांनी वजाबाकी", "steps": ["एक"]}}}), encoding="utf-8")
    (d / "checkpoint_titles.json").write_text(json.dumps({"titles": {"N.G1.count_to_20": "20 पर्यंत मोजणे"}}),
                                              encoding="utf-8")
    monkeypatch.setattr(library, "i18n_dir", lambda: tmp_path / "i18n")
    library.reload()
    try:
        assert library.localized("activity", "act_borrow_sticks", "title", "mr") == \
            {"text": "काड्यांनी वजाबाकी", "machine_translated": True}
        assert library.checkpoint_titles("mr") == {"N.G1.count_to_20": "20 पर्यंत मोजणे"}
        assert library.available_languages() == ["mr"]
        # a field the file lacks falls back to Hindi, labelled
        assert library.localized("activity", "act_borrow_sticks", "materials", "mr")["untranslated"] is True
    finally:
        library.reload()


# ------------------------------------------------------------------ generated content/i18n files
def _script_module():
    spec = importlib.util.spec_from_file_location("translate_content", BACKEND_DIR / "scripts" / "translate_content.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GENERATED = sorted(p.name for p in (get_settings().content_dir / "i18n").glob("*") if p.is_dir()) \
    if (get_settings().content_dir / "i18n").exists() else []


@pytest.mark.parametrize("lang", GENERATED)
def test_generated_files_pass_checks(lang):
    """Every generated string is in the target script, keeps the source digits, and counts match."""
    mod = _script_module()
    assert mod.check_lang(lang) == []
    lad = library.literacy_ladder(lang)
    assert lad["reviewed"] is False and lad["machine_translated"] is True
    for lv in lad["levels"]:
        for it in lv["items"] + lv["practice"]:
            assert in_script(it["show"], lang)
