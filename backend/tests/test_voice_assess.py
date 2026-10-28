"""Deterministic judging of spoken answers in the voice session (app/speech/assess.py)."""
import pytest

from app.services.voice_types import VERDICTS, Assessment
from app.speech.assess import (aksharas, assess_answer, assess_item, assess_reading,
                               assess_sentence_build, assess_word_build, describe_error)


def errs(a: Assessment, kind: str | None = None) -> list[tuple]:
    return [(e["type"], e["target"], e["heard"]) for e in a.errors if kind is None or e["type"] == kind]


# --------------------------------------------------------------------------- silence

@pytest.mark.parametrize("heard", ["", "   ", "[noise]", "<unk>", "हम्म", "...", "um uh", "।"])
def test_empty_or_noise_is_silent(heard):
    for a in (assess_reading("कमल", heard, "hi"), assess_reading("क", heard, "hi"),
              assess_word_build("कमल", heard, "hi"), assess_sentence_build(["गाय"], heard, "hi"),
              assess_answer(["दूध"], heard, "hi"), assess_reading("cat", heard, "en")):
        assert a.verdict == "silent" and a.score == 0.0 and a.heard == ""


def test_filler_that_is_the_target_is_kept():
    assert assess_reading("ओ", "ओ", "hi").verdict == "correct"
    assert assess_reading("u", "uh", "en").verdict == "correct"


# --------------------------------------------------------------------------- aksharas

def test_akshara_segmentation():
    assert aksharas("क्षत्रिय") == ["क्ष", "त्रि", "य"]
    assert aksharas("ज़िंदगी") == ["ज़िं", "द", "गी"]
    assert aksharas("मीना") == ["मी", "ना"]
    assert aksharas("आम") == ["आ", "म"]


# --------------------------------------------------------------------------- Hindi letters

@pytest.mark.parametrize("heard", ["क", "का", "कः", "के", "क से कमल", "क।"])
def test_letter_name_variants_correct(heard):
    a = assess_reading("क", heard, "hi")
    assert a.verdict == "correct" and a.score == 1.0


@pytest.mark.parametrize("heard", ["कमल", "किताब", "कबूतर"])
def test_word_starting_with_letter_is_close(heard):
    a = assess_reading("क", heard, "hi")
    assert a.verdict == "close"
    assert a.words[0]["heard"] == heard


def test_confusable_letter_is_wrong_with_substitution():
    a = assess_reading("श", "स", "hi")
    assert a.verdict == "wrong"
    assert errs(a) == [("substitution", "श", "स")]
    b = assess_reading("क", "खरगोश", "hi")
    assert b.verdict == "wrong" and errs(b) == [("substitution", "क", "ख")]


def test_vowel_letters():
    assert assess_reading("आ", "आ", "hi").verdict == "correct"
    assert assess_reading("आ", "आम", "hi").verdict == "close"
    a = assess_reading("ई", "इ", "hi")
    assert a.verdict == "wrong" and errs(a) == [("substitution", "ई", "इ")]


def test_nukta_letter_without_nukta_is_close():
    a = assess_reading("ड़", "ड", "hi")
    assert a.verdict == "close" and errs(a)[0][0] == "substitution"


def test_read_letter_item_with_accept():
    item = {"id": "x", "kind": "say_sound", "lang": "hi", "target": "म", "accept": ["मछली"]}
    assert assess_item(item, "मछली").verdict == "correct"
    assert assess_item(item, "मोर").verdict == "close"


# --------------------------------------------------------------------------- Hindi words

def test_exact_word_correct():
    a = assess_reading("कमल", "कमल", "hi")
    assert a.verdict == "correct" and a.score == 1.0 and a.errors == []
    assert a.words == [{"target": "कमल", "heard": "कमल", "status": "correct"}]


def test_consonant_substitution_pinpointed():
    a = assess_reading("शेर", "सेर", "hi")
    assert a.verdict == "close"
    assert a.errors == [{"type": "substitution", "target": "श", "heard": "स", "word": "शेर"}]
    assert "शेर" in a.notes            # reuses scorer's Hindi diff note


def test_matra_error_pinpointed():
    a = assess_reading("मीना", "मिना", "hi")
    assert a.verdict == "close"
    assert a.errors == [{"type": "matra", "target": "ी", "heard": "ि", "word": "मीना"}]


