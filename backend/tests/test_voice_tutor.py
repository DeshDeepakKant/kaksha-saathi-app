"""Voice-session AI tutor: item bank, validators, fallbacks (no network; conftest blanks the key)."""
from __future__ import annotations

import collections
import time
import unicodedata

import pytest

from app.ai import llm, voice_schemas as vs, voice_tutor as vt
from app.db import SessionLocal
from app.services import voice_bank
from app.services.voice_types import STAGES, Assessment

LANGS = ("hi", "en")


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def fake_claude(monkeypatch):
    """Pretend Claude is configured; each test sets the payload (dict, or callable(kw) -> dict)."""
    calls: list[dict] = []
    state = {"payload": None}

    def structured(session, **kw):
        calls.append(kw)
        p = state["payload"]
        data = p(kw) if callable(p) else p
        if kw.get("validate"):
            try:
                data = kw["validate"](data)
            except Exception as e:  # mirrors llm.structured: invalid -> LLMValidationError
                raise llm.LLMValidationError(str(e))
        return llm.LLMResult(data, kw["model"], 10, 10, 5, 0.0)

    monkeypatch.setattr(vt, "_ai_ready", lambda: True)
    monkeypatch.setattr(llm, "structured", structured)
    state["calls"] = calls
    return state


def bank(lang=None, stage=None, kind=None):
    return [i for i in voice_bank.all_items() if (lang is None or i["lang"] == lang)
            and (stage is None or i["stage"] == stage) and (kind is None or i["kind"] == kind)]


def item(lang, kind):
    return voice_bank.to_item(bank(lang, kind=kind)[0])


# ---------------------------------------------------------------- bank
@pytest.mark.parametrize("lang", LANGS)
def test_bank_covers_every_stage_and_difficulty(lang):
    for stage in STAGES:
        items = bank(lang, stage)
        assert len(items) >= 25, (lang, stage, len(items))
        per_diff = collections.Counter(i["difficulty"] for i in items)
        assert all(per_diff[d] >= 5 for d in (1, 2, 3)), (lang, stage, per_diff)


def test_every_bank_item_passes_the_validator():
    items = bank()
    assert items and all(i["reviewed"] is True for i in items)
    ids = [i["id"] for i in items] + [f["id"] for i in items for f in i["followups"]]
    assert len(ids) == len(set(ids))
    for i in items:
        assert vs.item_problems(i, lang=i["lang"], stage=i["stage"], grade=i.get("grade")) == [], i["id"]
        assert vs.item_problems(voice_bank.to_item(i), lang=i["lang"], stage=i["stage"], grade=i.get("grade")) == []


def test_build_word_tiles_join_and_paragraphs_have_questions():
    for i in bank(kind="build_word"):
        assert unicodedata.normalize("NFC", "".join(i["display"]["tiles"])) == i["target"]
        assert "text" not in i["display"]
    for lang in LANGS:
        paras = bank(lang, kind="read_paragraph")
        assert len(paras) >= 6
        for p in paras:
            assert len(p["followups"]) == 2
            for f in p["followups"]:
                assert f["kind"] == "answer_question" and f["keywords"]
                assert all(vs._contains(p["display"]["text"], k, lang) for k in f["keywords"])


def test_bank_has_confusable_letters():
    hi_letters = {i["target"] for i in bank("hi", "letter")}
    for a, b in [("श", "स"), ("ब", "व"), ("ड", "ड़")]:
        assert a in hi_letters and b in hi_letters
    en_letters = {i["target"] for i in bank("en", "letter")}
    assert {"b", "d", "p", "q"} <= en_letters


def test_bank_pick_is_deterministic_avoids_and_targets_weak_sounds():
    a = voice_bank.pick(lang="hi", stage="word_read", grade=2, n=6, seed=7)
    b = voice_bank.pick(lang="hi", stage="word_read", grade=2, n=6, seed=7)
    assert [i["id"] for i in a] == [i["id"] for i in b]
    assert all(i["source"] == "bank" for i in a)
    avoid = [i["id"] for i in a] + [a[0]["target"]]
    c = voice_bank.pick(lang="hi", stage="word_read", grade=2, n=6, seed=7, avoid=avoid)
    assert not {i["id"] for i in c} & set(avoid)
    weak = voice_bank.pick(lang="hi", stage="letter", grade=1, n=3, seed=1, weak_sounds=["श→स"])
    assert any("श" in (i["target"] or "") + (i["display"].get("text") or "") for i in weak)


