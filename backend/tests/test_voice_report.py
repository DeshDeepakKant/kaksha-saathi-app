"""Deterministic end-of-session report (app/services/voice_report.py)."""
import json
from datetime import datetime, timedelta

import pytest

from app.services.content import get_content
from app.services.voice_report import build_report
from app.speech.assess import assess_item

T0 = datetime(2026, 10, 29, 10, 0, 0)
PARA = "राम और श्याम बाज़ार गए। उन्होंने आम और केले खरीदे।"

ITEMS = {
    "L1": {"id": "L1", "stage": "letter", "kind": "read_letter", "lang": "hi",
           "checkpoint_id": "L.G1.vyanjan", "target": "क", "display": {"text": "क"}},
    "L2": {"id": "L2", "stage": "letter", "kind": "read_letter", "lang": "hi",
           "checkpoint_id": "L.G1.vyanjan", "target": "श", "display": {"text": "श"}},
    "L3": {"id": "L3", "stage": "letter", "kind": "read_letter", "lang": "hi",
           "checkpoint_id": "L.G1.swar", "target": "आ", "display": {"text": "आ"}},
    "B1": {"id": "B1", "stage": "word_build", "kind": "build_word", "lang": "hi",
           "checkpoint_id": "L.G1.blend_no_matra", "target": "कमल", "display": {"tiles": ["क", "म", "ल"]}},
    "B2": {"id": "B2", "stage": "word_build", "kind": "build_word", "lang": "hi",
           "checkpoint_id": "L.G1.blend_no_matra", "target": "शेर", "display": {"tiles": ["शे", "र"]}},
    "W1": {"id": "W1", "stage": "word_read", "kind": "read_word", "lang": "hi",
           "checkpoint_id": "L.G1.read_matra_words", "target": "मीना", "display": {"text": "मीना"}},
    "W2": {"id": "W2", "stage": "word_read", "kind": "read_word", "lang": "hi",
           "checkpoint_id": "L.G1.read_matra_words", "target": "पानी", "display": {"text": "पानी"}},
    "W3": {"id": "W3", "stage": "word_read", "kind": "read_word", "lang": "hi",
           "checkpoint_id": "L.G1.read_matra_words", "target": "किताब", "display": {"text": "किताब"}},
    "W4": {"id": "W4", "stage": "word_read", "kind": "read_word", "lang": "hi",
           "checkpoint_id": "L.G1.read_matra_words", "target": "घर", "display": {"text": "घर"}},
    "S1": {"id": "S1", "stage": "sentence_build", "kind": "make_sentence", "lang": "hi",
           "checkpoint_id": "L.G3.sentence_formation", "target": None,
           "required_words": ["गाय", "घास"], "display": {"words": ["गाय", "घास"]}},
    "R1": {"id": "R1", "stage": "reading", "kind": "read_paragraph", "lang": "hi",
           "checkpoint_id": "L.G2.fluency_45_60", "target": PARA, "display": {"text": PARA}},
    "Q1": {"id": "Q1", "stage": "reading", "kind": "answer_question", "lang": "hi",
           "checkpoint_id": "L.G2.comprehension_literal", "target": None,
           "keywords": ["आम", "केले"], "display": {"question": "उन्होंने क्या खरीदा?"}},
}

# (item_id, transcript, duration_s) in the order the child spoke; None transcript = skip.
SCRIPT = [
    ("L1", "क", 2),
    ("L2", "स", 2), ("L2", "स", 2), ("L2", "श", 2),            # श → स twice, then right
    ("L3", "", 3), ("L3", "आ", 2),                              # silent turn uses no try
    ("B1", "क म ल", 4), ("B1", "कमल", 3),                       # sounds, then blended
    *[("B2", "सेर", 3)] * 5,                                     # never got श
    *[("W1", "मिना", 3)] * 5,                                    # ी read as ि every time
    ("W2", "पानी", 2),
    ("W3", "कताब", 3), ("W3", None, 0),                          # one try, then skipped
    ("W4", None, 0),                                             # skipped without a try
    ("S1", "गाय दूध देती है", 5), ("S1", "गाय घास खाती है", 5),
    ("R1", "राम श्याम बाजार गए उन्होंने आम केले खरीदे", 16),     # 8/10 (both और missed) = 30 wcpm
    ("R1", PARA, 15),                                            # 10/10 in 15 s = 40 wcpm
    ("Q1", "आम और केले", 4),
]


def make_turns() -> list[dict]:
    turns, attempts = [], {}
    for n, (iid, heard, dur) in enumerate(SCRIPT):
        item = ITEMS[iid]
        at = (T0 + timedelta(seconds=60 * n)).isoformat()
        base = {"item_id": iid, "stage": item["stage"], "kind": item["kind"], "at": at}
        if heard is None:
            turns.append({**base, "attempt": attempts.get(iid, 0), "verdict": None, "heard": "",
                          "errors": [], "words": [], "skipped": True})
            continue
        a = assess_item(item, heard, duration_s=dur)
        if a.verdict != "silent":
            attempts[iid] = attempts.get(iid, 0) + 1
        turns.append({**base, "attempt": attempts.get(iid, 0), "verdict": a.verdict, "heard": a.heard,
                      "errors": a.errors, "words": a.words, "silent": a.verdict == "silent",
                      "fluency": a.fluency})
    return turns