def test_missing_matra():
    a = assess_reading("मीना", "मना", "hi")
    assert a.verdict == "close" and errs(a) == [("matra", "ी", "")]
    b = assess_reading("किताब", "कताब", "hi")
    assert b.verdict == "close" and errs(b) == [("matra", "ि", "")]


def test_akshara_omission_and_insertion():
    a = assess_reading("बकरी", "बरी", "hi")
    assert ("omission", "क", "") in errs(a) and a.verdict == "close"
    b = assess_reading("घर", "घरर", "hi")
    assert ("insertion", "", "र") in errs(b)


def test_order_swap():
    a = assess_reading("कमल", "कलम", "hi")
    assert a.verdict == "close" and errs(a) == [("order", "कमल", "कलम")]


def test_different_word_is_wrong():
    a = assess_reading("कमल", "घर", "hi")
    assert a.verdict == "wrong" and a.score < 0.6


@pytest.mark.parametrize("target,heard", [
    ("बाज़ार", "बाजार"), ("ज़मीन", "जमीन"), ("फ़ल", "फल"),          # Urdu nukta spelling noise
    ("चाँद", "चांद"), ("पन्द्रह", "पंद्रह"),                          # chandrabindu / half nasal
    ("गयी", "गई"), ("लिये", "लिए"),                                # य-spellings
])
def test_asr_spelling_noise_is_correct(target, heard):
    assert assess_reading(target, heard, "hi").verdict == "correct"
    assert assess_reading(heard, target, "hi").verdict == "correct"


def test_retroflex_flap_nukta_is_close_not_wrong():
    a = assess_reading("पेड़", "पेड", "hi")
    assert a.verdict == "close" and errs(a) == [("substitution", "ड़", "ड")]


def test_word_found_among_extra_speech():
    assert assess_reading("कमल", "यह कमल है", "hi").verdict == "correct"


def test_unicode_nfc_input():
    decomposed = "क़लम"           # क + nukta written as two code points
    assert assess_reading("क़लम", decomposed, "hi").verdict == "correct"


def test_reading_word_as_separate_sounds_is_close():
    a = assess_reading("घर", "घ र", "hi")
    assert a.verdict == "close" and errs(a)[0][0] == "not_blended"


# --------------------------------------------------------------------------- English

@pytest.mark.parametrize("heard", ["b", "B", "bee", "buh", "B.", "b for ball", "letter b"])
def test_english_letter_variants(heard):
    assert assess_reading("b", heard, "en").verdict == "correct"


def test_english_letter_word_start_close_and_wrong_letter():
    assert assess_reading("b", "ball", "en").verdict == "close"
    a = assess_reading("b", "dee", "en")
    assert a.verdict == "wrong" and errs(a) == [("substitution", "b", "d")]


def test_english_case_and_punctuation():
    a = assess_reading("Cat", "CAT!", "en")
    assert a.verdict == "correct" and a.heard == "cat"
    assert assess_reading("don't", "dont", "en").verdict == "correct"


def test_english_letter_substitution_and_missing_letter():
    a = assess_reading("cat", "cot", "en")
    assert a.verdict == "close" and errs(a) == [("substitution", "a", "o")]
    b = assess_reading("frog", "fog", "en")
    assert b.verdict == "close" and errs(b) == [("omission", "r", "")]


@pytest.mark.parametrize("target,heard", [("two", "to"), ("too", "two"), ("write", "right"),
                                          ("sea", "see"), ("four", "for")])
def test_english_homophones_not_penalised(target, heard):
    # Identical audio: the recogniser cannot tell them apart, so it must not fail the child.
    assert assess_reading(target, heard, "en").verdict == "correct"


def test_english_wrong_word():
    assert assess_reading("cat", "elephant", "en").verdict == "wrong"


# --------------------------------------------------------------------------- word building

def test_word_build_blended_correct():
    assert assess_word_build("कमल", "कमल", "hi").verdict == "correct"


@pytest.mark.parametrize("heard", ["क म ल", "का मा ला"])
def test_word_build_separate_sounds_is_close(heard):
    a = assess_word_build("कमल", heard, "hi")
    assert a.verdict == "close"
    assert a.errors[0]["type"] == "not_blended" and a.errors[0]["target"] == "कमल"
    assert "separately" in describe_error(a.errors[0])[0]


def test_word_build_sounds_then_word_is_correct():
    assert assess_word_build("कमल", "क म ल कमल", "hi").verdict == "correct"