# ---------------------------------------------------------------- generate_items
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("stage", STAGES)
def test_generate_items_falls_back_to_bank_without_key(db, lang, stage):
    items, src = vt.generate_items(db, school_id=1, lang=lang, grade=2, stage=stage, topics=[], avoid=[],
                                   weak_sounds=[], n=6)
    assert src == "bank" and len(items) == 6
    assert len({i["id"] for i in items}) == 6
    for i in items:
        assert set(vs.ITEM_KEYS) <= set(i) and i["stage"] == stage and i["lang"] == lang


def test_generate_items_repeats_rather_than_runs_dry(db):
    every = [i["id"] for i in bank("en", "word_read")]
    items, src = vt.generate_items(db, school_id=1, lang="en", grade=2, stage="word_read", topics=[],
                                   avoid=every, weak_sounds=[], n=6)
    assert len(items) == 6 and src == "bank"


GOOD_HI_WORDS = {"items": [
    {"kind": "build_word", "prompt": "इन टुकड़ों को जोड़कर शब्द बोलो।", "tiles": ["ब", "स्ता"], "target": "बस्ता", "difficulty": 3},
    {"kind": "build_word", "prompt": "जोड़ो और बोलो।", "tiles": ["म", "ग"], "target": "मग", "difficulty": 1},
    {"kind": "build_word", "prompt": "जोड़ो और बोलो।", "tiles": ["ता", "ला"], "target": "ताला", "difficulty": 2,
     "checkpoint_id": "custom.99"},
]}


def test_generate_items_uses_valid_ai_items(db, fake_claude):
    fake_claude["payload"] = GOOD_HI_WORDS
    topics = [{"checkpoint_id": "custom.99", "title_hi": "घर की चीज़ें", "title_en": "Things at home", "custom": True}]
    items, src = vt.generate_items(db, school_id=1, lang="hi", grade=1, stage="word_build", topics=topics,
                                   avoid=[], weak_sounds=["स"], n=4)
    assert src == "ai" and len(items) == 4
    ai = [i for i in items if i["source"] == "ai"]
    assert len(ai) == 3 and items[3]["source"] == "bank"  # topped up from the bank
    assert ai[2]["checkpoint_id"] == "custom.99" and ai[0]["checkpoint_id"] == "L.G1.blend_no_matra"
    assert all(i["max_record_s"] == 5 for i in ai)
    assert fake_claude["calls"][0]["model"] == vt.get_settings().model_tutor


def test_generate_items_drops_invalid_ai_items(db, fake_claude):
    bad = [
        {"kind": "build_word", "prompt": "जोड़ो।", "tiles": ["क", "म"], "target": "कमल", "difficulty": 1},  # tiles != word
        {"kind": "build_word", "prompt": "kamal bolo", "tiles": ["क", "ल"], "target": "कल", "difficulty": 1},  # Latin prompt
        {"kind": "build_word", "prompt": "बम बोलो।", "tiles": ["ब", "म"], "target": "बम", "difficulty": 1},     # unsafe
        {"kind": "read_word", "prompt": "पढ़ो।", "text": "घर", "difficulty": 1},                              # wrong kind for stage
        {"kind": "build_word", "prompt": "मग बोलो।", "tiles": ["म", "ग"], "target": "मग", "difficulty": 1},    # reveals answer
    ]
    fake_claude["payload"] = {"items": bad + GOOD_HI_WORDS["items"][:1]}
    items, src = vt.generate_items(db, school_id=1, lang="hi", grade=1, stage="word_build", topics=[],
                                   avoid=[], weak_sounds=[], n=6)
    # 1 of 6 valid -> fewer than half -> bank, but nothing invalid slips through
    assert src == "bank" and len(items) == 6
    assert not any(i["source"] == "ai" and i["target"] in {"कमल", "कल", "बम", "मग"} for i in items)
    for i in items:
        assert vs.item_problems(i, lang="hi", stage="word_build", grade=1) == []