@pytest.fixture(scope="module")
def report():
    return build_report(lang="hi", started_at=T0, ended_at=T0 + timedelta(minutes=30),
                        turns=make_turns(), items=ITEMS, content=get_content(), session_id="vs1")


def test_script_verdicts_are_what_the_session_assumes():
    v = [(t["item_id"], t["verdict"]) for t in make_turns()]
    assert v[1:4] == [("L2", "wrong"), ("L2", "wrong"), ("L2", "correct")]
    assert v[4] == ("L3", "silent")
    assert v[6] == ("B1", "close")
    assert v[-3:] == [("R1", "close"), ("R1", "correct"), ("Q1", "correct")]


def test_schema_keys(report):
    assert set(report) == {
        "session_id", "lang", "minutes", "items_attempted", "first_try", "after_retry", "failed",
        "skipped", "accuracy", "highest_stage", "stages", "strengths", "weaknesses", "mistakes",
        "difficult_words", "difficult_sounds", "topics_attention", "fluency", "narrative",
        "narrative_status", "next_steps"}
    assert report["narrative"] == {"parent_hi": "", "parent_en": "", "teacher_en": "", "teacher_hi": ""}
    assert report["narrative_status"] == "fallback"
    assert report["next_steps"] == {"hi": [], "en": []}
    json.dumps(report, ensure_ascii=False)          # serialisable as-is


def test_counts(report):
    assert report["session_id"] == "vs1" and report["lang"] == "hi"
    assert report["minutes"] == 30.0
    assert report["items_attempted"] == 11           # W4 was skipped without trying
    assert report["first_try"] == 4                  # L1, L3 (silent turn ignored), W2, Q1
    assert report["after_retry"] == 4                # L2, B1, S1, R1
    assert report["failed"] == 2                     # B2, W1
    assert report["skipped"] == 2                    # W3, W4
    assert report["accuracy"] == round(8 / 11, 3)
    assert report["highest_stage"] == "reading"


def test_stages(report):
    assert report["stages"] == [
        {"stage": "letter", "attempted": 3, "correct": 3, "failed": 0},
        {"stage": "word_build", "attempted": 2, "correct": 1, "failed": 1},
        {"stage": "word_read", "attempted": 3, "correct": 1, "failed": 1},
        {"stage": "sentence_build", "attempted": 1, "correct": 1, "failed": 0},
        {"stage": "reading", "attempted": 2, "correct": 2, "failed": 0},
    ]


def test_mistakes(report):
    m = {x["item"]: x for x in report["mistakes"]}
    assert list(m) == ["श", "कमल", "शेर", "मीना", "गाय, घास", PARA]
    assert m["श"]["attempts"] == 3 and m["श"]["solved"] and m["श"]["errors"] == ["श → स"]
    assert m["शेर"] == {**m["शेर"], "stage": "word_build", "heard": "सेर", "attempts": 5,
                        "solved": False, "errors": ["श → स in शेर"]}
    assert m["मीना"]["errors"] == ["ी matra read as ि in मीना"]
    assert m["मीना"]["errors_hi"] == ["ी की मात्रा को ि पढ़ा (मीना में)"]
    assert m["कमल"]["errors"] == ["said the sounds separately (क म ल) instead of कमल"]
    assert m["गाय, घास"]["errors"] == ["missed word: घास"]
    assert m[PARA]["errors"] == ["missed word: और"] and m[PARA]["attempts"] == 2


def test_difficult_words_and_sounds(report):
    assert report["difficult_words"] == ["शेर", "मीना"]
    assert report["difficult_sounds"] == [
        {"sound": "श", "confused_with": "स", "count": 7},     # 2 letter turns + 5 word-build turns
        {"sound": "ी", "confused_with": "ि", "count": 5},
        {"sound": "ि", "confused_with": "", "count": 1},      # किताब read as कताब (then skipped)
    ]


def test_topics_attention_titles_from_content(report):
    t = report["topics_attention"]
    assert [x["checkpoint_id"] for x in t] == ["L.G1.blend_no_matra", "L.G1.read_matra_words", "L.G1.vyanjan"]
    cps = get_content().checkpoints
    for x in t:
        assert x["title_hi"] == cps[x["checkpoint_id"]].title_hi
        assert x["title_en"] == cps[x["checkpoint_id"]].title_en
    assert t[0]["reason_en"] == "Not solved after 5 tries: शेर"
    assert t[0]["reason_hi"] == "5 कोशिशों में नहीं हुआ: शेर"
    assert t[2]["reason_en"] == "Needed 3+ tries: श"