def test_word_build_accept_list_and_wrong_blend():
    assert assess_word_build("नल", "नल", "hi", accept=["नल्"]).verdict == "correct"
    assert assess_word_build("मटर", "मकर", "hi", accept=["मटर"]).verdict == "close"
    assert assess_word_build("मटर", "गाय", "hi").verdict == "wrong"


def test_word_build_english():
    assert assess_word_build("cat", "cat", "en").verdict == "correct"
    a = assess_word_build("cat", "c a t", "en")
    assert a.verdict == "close" and a.errors[0]["type"] == "not_blended"
    assert assess_word_build("cat", "see ay tee", "en").verdict == "close"


def test_word_build_item_uses_tiles_when_no_target():
    item = {"id": "b1", "kind": "build_word", "lang": "hi", "display": {"tiles": ["ज", "ल"]}}
    assert assess_item(item, "जल").verdict == "correct"


# --------------------------------------------------------------------------- sentence building

def test_sentence_with_all_words_correct():
    a = assess_sentence_build(["गाय", "घास"], "गाय घास खाती है", "hi")
    assert a.verdict == "correct" and a.errors == []


def test_sentence_only_listing_words_is_close():
    a = assess_sentence_build(["गाय", "घास"], "गाय घास", "hi")
    assert a.verdict == "close" and errs(a, "not_a_sentence")
    b = assess_sentence_build(["लड़का", "गेंद", "खेलता"], "लड़का गेंद खेलता", "hi")
    assert b.verdict == "close"


def test_sentence_missing_word_close():
    a = assess_sentence_build(["गाय", "घास"], "गाय दूध देती है", "hi")
    assert a.verdict == "close"
    assert errs(a) == [("missing_word", "घास", "")]


def test_sentence_without_required_words_wrong():
    a = assess_sentence_build(["गाय", "घास"], "मैं स्कूल जाता हूँ", "hi")
    assert a.verdict == "wrong" and len(errs(a, "missing_word")) == 2


def test_sentence_inflection_and_matra_variants_allowed():
    assert assess_sentence_build(["लड़का", "खाना"], "लड़के ने खाना खाया", "hi").verdict == "correct"
    assert assess_sentence_build(["खाना", "आम"], "मैं आम खाती हूँ", "hi").verdict == "correct"
    assert assess_sentence_build(["dog", "run"], "the dog is running", "en").verdict == "correct"
    assert assess_sentence_build(["make", "cake"], "we are making a cake", "en").verdict == "correct"


def test_make_sentence_item_dispatch():
    item = {"id": "s1", "kind": "make_sentence", "lang": "hi", "target": None,
            "display": {"words": ["बिल्ली", "दूध"]}, "required_words": ["बिल्ली", "दूध"]}
    assert assess_item(item, "बिल्ली दूध पीती है").verdict == "correct"


# --------------------------------------------------------------------------- answers

def test_answer_keywords():
    assert assess_answer(["बिल्ली", "दूध"], "बिल्ली ने दूध पिया", "hi").verdict == "correct"
    assert assess_answer(["red", "ball", "park"], "a red ball", "en").verdict == "correct"
    a = assess_answer(["red", "ball", "park"], "a red one", "en")
    assert a.verdict == "close" and len(errs(a, "missing_word")) == 2
    assert assess_answer(["बिल्ली", "दूध"], "पता नहीं", "hi").verdict == "wrong"


def test_answer_accept_phrase():
    a = assess_answer([], "वह पेड़ पर बैठी थी", "hi", accept=["पेड़ पर"])
    assert a.verdict == "correct"


def test_answer_item_target_counts_as_accept():
    item = {"id": "q1", "kind": "answer_question", "lang": "en", "target": "the park",
            "keywords": ["park"], "accept": []}
    assert assess_item(item, "they went to the park").verdict == "correct"


# --------------------------------------------------------------------------- sentences / paragraphs

def test_sentence_reading_all_correct():
    a = assess_reading("राम घर गया", "राम घर गया।", "hi")
    assert a.verdict == "correct" and [w["status"] for w in a.words] == ["correct"] * 3