def test_generate_items_respects_avoid_and_paragraph_rules(db, fake_claude):
    para = ("मीना रोज़ सुबह अपने भाई के साथ खेत जाती है। वहाँ वह गाय को घास खिलाती है। गाय उसे देखकर खुश होती है। "
            "फिर दोनों घर लौटकर माँ के साथ गरम रोटी खाते हैं और स्कूल जाते हैं।")
    fake_claude["payload"] = {"items": [
        {"kind": "read_paragraph", "prompt": "यह कहानी पढ़ो।", "text": para, "difficulty": 2,
         "followups": [{"question": "मीना गाय को क्या खिलाती है?", "answer": "घास", "keywords": ["घास"]},
                       {"question": "वे स्कूल से पहले क्या खाते हैं?", "answer": "रोटी", "keywords": ["पराठा"]}]},
        {"kind": "read_sentence", "prompt": "यह वाक्य पढ़ो।", "text": "गाय घास खाती है।", "difficulty": 1},
        {"kind": "read_sentence", "prompt": "यह वाक्य पढ़ो।", "text": "आम।", "difficulty": 1},
    ]}
    items, src = vt.generate_items(db, school_id=1, lang="hi", grade=2, stage="reading", topics=[],
                                   avoid=["गाय घास खाती है।"], weak_sounds=[], n=2)
    # paragraph has a keyword missing from the text, sentence 2 is avoided, sentence 3 too short -> bank
    assert src == "bank"
    assert all(i["source"] == "bank" for i in items)


def test_generate_items_ai_paragraph_ok(db, fake_claude):
    para = ("Raju and Asha go to the river every evening. They take a small ball and play on the sand. "
            "Their dog runs after the ball and splashes in the water. When the sun goes down they walk home happily.")
    fake_claude["payload"] = {"items": [
        {"kind": "read_paragraph", "prompt": "Read this story.", "text": para, "difficulty": 2,
         "followups": [{"question": "Where do they go every evening?", "answer": "the river", "keywords": ["river"]},
                       {"question": "Who runs after the ball?", "answer": "their dog", "keywords": ["dog"],
                        "inferential": False}]},
        {"kind": "read_sentence", "prompt": "Read this sentence.", "text": "The cow eats green grass.", "difficulty": 1},
    ]}
    items, src = vt.generate_items(db, school_id=1, lang="en", grade=2, stage="reading", topics=[], avoid=[],
                                   weak_sounds=[], n=2)
    assert src == "ai"
    p = items[0]
    assert p["kind"] == "read_paragraph" and len(p["followups"]) == 2
    assert p["followups"][0]["id"] == p["id"] + "-q1" and p["followups"][0]["context"] == para
    assert p["max_record_s"] >= 30 and p["checkpoint_id"] is None


# ---------------------------------------------------------------- validators
def _ok_item(**over):
    base = {"id": "x1", "stage": "word_read", "kind": "read_word", "lang": "hi", "checkpoint_id": None,
            "prompt": "यह शब्द पढ़ो।", "display": {"text": "कमल"}, "target": "कमल", "accept": [],
            "required_words": [], "keywords": [], "max_record_s": 5, "difficulty": 1, "source": "ai", "followups": []}
    base.update(over)
    return base


def test_item_validator_rejects_bad_items():
    assert vs.item_problems(_ok_item(), lang="hi") == []
    assert vs.item_problems(_ok_item(display={"text": "kamal"}, target="kamal"), lang="hi")
    assert vs.item_problems(_ok_item(display={"text": "कमलकमलकमलकमलक"}, target="कमलकमलकमलकमलक"), lang="hi")
    assert vs.item_problems(_ok_item(), lang="hi", avoid={"कमल"})
    assert vs.item_problems(_ok_item(display={"text": "खून"}, target="खून"), lang="hi")
    assert vs.item_problems(_ok_item(lang="en", prompt="Read this word.", display={"text": "gun"}, target="gun"), lang="en")
    assert vs.item_problems(_ok_item(kind="read_letter", stage="letter", display={"text": "कमल"}), lang="hi")
    letter = _ok_item(kind="read_letter", stage="letter", display={"text": "क्ष"}, target="क्ष")
    assert vs.item_problems(letter, lang="hi") == []
    wb = _ok_item(kind="build_word", stage="word_build", display={"tiles": ["शा", "म"]}, target="शाम",
                  prompt="जोड़कर बोलो।")
    assert vs.item_problems(wb, lang="hi") == []
    assert vs.item_problems({**wb, "display": {"tiles": ["श", "ा", "म"]}}, lang="hi")       # lone matra
    assert vs.item_problems({**wb, "display": {"tiles": ["श", "त्", "रु"]}, "target": "शत्रु"}, lang="hi")
    sent = _ok_item(kind="make_sentence", stage="sentence_build", display={"words": ["गाय", "दूध"]}, target=None,
                    required_words=["गाय", "दूध"], accept=["गाय पानी पीती है।"])
    assert any("example" in p for p in vs.item_problems(sent, lang="hi"))