def test_fluency(report):
    assert report["fluency"] == {"wcpm": 40.0, "paragraphs": 1, "best_wcpm": 40.0}


def test_strengths_and_weaknesses_from_numbers(report):
    s_en = [b["en"] for b in report["strengths"]]
    w_en = [b["en"] for b in report["weaknesses"]]
    assert s_en == ["Letters: all 3 correct", "Reading: all 2 correct"]
    assert "Building words: 1 of 2 not solved after 5 tries" in w_en
    assert "Reading speed 40 correct words per minute (class 2 goal 45–60)" in w_en
    assert "Said स instead of श (7 times)" in w_en
    assert "Read the ी matra as ि (5 times)" in w_en
    assert "Skipped words while reading or speaking (3 words)" in w_en   # घास + और twice
    assert len(w_en) == 5                                                 # capped list
    for b in report["strengths"] + report["weaknesses"]:
        assert b["en"] and b["hi"]


def test_deterministic_and_input_order_of_items_irrelevant():
    turns = make_turns()
    a = build_report(lang="hi", started_at=T0.isoformat(), ended_at=(T0 + timedelta(minutes=30)).isoformat(),
                     turns=turns, items=ITEMS, content=get_content())
    shuffled = dict(reversed(list(ITEMS.items())))
    b = build_report(lang="hi", started_at=T0, ended_at=T0 + timedelta(minutes=30),
                     turns=make_turns(), items=shuffled, content=get_content())
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def test_dict_content_and_unknown_checkpoint():
    content = {"checkpoints": {"L.G1.blend_no_matra": {"title_hi": "जोड़ना", "title_en": "Blending"}}}
    r = build_report(lang="hi", started_at=T0, ended_at=T0, turns=make_turns(), items=ITEMS, content=content)
    t = {x["checkpoint_id"]: x for x in r["topics_attention"]}
    assert t["L.G1.blend_no_matra"]["title_en"] == "Blending"
    assert t["L.G1.vyanjan"]["title_en"] == "L.G1.vyanjan"     # no title known: id, never invented
    assert r["minutes"] == 0.0


def test_empty_session():
    r = build_report(lang="en", started_at=T0, ended_at=T0 + timedelta(minutes=2), turns=[], items={},
                     content=None)
    assert r["items_attempted"] == 0 and r["accuracy"] == 0.0 and r["highest_stage"] is None
    assert r["stages"] == [] and r["mistakes"] == [] and r["difficult_sounds"] == []
    assert r["fluency"] == {"wcpm": None, "paragraphs": 0, "best_wcpm": None}
    assert r["strengths"] == [] and r["weaknesses"] == [] and r["minutes"] == 2.0


def test_only_silent_turns_count_nothing():
    turns = [{"item_id": "L1", "stage": "letter", "kind": "read_letter", "verdict": "silent",
              "silent": True, "attempt": 0, "heard": "", "errors": [], "words": []}] * 3
    r = build_report(lang="hi", started_at=T0, ended_at=T0, turns=turns, items=ITEMS, content=None)
    assert r["items_attempted"] == 0 and r["skipped"] == 0 and r["difficult_sounds"] == []


def test_correct_on_first_try_after_engine_numbering():
    # An item correct on its first judged try is first_try even if earlier silent turns exist.
    turns = [{"item_id": "W2", "verdict": "silent", "silent": True, "attempt": 0},
             {"item_id": "W2", "verdict": "correct", "attempt": 1, "heard": "पानी"}]
    r = build_report(lang="hi", started_at=T0, ended_at=T0, turns=turns, items=ITEMS, content=None)
    assert (r["first_try"], r["after_retry"], r["items_attempted"]) == (1, 0, 1)


def test_engine_shape_transcript_lines_plus_item_attempts():
    # The engine may pass transcript lines (tutor lines included, no errors) and keep the judged
    # tries on each item as `attempts`; the report must read the same facts from that shape.
    turns = make_turns()
    items = {iid: dict(it) for iid, it in ITEMS.items()}
    lines = []
    for t in turns:
        lines.append({"role": "tutor", "text": "...", "at": t["at"], "item_id": t["item_id"]})
        lines.append({"role": "child", "text": t["heard"], "at": t["at"], "item_id": t["item_id"],
                      **({"verdict": "skipped"} if t.get("skipped") else
                         {"verdict": t["verdict"], "words": t["words"]} if t["verdict"] else {})})
        if t["verdict"] in ("correct", "close", "wrong"):
            items[t["item_id"]].setdefault("attempts", []).append(
                {k: t[k] for k in ("attempt", "verdict", "heard", "errors", "words", "fluency")})
    r = build_report(lang="hi", started_at=T0, ended_at=T0 + timedelta(minutes=30), turns=lines,
                     items=items, content=get_content(), session_id="vs1")
    base = build_report(lang="hi", started_at=T0, ended_at=T0 + timedelta(minutes=30), turns=turns,
                        items=ITEMS, content=get_content(), session_id="vs1")
    assert r == base