def test_paragraph_missed_words_and_wcpm():
    target = "मीना बाज़ार गई। उसने लाल सेब और केले खरीदे। फिर वह घर लौट आई।"
    heard = "मीना बाजार गई उसने लाल सेब केले खरीदे फिर वह घर आई"
    a = assess_reading(target, heard, "hi", duration_s=12)
    statuses = [(w["target"], w["status"]) for w in a.words]
    assert ("और", "missed") in statuses and ("लौट", "missed") in statuses
    assert ("बाज़ार", "correct") in statuses            # nukta spelling noise
    assert errs(a, "missing_word") == [("missing_word", "और", ""), ("missing_word", "लौट", "")]
    assert a.fluency == {"wcpm": 60.0, "duration_s": 12.0}   # 12 correct words in 12 s
    assert a.verdict == "close" and a.score == pytest.approx(12 / 14, abs=1e-3)


def test_paragraph_tolerates_repeats_and_misread_word():
    a = assess_reading("राम घर गया और खाना खाया", "राम घर गया गया खाना खाया", "hi")
    by = [(w["target"], w["heard"], w["status"]) for w in a.words]
    assert ("और", "", "missed") in by and ("", "गया", "extra") in by
    b = assess_reading("राम घर गया", "राम पानी गया", "hi")
    assert ("घर", "पानी", "wrong") in [(w["target"], w["heard"], w["status"]) for w in b.words]


def test_paragraph_close_words_report_akshara_errors():
    a = assess_reading("शेर जंगल में रहता है", "सेर जंगल में रहता है", "hi", duration_s=4)
    assert a.verdict == "correct"                          # 4 correct + 1 close of 5 = 0.9
    assert ("substitution", "श", "स") in errs(a)
    assert a.fluency["wcpm"] == 60.0


def test_paragraph_mostly_wrong_is_wrong():
    a = assess_reading("the cat sat on the mat", "a dog ran", "en", duration_s=5)
    assert a.verdict == "wrong" and a.fluency["wcpm"] == 0.0


def test_english_paragraph_wcpm():
    a = assess_reading("The cat sat on the mat.", "the cat sat on mat", "en", duration_s=3)
    assert a.fluency["wcpm"] == 100.0
    assert [w["status"] for w in a.words].count("missed") == 1


def test_paragraph_without_duration_has_no_fluency():
    assert assess_reading("राम घर गया", "राम घर गया", "hi").fluency is None


# --------------------------------------------------------------------------- contract

def test_assess_item_dispatch_and_shape():
    items = [
        {"kind": "read_letter", "lang": "hi", "target": "ग"},
        {"kind": "read_word", "lang": "hi", "display": {"text": "पानी"}},
        {"kind": "read_sentence", "lang": "en", "target": "I can run."},
        {"kind": "read_paragraph", "lang": "en", "target": "A big red bus. It goes fast."},
    ]
    for item, heard in zip(items, ["ग", "पानी", "i can run", "a big red bus it goes fast"]):
        a = assess_item(item, heard, duration_s=5)
        assert a.verdict == "correct", item
        d = a.to_dict()
        assert set(d) >= {"verdict", "score", "heard", "words", "errors", "fluency", "notes", "judged_by"}
        assert d["verdict"] in VERDICTS and 0.0 <= d["score"] <= 1.0 and d["judged_by"] == "code"
        for w in d["words"]:
            assert w["status"] in ("correct", "close", "wrong", "missed", "extra")


def test_deterministic():
    a = assess_reading("मीना बाज़ार गई", "मिना बजार गई", "hi", duration_s=3).to_dict()
    b = assess_reading("मीना बाज़ार गई", "मिना बजार गई", "hi", duration_s=3).to_dict()
    assert a == b


def test_describe_error_strings():
    assert describe_error({"type": "substitution", "target": "श", "heard": "स", "word": "शेर"})[0] == "श → स in शेर"
    assert describe_error({"type": "matra", "target": "ी", "heard": "", "word": "मीना"})[0] == "missing ी matra in मीना"
    assert describe_error({"type": "missing_word", "target": "और", "heard": "", "word": "और"})[1] == "शब्द छूटा: और"


def test_implausible_reading_speed_reports_no_fluency():
    from app.speech.assess import assess_reading
    para = "मीना बाज़ार गई। उसने आम और केले खरीदे। फिर वह घर लौट आई।"
    ok = assess_reading(para, para, "hi", duration_s=12.0)
    assert ok.fluency and 0 < ok.fluency["wcpm"] <= 250
    cut = assess_reading(para, para, "hi", duration_s=1.0)  # 13 words in 1 s: recording cut short
    assert cut.fluency is None and cut.verdict == "correct"