def test_tutor_text_validator():
    it = item("hi", "build_word")
    assert vs.validate_tutor_text("शाबाश {name}! फिर से बोलो।", lang="hi")
    with pytest.raises(ValueError):
        vs.validate_tutor_text("Good job! फिर से बोलो।", lang="hi")
    with pytest.raises(ValueError):
        vs.validate_tutor_text("एक। दो। तीन।", lang="hi")
    with pytest.raises(ValueError):
        vs.validate_tutor_text(f"यह शब्द {it['target']} है।", lang="hi", item=it, attempt=3)
    assert vs.validate_tutor_text(f"मेरे साथ बोलो, {it['target']}।", lang="hi", item=it, attempt=4)
    with pytest.raises(ValueError):
        vs.validate_tutor_text("You are slow, try again.", lang="en")


# ---------------------------------------------------------------- tutor_line
@pytest.mark.parametrize("lang", LANGS)
def test_tutor_line_templates_for_every_situation(db, lang):
    it = item(lang, "read_word")
    for situation in vt.SITUATIONS:
        for attempt in (1, 2, 3, 4, 5):
            text, src = vt.tutor_line(db, school_id=1, lang=lang, situation=situation, item=it,
                                      assessment=Assessment("wrong", 0.1, "x"), attempt=attempt)
            assert src == "fallback" and text.strip()
            assert vs.script_ok(text, lang, allow_name=True), text
            if situation != "intro_item":
                assert vs.validate_tutor_text(text, lang=lang, item=it, attempt=attempt) == " ".join(text.split())


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("kind", ["build_word", "answer_question"])
def test_hints_escalate_without_revealing_the_answer(db, lang, kind):
    if kind == "answer_question":
        it = voice_bank.to_item(bank(lang, kind="read_paragraph")[0])["followups"][0]
    else:
        it = item(lang, kind)
    a = Assessment("wrong", 0.1, "x", errors=[{"type": "substitution", "target": "क", "heard": "ख", "word": "x"}])
    lines = [vt.tutor_line(db, school_id=1, lang=lang, situation="retry_hint", item=it, assessment=a,
                           attempt=k)[0] for k in range(1, 6)]
    assert len(set(lines)) >= 4  # each attempt says something different
    secrets = [it["target"], *it["accept"], *it["keywords"]]
    for k, line in enumerate(lines[:3], start=1):
        assert not any(vs._contains(line, s, lang) for s in secrets if s), (k, line)
    assert any(vs._contains(lines[3], s, lang) for s in secrets if s)  # attempt 4: say it together


def test_hint_models_reading_items(db):
    it = voice_bank.to_item([i for i in bank("hi", kind="read_word") if i["target"] == "बादल"][0])
    two = vt.tutor_line(db, school_id=1, lang="hi", situation="retry_hint", item=it, assessment=None, attempt=2)[0]
    assert "बा-द-ल" in two
    a = Assessment("wrong", 0.3, "बाजल", errors=[{"type": "substitution", "target": "द", "heard": "ज", "word": "बादल"}])
    three = vt.tutor_line(db, school_id=1, lang="hi", situation="retry_hint", item=it, assessment=a, attempt=3)[0]
    assert "'द'" in three and "'ज'" in three


def test_tutor_line_ai_only_where_it_adds_value(db, fake_claude):
    it = item("hi", "build_word")
    fake_claude["payload"] = {"line": "पहली आवाज़ पर ध्यान दो, फिर बोलो।"}
    a = Assessment("wrong", 0.1, "x", errors=[{"type": "substitution", "target": "क", "heard": "ख", "word": ""}])
    for attempt in (1, 2):
        assert vt.tutor_line(db, school_id=1, lang="hi", situation="retry_hint", item=it, assessment=a,
                             attempt=attempt)[1] == "fallback"
    assert vt.tutor_line(db, school_id=1, lang="hi", situation="praise", item=it, assessment=a, attempt=1)[1] == "fallback"
    assert not fake_claude["calls"]
    text, src = vt.tutor_line(db, school_id=1, lang="hi", situation="retry_hint", item=it, assessment=a, attempt=3)
    assert src == "ai" and text == fake_claude["payload"]["line"]
    assert fake_claude["calls"][-1]["model"] == vt.get_settings().model_extract
    assert vt.tutor_line(db, school_id=1, lang="hi", situation="stage_up", item=it, assessment=None, attempt=1)[1] == "ai"
    # answer reveal before attempt 4, wrong script, too long -> template
    for bad in (f"शब्द है {it['target']}।", "Say it again.", "एक। दो। तीन। चार।"):
        fake_claude["payload"] = {"line": bad}
        assert vt.tutor_line(db, school_id=1, lang="hi", situation="retry_hint", item=it, assessment=a,
                             attempt=3)[1] == "fallback"
    # the secret word never reaches the model for a no-reveal item
    assert it["target"] not in str(fake_claude["calls"][-1]["user"]).replace("\\u", "")


