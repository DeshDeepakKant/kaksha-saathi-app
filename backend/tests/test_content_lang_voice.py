"""The voice session and parent-side learning content in every content language
(docs/lang_provider_contract.md section 4, Backend-Voice).

Claude, the translator and the speech providers are replaced with small fakes, so these tests pin our
own plumbing: the language reaches items, judging, Saathi's lines, speech-to-text (with the parent's
provider) and the report; Marathi is judged as Devanagari without Hindi-only rules; Tamil (another
script) is judged on its own grapheme clusters; hi/en keep their exact behaviour (the existing voice
tests run unchanged).
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai import voice_schemas as vs
from app.ai import voice_tutor
from app.core.security import hash_phone, hash_pin, make_token
from app.db import SessionLocal
from app.i18n import script, translate
from app.models.tables import Child, Classroom, Evidence, LevelCheck, ParentAccount, School, Teacher
from app.services import parent_insights, prefs, voice_bank
from app.services import voice_session as vse
from app.speech import assess, capabilities
from app.speech.scorer import score_read

SAMPLE = {"mr": "छान", "ta": "நன்று"}  # a word in each script, used by the fake translator
PH = re.compile(r"\{\w+\}")


# ------------------------------------------------------------------ fakes
class FakeTranslator:
    """translate_texts stand-in: a word in the target script, keeping every placeholder."""

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, db, texts, target, source="hi", school_id=None):
        self.seen += list(texts)
        if target == source or target not in SAMPLE:
            return [{"text": t, "machine_translated": False, "untranslated": target != source} for t in texts]
        return [{"text": " ".join([SAMPLE[target], *PH.findall(t)]) + ".", "machine_translated": True}
                for t in texts]


MR_POOL = {  # hand-written Marathi items Claude "returns" (compact raw shape of ITEMS_SCHEMA)
    "letter": [{"kind": "read_letter", "text": t, "prompt": "{name}, हे अक्षर वाच.", "difficulty": 1 + n % 3,
                "gloss_en": f"the letter {t}"} for n, t in enumerate("अआकखगमपब")],
    "word_build": [{"kind": "build_word", "tiles": tiles, "target": "".join(tiles),
                    "prompt": "{name}, हे तुकडे जोडून शब्द बोल.", "difficulty": 1 + n % 3, "gloss_en": gloss}
                   for n, (tiles, gloss) in enumerate([(["पा", "णी"], "water"), (["घ", "र"], "house"),
                                                       (["झा", "ड"], "tree"), (["फू", "ल"], "flower"),
                                                       (["मा", "सा"], "fish"), (["आं", "बा"], "mango")])],
    "word_read": [{"kind": "read_word", "text": w, "prompt": "{name}, हा शब्द वाच.", "difficulty": 1 + n % 3,
                   "gloss_en": g} for n, (w, g) in enumerate([("शाळा", "school"), ("दूध", "milk"),
                                                              ("गाय", "cow"), ("पाऊस", "rain"),
                                                              ("चेंडू", "ball"), ("पुस्तक", "book")])],
    "sentence_build": [{"kind": "make_sentence", "words": w, "example": ex, "prompt": "{name}, या शब्दांनी एक वाक्य बोल.",
                        "difficulty": 1 + n % 3, "gloss_en": g}
                       for n, (w, ex, g) in enumerate([
                           (["शाळा", "मुले"], "शाळा मोठी आहे आणि मुले खेळतात", "school, children"),
                           (["गाय", "दूध"], "गाय आपल्याला दूध देते", "cow, milk"),
                           (["पाऊस", "आज"], "आज खूप पाऊस पडला", "rain, today"),
                           (["आंबा", "गोड"], "हा आंबा खूप गोड आहे", "mango, sweet")])],
    "reading": [{"kind": "read_sentence", "text": t, "prompt": "{name}, हे वाक्य वाच.", "difficulty": 1 + n % 3,
                 "gloss_en": g} for n, (t, g) in enumerate([("आई घरी जेवण करते.", "mother cooks at home"),
                                                            ("गाय हिरवे गवत खाते.", "the cow eats green grass"),
                                                            ("आम्ही शाळेत जातो.", "we go to school")])],
}


def fake_call(*, timeout, **kw):
    """voice_tutor._call stand-in: Marathi items / lines / verdicts, validated by the real validators."""
    feature = kw["feature"]
    if feature == "voice_items":
        req = json.loads(kw["user"].split("\n", 1)[1])
        avoid = set(req["avoid"])
        raws = [r for r in MR_POOL[req["stage"]]
                if r.get("text", r.get("target")) not in avoid][: req["how_many"]]
        return SimpleNamespace(data=kw["validate"]({"items": raws}))
    if feature == "voice_tutor":
        return SimpleNamespace(data=kw["validate"]({"line": "छान {name}! पुन्हा प्रयत्न कर.",
                                                    "gloss_en": "Good {name}! Try again."}))
    if feature == "voice_open_eval":
        return SimpleNamespace(data=kw["validate"]({"verdict": "correct", "reason": "uses both words"}))
    raise voice_tutor.llm.LLMUnavailable("not faked")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def translator(monkeypatch):
    f = FakeTranslator()
    monkeypatch.setattr(translate, "translate_texts", f)
    monkeypatch.setattr(voice_tutor, "_LOCAL", {})
    monkeypatch.setattr(voice_tutor, "_PREPARING", set())
    return f


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(vse, "CLOCK", c)
    return c


@pytest.fixture
def langs(monkeypatch):
    monkeypatch.setattr(capabilities, "content_languages", lambda: ["en", "hi", "mr", "ta"])


@pytest.fixture(autouse=True)
def _content_langs(langs):
    """The real prefs/voice validation reads content_languages(); declare them for every test here."""


@pytest.fixture(scope="module")
def sandbox():
    with SessionLocal() as db:
        school = School(name="Content Lang School", code="CL" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="CL Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.flush()
        cls = Classroom(school_id=school.id, teacher_id=t.id, grade=2, section="L", label="2L")
        db.add(cls)
        db.commit()
        return {"school_id": school.id, "class_id": cls.id, "roll": 0}


@pytest.fixture
def kid(sandbox):
    """A fresh child + parent: (headers, child_id, parent_id)."""
    sandbox["roll"] += 1
    with SessionLocal() as db:
        c = Child(class_id=sandbox["class_id"], roll_no=sandbox["roll"], first_name="Kavya")
        db.add(c)
        db.flush()
        p = ParentAccount(school_id=sandbox["school_id"], child_id=c.id, phone_hash=hash_phone("9111111111"),
                          pin_hash=hash_pin("0000"))
        db.add(p)
        db.commit()
        return {"Authorization": f"Bearer {make_token(str(p.id), 'parent')}"}, c.id, p.id


def _level(sandbox, child_id, key, index):
    """A literacy level check for the child (the session plans its focus from it)."""
    with SessionLocal() as db:
        db.add(LevelCheck(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=child_id,
                          subject="literacy", level_index=index, level_key=key, at=datetime(2026, 10, 20)))
        db.commit()


def _set_prefs(parent_id, school_id, **fields):
    with SessionLocal() as db:
        prefs.set_prefs(db, "parent", parent_id, school_id, **fields)
        db.commit()


def _turn(client, h, s, item_id, transcript=None, audio=None):
    meta = {"item_id": item_id, "client_turn_id": uuid.uuid4().hex}
    if transcript is not None:
        meta["transcript"] = transcript
    files = {"audio": ("t.wav", audio, "audio/wav")} if audio else None
    r = client.post(f"/v1/parent/voice/sessions/{s['id']}/turn", headers=h, data={"meta": json.dumps(meta)},
                    files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _answer(item) -> str:
    """The right answer to a public item (targets of build_word are hidden: join the tiles)."""
    d = item["display"]
    if item["kind"] == "build_word":
        return "".join(d["tiles"])
    if item["kind"] == "make_sentence":
        return " ".join(d["words"]) + " खूप छान आहेत"
    return d["text"]


def _strip(x, lang):
    """A payload without the additive content-language fields."""
    if isinstance(x, dict):
        return {k: _strip(v, lang) for k, v in x.items()
                if not k.endswith(f"_{lang}") and k not in ("content_lang", "machine_translated", "untranslated")}
    if isinstance(x, list):
        return [_strip(v, lang) for v in x]
    return x


def _mostly(text, lang):
    letters = [c for c in text if c.isalpha()]
    return letters and sum(script.in_script(c, lang) for c in letters) * 2 >= len(letters)


# ------------------------------------------------------------------ judging (code decides)
def test_marathi_is_devanagari_without_hindi_rules():
    # Devanagari akshara analysis still applies: a matra slip is found
    a = assess.assess_reading("पाणी", "पाणि", "mr")
    assert a.verdict == "close" and any(e["type"] == "matra" for e in a.errors)
    # the Hindi spelling fold गयी = गई is a Hindi habit, not applied to Marathi
    assert assess.assess_reading("गयी", "गई", "hi").verdict == "correct"
    assert assess.assess_reading("गयी", "गई", "mr").verdict != "correct"
    # Hindi verb stems (खाना ~ खाती) don't count for Marathi; a Marathi case ending does
    assert assess.assess_sentence_build(["खाना", "आम"], "वह आम खाती है", "hi").verdict == "correct"
    assert assess.assess_sentence_build(["खाना", "आम"], "ती आम खाती आहे", "mr").verdict != "correct"
    assert assess.assess_sentence_build(["शाळा", "मुले"], "मुले शाळेला जातात", "mr").verdict == "correct"
    # Hindi fillers are not dropped from a Marathi answer
    assert assess._tokens("हम आम", "hi") == ["आम"] and assess._tokens("हम आम", "mr") == ["हम", "आम"]


def test_tamil_is_judged_on_its_own_clusters():
    assert assess.aksharas("பள்ளி") == ["ப", "ள்", "ளி"]  # Tamil pulli ends a letter (i18n.script.graphemes)
    assert assess.assess_reading("பள்ளி", "பள்ளி", "ta").verdict == "correct"
    a = assess.assess_reading("பள்ளி", "பல்லி", "ta")
    assert a.verdict != "correct" and a.errors
    assert all(e["type"] != "matra" for e in a.errors)  # no Hindi matra rules on another script
    assert {e["target"] for e in a.errors} <= set(assess.aksharas("பள்ளி"))
    letter = {"kind": "read_letter", "lang": "ta", "target": "க", "display": {"text": "க"}}
    assert assess.assess_item(letter, "கா").verdict == "correct"   # letter read with its aa sign
    assert assess.assess_item(letter, "ம").verdict == "wrong"
    # a Tamil case ending on a required word still counts as using it
    assert assess.assess_sentence_build(["பூனை", "பால்"], "பூனை பாலை குடித்தது", "ta").verdict == "correct"


def test_numbers_digits_only_without_a_number_word_table():
    assert score_read(["5"], "पाँच").n_correct == 1                 # Hindi number words: unchanged
    assert score_read(["5"], "ஐந்து", lang="ta").n_correct == 0     # no Tamil number-word table
    assert score_read(["5"], "௫", lang="ta").n_correct == 1         # a Tamil digit is the same number
    assert score_read(["12"], "১২", lang="bn").n_correct == 1


def test_script_and_item_rules_per_language():
    assert vs.script_ok("பூனை", "ta") and not vs.script_ok("पाणी", "ta") and vs.script_ok("पाणी", "mr")
    assert not vs.script_ok("பூனை 2", "ta") and not vs.script_ok("cat", "ta")
    assert vs.graphemes("மரம்") == ["ம", "ர", "ம்"]
    item = {"id": "x", "stage": "word_build", "kind": "build_word", "lang": "ta", "checkpoint_id": None,
            "prompt": "{name}, இவற்றை சேர்த்து சொல்.", "display": {"tiles": ["ம", "ர", "ம்"]}, "target": "மரம்",
            "accept": [], "required_words": [], "keywords": [], "max_record_s": 5, "difficulty": 1,
            "source": "ai", "followups": []}
    assert vs.item_problems(item, lang="ta", stage="word_build") == ["gloss_en (plain English meaning) required"]
    assert vs.item_problems({**item, "gloss_en": "tree"}, lang="ta", stage="word_build") == []
    assert vs.item_problems({**item, "gloss_en": "a gun"}, lang="ta", stage="word_build") == ["unsafe gloss"]
    assert vs.item_problems({**item, "lang": "ta"}, lang="hi", stage="word_build")  # wrong lang


# ------------------------------------------------------------------ sessions
def test_marathi_session_with_claude_items(client, kid, sandbox, translator, clock, langs, monkeypatch):
    h, child_id, parent_id = kid
    _level(sandbox, child_id, "letter", 0)  # reads letters: warm up on letters, focus on building words
    monkeypatch.setattr(voice_tutor, "_ai_ready", lambda: True)
    monkeypatch.setattr(voice_tutor, "_call", fake_call)
    from app.services import voice_bank
    monkeypatch.setattr(voice_bank, "lang_dir", lambda lang: voice_bank.Path("/nonexistent-i18n") / lang)
    voice_bank._load_lang.cache_clear()
    r = client.post("/v1/parent/voice/sessions", headers=h, json={"lang": "mr"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["lang"] == "mr" and s["item"]["lang"] == "mr" and s["item"]["source"] == "ai"
    assert vs.script_ok(s["item"]["display"]["text"], "mr")
    assert s["tutor"]["lang"] == "mr" and s["tutor"]["machine_translated"] is True
    assert "Kavya" in s["tutor"]["text"] and _mostly(s["tutor"]["text"].replace("Kavya", ""), "mr")
    assert not any("Kavya" in t for t in translator.seen)  # the child's name never goes to the translator

    item, stages = s["item"], {s["stage"]}
    for _ in range(10):  # 2 warm-up letters, then 8 words built right: mastered, one stage up
        clock.advance(20)
        t = _turn(client, h, s, item["id"], _answer(item))  # judged by the real Marathi assessment
        assert t["verdict"] == "correct", (item, t)
        assert t["tutor"]["lang"] == "mr" and t["next_item"]["lang"] == "mr"
        item = t["next_item"]
        stages.add(t["stage"])
    assert {"letter", "word_build", "word_read"} <= stages
    assert t["focus_stage"] == "word_read" and t["stage_changed"]

    assert item["kind"] == "read_word" and item["source"] == "ai"
    for _ in range(5):  # one item not managed: a mistake for the report
        clock.advance(20)
        t = _turn(client, h, s, item["id"], "कमळ")
    assert t["item_result"] == "failed" and t["verdict"] == "wrong"

    monkeypatch.setattr(voice_tutor, "_ai_ready", lambda: False)  # narrative: templated + translated, at once
    rep = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={}).json()
    assert rep["lang"] == "mr" and rep["content_lang"] == "mr" and rep["machine_translated"] is True
    assert rep["narrative"]["parent_hi"] and rep["narrative"]["parent_en"]  # teacher app keeps hi/en
    assert _mostly(rep["narrative"]["parent_mr"], "mr") and _mostly(rep["narrative"]["teacher_mr"], "mr")
    assert rep["next_steps"]["mr"] and all(_mostly(x, "mr") for x in rep["next_steps"]["mr"])
    assert rep["mistakes"] and rep["mistakes"][0]["errors_mr"]
    assert rep["narrative_status"] == "fallback" and rep["narrative_machine_translated"] is True
    with SessionLocal() as db:  # home-language evidence lands on the built-in literacy checkpoints
        evs = list(db.scalars(select(Evidence).where(Evidence.child_id == child_id,
                                                     Evidence.source == "home_voice")))
    assert evs and all(e.checkpoint_id.startswith("L.") for e in evs)


def _write_tamil_files(folder):
    folder.mkdir(parents=True, exist_ok=True)
    items = [{"id": f"ta-let-{n}", "stage": "letter", "kind": "read_letter", "lang": "ta",
              "checkpoint_id": "L.G1.vyanjan", "prompt": "{name}, இந்த எழுத்தை படி.", "display": {"text": t},
              "target": t, "difficulty": 1 + n % 3, "grade": 1, "reviewed": False}
             for n, t in enumerate("அஆஇகமபதந")]
    items += [{"id": f"ta-wr-{n}", "stage": "word_read", "kind": "read_word", "lang": "ta",
               "checkpoint_id": "L.G1.read_matra_words", "prompt": "{name}, இந்த சொல்லை படி.",
               "display": {"text": w}, "target": w, "difficulty": 1 + n % 3, "grade": 1, "reviewed": False}
              for n, w in enumerate(["பூனை", "மரம்", "வீடு", "நாய்", "பசு", "கை"])]
    items.append({"id": "ta-bad", "stage": "letter", "kind": "read_letter", "lang": "ta", "checkpoint_id": None,
                  "prompt": "read this", "display": {"text": "a"}, "target": "a", "reviewed": False})  # dropped
    (folder / "voice_bank.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    ladder = {"levels": [{"key": "word", "checkpoint_id": "L.G1.read_matra_words",
                          "items": [{"show": "பள்ளி"}, {"show": "பழம்"}]},
                         {"key": "sentence", "checkpoint_id": "L.G1.read_short_sentences",
                          "items": [{"show": "நான் பள்ளிக்கு போகிறேன்."}]}]}
    (folder / "level_check_literacy.json").write_text(json.dumps(ladder, ensure_ascii=False), encoding="utf-8")


def test_tamil_session_defaults_to_parent_language(client, kid, sandbox, translator, clock, langs,
                                                   monkeypatch, tmp_path):
    h, child_id, parent_id = kid
    _level(sandbox, child_id, "letter", 0)  # warm up on letters, focus on building words
    _write_tamil_files(tmp_path / "ta")
    monkeypatch.setattr(voice_bank, "lang_dir", lambda lang: tmp_path / lang)
    voice_bank._load_lang.cache_clear()
    monkeypatch.setattr(voice_tutor, "_ai_ready", lambda: False)  # no key: items come from the files
    _set_prefs(parent_id, sandbox["school_id"], content_lang="ta", voice_provider="gnani")
    heard = []

    def fake_transcribe(audio, filename, lang="hi", keyterms=None, preferred="sarvam"):
        heard.append((lang, preferred))
        return SimpleNamespace(text=current["answer"], lang=lang, provider=preferred, fallback_used=False, error=None)

    from app import speech
    monkeypatch.setattr(speech, "transcribe", fake_transcribe, raising=False)
    monkeypatch.setattr(capabilities, "providers_for", lambda cap, lang: ["gnani", "sarvam"])

    r = client.post("/v1/parent/voice/sessions", headers=h, json={})  # no lang: the parent's content language
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["lang"] == "ta" and s["item"]["lang"] == "ta" and s["item"]["id"].startswith("ta-let")
    assert _mostly(s["tutor"]["text"].replace("Kavya", ""), "ta")

    item = s["item"]
    current = {"answer": _answer(item)}
    clock.advance(10)
    t = _turn(client, h, s, item["id"], audio=b"RIFF0000WAVE")  # speech-to-text in Tamil, parent's provider
    assert heard == [("ta", "gnani")] and t["asr"] == "asr" and t["verdict"] == "correct"
    item = t["next_item"]
    for _ in range(2):
        clock.advance(10)
        t = _turn(client, h, s, item["id"], _answer(item))
        assert t["verdict"] == "correct"
        item = t["next_item"]
    assert t["stage"] == "word_build"  # after the warm-up; no Tamil build_word items: emergency letters
    assert item["kind"] == "read_letter" and vs.script_ok(item["display"]["text"], "ta")

    for _ in range(5):
        clock.advance(10)
        t = _turn(client, h, s, item["id"], "வீடு")  # wrong every time
    assert t["item_result"] == "failed"
    bad = [e for e in t["errors"] if e.get("type") == "substitution"]
    assert bad and all(script.in_script(e["target"] + e["heard"], "ta") for e in bad)

    rep = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={}).json()
    assert rep["lang"] == "ta" and rep["content_lang"] == "ta"
    assert _mostly(rep["narrative"]["parent_ta"], "ta") and rep["next_steps"]["ta"]
    assert not any("matra" in x for m in rep["mistakes"] for x in m["errors"])
    sessions = client.get("/v1/parent/voice/sessions", headers=h).json()
    assert sessions[0]["lang"] == "ta"


def test_tamil_bank_reads_files_and_ladder(translator, monkeypatch, tmp_path):
    _write_tamil_files(tmp_path / "ta")
    monkeypatch.setattr(voice_bank, "lang_dir", lambda lang: tmp_path / lang)
    voice_bank._load_lang.cache_clear()
    letters = voice_bank.pick(lang="ta", stage="letter", n=20)
    assert letters and "ta-bad" not in {i["id"] for i in letters}  # Latin item failed the code gate
    words = voice_bank.pick(lang="ta", stage="word_read", n=20)
    assert {"பள்ளி", "பழம்"} <= {i["target"] for i in words}           # ladder words become read_word items
    ladder = next(i for i in words if i["target"] == "பள்ளி")
    assert ladder["prompt"] == "{name}, read this word."                # untranslated: the safe English ask
    with SessionLocal() as db:
        voice_tutor.translate_lines(db, "ta", list(voice_bank._LADDER_PROMPT_EN.values()))
    ladder = next(i for i in voice_bank.pick(lang="ta", stage="word_read", n=20) if i["target"] == "பள்ளி")
    assert ladder["prompt"].startswith(SAMPLE["ta"]) and "{name}" in ladder["prompt"]
    assert voice_bank.pick(lang="ta", stage="reading", n=5)[0]["kind"] == "read_sentence"
    voice_bank._load_lang.cache_clear()


def test_lang_validation_and_default(client, kid, sandbox, translator, clock, monkeypatch):
    h, _, parent_id = kid
    _set_prefs(parent_id, sandbox["school_id"], content_lang="ta")  # saved while Tamil speech was available
    monkeypatch.setattr(capabilities, "content_languages", lambda: ["hi", "en"])  # now no speech provider set up
    r = client.post("/v1/parent/voice/sessions", headers=h, json={"lang": "ta"})
    assert r.status_code == 422
    assert client.post("/v1/parent/voice/sessions", headers=h, json={"lang": "xx"}).status_code == 422
    r = client.post("/v1/parent/voice/sessions", headers=h, json={})
    assert r.status_code == 200 and r.json()["lang"] == "hi"  # Tamil can't be heard/spoken now: Hindi
    assert "machine_translated" not in r.json()["tutor"]      # hi payload exactly as before


def test_tutor_lines_translated_once_with_english_fallback(translator):
    with SessionLocal() as db:
        assert voice_tutor.template_line("ta", "praise", {}, None, 1).isascii()  # not prepared: English
        assert voice_tutor.prepare_language(db, "ta") is True
    line = voice_tutor.template_line("ta", "praise", {}, None, 1)
    assert _mostly(line.replace("{name}", ""), "ta")
    hint = voice_tutor.template_line("ta", "retry_hint", {"kind": "read_word", "target": "மரம்"}, None, 2)
    assert "மரம்" in hint and _mostly(hint, "ta")  # the model word goes into the translated template
    assert voice_tutor.template_line("hi", "praise", {}, None, 1) in voice_tutor.TEMPLATES["hi"]["praise"]


def test_bad_translations_are_not_said(monkeypatch):
    monkeypatch.setattr(voice_tutor, "_LOCAL", {})
    outs = {"Hello {name}!": {"text": "வணக்கம்!", "machine_translated": True},          # lost {name}
            "Look at this one.": {"text": "Look at this one.", "untranslated": True},
            "Your turn now.": {"text": "उदाहरण", "machine_translated": True},              # wrong script
            "Try this one.": {"text": "இதை முயற்சி செய்.", "machine_translated": True}}
    monkeypatch.setattr(translate, "translate_texts",
                        lambda db, texts, target, source="hi", school_id=None: [outs[t] for t in texts])
    voice_tutor.translate_lines(None, "ta", list(outs))
    assert voice_tutor.local("ta", "Try this one.") == "இதை முயற்சி செய்."
    assert [voice_tutor.local("ta", t) for t in list(outs)[:3]] == list(outs)[:3]  # English kept


def test_marathi_ai_narrative_validated(monkeypatch):
    report = {"lang": "mr", "minutes": 12, "items_attempted": 6, "first_try": 4, "after_retry": 1, "failed": 1,
              "skipped": 0, "accuracy": 0.83, "highest_stage": "word_read", "stages": [], "strengths": [],
              "weaknesses": [], "mistakes": [{"item": "पाणी", "stage": "word_read", "heard": "पाणि",
                                               "attempts": 5, "errors": ["ी matra read as ि"]}],
              "difficult_words": ["पाणी"], "difficult_sounds": [], "topics_attention": [],
              "fluency": {"wcpm": None, "paragraphs": 0}}
    good = {"narrative": {
        "parent_hi": "आज आपके बच्चे ने 12 मिनट अभ्यास किया। 'पाणी' पर थोड़ा अभ्यास चाहिए। शाबाश!",
        "parent_en": "Today your child practised for 12 minutes. 'पाणी' needs a little practice. Well done!",
        "teacher_en": "Highest stage: reading words; 4 right first try; difficult word 'पाणी'.",
        "teacher_hi": "सबसे ऊँचा स्तर: शब्द पढ़ना; 4 पहली बार सही; कठिन शब्द 'पाणी'।",
        "parent_mr": "आज तुमच्या मुलाने 12 मिनिटे सराव केला. 'पाणी' या शब्दाचा थोडा सराव हवा. छान!",
        "teacher_mr": "सर्वोच्च टप्पा: शब्द वाचन; पहिल्या प्रयत्नात 4 बरोबर; कठीण शब्द 'पाणी'."},
        "next_steps": {"hi": ["'पाणी' रोज़ पढ़ें।", "एक छोटी कहानी पढ़ें।", "शाबाशी दें।"],
                       "en": ["Read 'पाणी' daily.", "Read a short story.", "Praise every try."],
                       "mr": ["'पाणी' रोज वाचा.", "एक छोटी गोष्ट वाचा.", "प्रत्येक प्रयत्नाचे कौतुक करा."]}}
    calls = []

    def fake(*, timeout, **kw):
        calls.append(kw)
        return SimpleNamespace(data=kw["validate"](good))

    monkeypatch.setattr(voice_tutor, "_ai_ready", lambda: True)
    monkeypatch.setattr(voice_tutor, "_call", fake)
    out, status = voice_tutor.write_narrative(None, school_id=None, lang="mr", report=report)
    assert status == "ai" and out["narrative"]["parent_mr"].startswith("आज तुमच्या")
    assert out["next_steps"]["mr"][0] == "'पाणी' रोज वाचा." and out["content_lang"] == "mr"
    assert calls[0]["prompt_version"] == "v2" and "parent_mr" in json.dumps(calls[0]["schema"])
    bad = json.loads(json.dumps(good))
    bad["narrative"]["parent_mr"] = "Today your child practised. Needs practice. Well done!"  # not Marathi
    with pytest.raises(ValueError):
        vs.validate_narrative(bad, report=report)
    bad["narrative"]["parent_mr"] = "आज 99 मिनिटे सराव केला. छान! पुन्हा करू."  # number not in the report
    with pytest.raises(ValueError):
        vs.validate_narrative(bad, report=report)


# ------------------------------------------------------------------ parent insights / parent API
def test_parent_insights_translated_for_other_languages(client, kid, sandbox, translator):
    h, child_id, parent_id = kid
    base = client.get("/v1/parent/school_week", headers=h).json()
    assert "content_lang" not in base and "line_ta" not in base  # hi default: exactly as before
    _set_prefs(parent_id, sandbox["school_id"], content_lang="ta")
    week = client.get("/v1/parent/school_week", headers=h).json()
    assert _strip(week, "ta") == base                                # additive only
    assert week["content_lang"] == "ta" and week["machine_translated"] is True
    assert _mostly(week["line_ta"].replace("Kavya", ""), "ta") and "Kavya" not in " ".join(translator.seen)
    weekly = client.get("/v1/parent/weekly", headers=h).json()
    assert weekly["line_ta"] and weekly["content_lang"] == "ta"
    child = client.get("/v1/parent/child", headers=h).json()
    assert child["content_lang"] == "ta"
    assert all(f["title_ta"] and f["label_ta"] for f in child["focus"])


def test_parent_insights_untranslated_keeps_english(client, kid, sandbox, monkeypatch):
    h, child_id, parent_id = kid
    _set_prefs(parent_id, sandbox["school_id"], content_lang="ta")
    week = client.get("/v1/parent/school_week", headers=h).json()  # stand-in translator: no model, no change
    assert week["line_ta"] == week["line_en"] and week["machine_translated"] is False and week["untranslated"]