def test_tutor_line_times_out_to_template(db, fake_claude, monkeypatch):
    monkeypatch.setattr(vt, "LINE_TIMEOUT_S", 0.2)
    fake_claude["payload"] = lambda kw: (time.sleep(1.0), {"line": "ठीक है।"})[1]
    started = time.monotonic()
    text, src = vt.tutor_line(db, school_id=1, lang="hi", situation="stage_down", item=item("hi", "read_word"),
                              assessment=None, attempt=1)
    assert src == "fallback" and text and time.monotonic() - started < 0.9


# ---------------------------------------------------------------- evaluate_open
def _sentence_item():
    return voice_bank.to_item([i for i in bank("hi", kind="make_sentence") if i["required_words"] == ["गाय", "दूध"]][0])


def test_evaluate_open_returns_code_without_ai(db):
    code = Assessment("close", 0.5, "गाय दूध")
    assert vt.evaluate_open(db, school_id=1, lang="hi", item=_sentence_item(), transcript="गाय दूध", code=code) is code


def test_evaluate_open_never_upgrades_when_words_missing(db, fake_claude):
    it = _sentence_item()
    fake_claude["payload"] = {"verdict": "correct", "confidence": 0.95, "reason": "Good sentence."}
    code = Assessment("wrong", 0.3, "गाय घास खाती है", errors=[{"type": "missing_word", "target": "दूध", "heard": "", "word": "दूध"}])
    out = vt.evaluate_open(db, school_id=1, lang="hi", item=it, transcript="गाय घास खाती है", code=code)
    assert out.verdict != "correct" and out.judged_by == "ai"
    ok = Assessment("close", 0.6, "गाय दूध देती है")
    out = vt.evaluate_open(db, school_id=1, lang="hi", item=it, transcript="गाय दूध देती है", code=ok)
    assert out.verdict == "correct" and out.judged_by == "ai" and out.notes == "Good sentence."
    fake_claude["payload"] = {"verdict": "wrong", "reason": "Only lists the words."}
    listed = Assessment("correct", 0.9, "गाय दूध गाय दूध")
    out = vt.evaluate_open(db, school_id=1, lang="hi", item=it, transcript="गाय दूध गाय दूध", code=listed)
    assert out.verdict == "wrong" and any(e["type"] == "meaning" for e in out.errors)


def test_evaluate_open_answer_question_and_failures(db, fake_claude):
    q = voice_bank.to_item(bank("en", kind="read_paragraph")[0])["followups"][0]
    code = Assessment("wrong", 0.0, "something else")
    fake_claude["payload"] = {"verdict": "correct", "confidence": 0.9, "reason": "Synonym of the answer."}
    assert vt.evaluate_open(db, school_id=1, lang="en", item=q, transcript="something else", code=code).verdict == "correct"
    fake_claude["payload"] = {"verdict": "correct", "confidence": 0.5, "reason": "Maybe."}
    assert vt.evaluate_open(db, school_id=1, lang="en", item=q, transcript="something else", code=code).verdict == "close"
    fake_claude["payload"] = {"verdict": "maybe", "reason": ""}  # invalid -> code unchanged
    assert vt.evaluate_open(db, school_id=1, lang="en", item=q, transcript="something else", code=code) is code
    silent = Assessment("silent", 0.0, "")
    assert vt.evaluate_open(db, school_id=1, lang="en", item=q, transcript="", code=silent) is silent
    rd = item("en", "read_word")
    assert vt.evaluate_open(db, school_id=1, lang="en", item=rd, transcript="cat", code=code) is code


# ---------------------------------------------------------------- write_narrative
REPORT = {
    "session_id": 41, "lang": "hi", "minutes": 28.5, "items_attempted": 34, "first_try": 20, "after_retry": 8,
    "failed": 4, "skipped": 2, "accuracy": 0.82, "highest_stage": "word_read",
    "stages": [{"stage": "letter", "attempted": 10, "correct": 9, "failed": 1}],
    "strengths": [{"en": "reads simple matra words", "hi": "मात्रा वाले सरल शब्द पढ़ता है"}],
    "weaknesses": [{"en": "confuses श and स", "hi": "श और स में भ्रम"}],
    "mistakes": [{"item": "शेर", "stage": "word_read", "heard": "सेर", "attempts": 5, "errors": ["श→स"]}],
    "difficult_words": ["शेर", "पत्ता"], "difficult_sounds": [{"sound": "श", "confused_with": "स", "count": 3}],
    "topics_attention": [{"checkpoint_id": "L.G1.vyanjan", "title_hi": "व्यंजन पहचानना",
                          "title_en": "Recognise consonants", "reason_en": "3 errors", "reason_hi": "3 गलतियाँ"}],
    "fluency": {"wcpm": None, "paragraphs": 0},
    "narrative": {}, "narrative_status": "fallback", "next_steps": {},
}


def test_narrative_fallback_mentions_only_report_facts(db):
    out, src = vt.write_narrative(db, school_id=1, lang="hi", report=REPORT)
    assert src == "fallback"
    assert set(out["narrative"]) == {"parent_hi", "parent_en", "teacher_en", "teacher_hi"}
    assert len(out["next_steps"]["hi"]) == 3 and len(out["next_steps"]["en"]) == 3
    assert vs.validate_narrative(out, report=REPORT)  # the same checks Claude's text must pass
    assert "'श'" in out["narrative"]["teacher_en"] and "'शेर'" in out["narrative"]["teacher_hi"]
    empty = {"lang": "en", "minutes": 3, "items_attempted": 2, "first_try": 1, "after_retry": 0, "failed": 1,
             "skipped": 0, "accuracy": 0.5, "highest_stage": "letter"}
    out2, _ = vt.write_narrative(db, school_id=1, lang="en", report=empty)
    assert vs.validate_narrative(out2, report=empty)


def _ai_narrative(**over):
    d = {"narrative": {
        "parent_hi": "आज आपके बच्चे ने बहुत मन से पढ़ा। मात्रा वाले शब्द अच्छे से पढ़े। 'श' की आवाज़ पर थोड़ा अभ्यास करें।",
        "parent_en": "Your child read with a lot of interest today. Matra words went well. Practise the 'श' sound a little.",
        "teacher_en": "Highest stage reached was word reading, 20 items right on first try. Confuses 'श' with 'स', for example in 'शेर'.",
        "teacher_hi": "सबसे ऊँचा स्तर शब्द पढ़ना रहा, 20 सवाल पहली बार में सही। 'श' और 'स' में भ्रम है, जैसे 'शेर'।"},
        "next_steps": {"hi": ["'श' और 'स' वाले शब्द बारी-बारी से बोलें।", "'शेर' और 'पत्ता' कागज़ पर लिखकर पढ़वाएँ।",
                              "रोज़ एक छोटी कहानी साथ पढ़ें।"],
                       "en": ["Say words with 'श' and 'स' in turns.", "Write 'शेर' and 'पत्ता' on paper and read them.",
                              "Read a short story together every day."]}}
    d["narrative"].update(over)
    return d


def test_narrative_ai_validated_against_report(db, fake_claude):
    fake_claude["payload"] = _ai_narrative()
    out, src = vt.write_narrative(db, school_id=1, lang="hi", report=REPORT)
    assert src == "ai" and out["narrative"]["teacher_en"].startswith("Highest stage")
    sent = fake_claude["calls"][-1]["user"]
    assert "session_id" not in sent and "{name}" not in sent
    for bad in (
        {"teacher_en": "Confuses 'ब' with 'व' and 20 items right."},   # invented sound
        {"teacher_hi": "बच्चे ने 95 सवाल सही किए। अच्छा।"},             # invented number
        {"parent_en": "Your child, {name}, is doing well. Good. Keep going."},
        {"parent_hi": "Your child did well today. Good work. Keep it up."},  # wrong language
    ):
        fake_claude["payload"] = _ai_narrative(**bad)
        out, src = vt.write_narrative(db, school_id=1, lang="hi", report=REPORT)
        assert src == "fallback", bad
