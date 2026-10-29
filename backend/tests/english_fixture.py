"""A stand-in for the English content (docs/english_subject_contract.md) so the backend can be built and
tested before the Content agent's files are merged.

`build_content_dir(dest)` links `content/` into `dest` and overlays a minimal English layer on the reviewed
files: the 16 `E.G*` nodes, 9 `act_en_*` activities, 5 probes, the English level-check ladder, tips and
`checkpoint_id`s on the English voice-bank items. Nothing under `content/` is touched.

    CONTENT_DIR=/tmp/eng_content python -m tests.english_fixture /tmp/eng_content   # then run pytest

The real files, once merged, replace all of it: tests that need English content skip when the real or
fixture English nodes are missing (see `tests/conftest.py::needs_english`).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[2] / "content"

# id, grade, chapter, title_en, title_hi, prereqs, misconceptions
NODES = [
    ("E.G1.letter_names", 1, "Letters and sounds", "Letter names A-Z", "अक्षरों के नाम A-Z", [],
     ["confuses_b_d", "confuses_p_q"]),
    ("E.G1.letter_sounds", 1, "Letters and sounds", "Letter sounds", "अक्षरों की ध्वनियाँ", ["E.G1.letter_names"],
     ["says_letter_name_not_sound", "confuses_b_d"]),
    ("E.G1.oral_vocab", 1, "Speaking", "Naming common things", "आम चीज़ों के नाम बताना", [], []),
    ("E.G1.build_cvc", 1, "Words", "Joining sounds into 3-letter words", "तीन अक्षर के शब्द जोड़ना",
     ["E.G1.letter_sounds"], ["says_letter_name_not_sound", "guesses_from_first_letter"]),
    ("E.G1.read_cvc", 1, "Words", "Reading 3-letter words", "तीन अक्षर के शब्द पढ़ना", ["E.G1.build_cvc"],
     ["guesses_from_first_letter", "confuses_b_d"]),
    ("E.G1.sight_words", 1, "Words", "Common words (is, the, my)", "आम शब्द (is, the, my)", ["E.G1.read_cvc"],
     ["skips_small_words"]),
    ("E.G1.read_short_sent", 1, "Sentences", "Reading short sentences", "छोटे वाक्य पढ़ना", ["E.G1.read_cvc"],
     ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G2.blends_digraphs", 2, "Words", "Blends and digraphs (sh, ch, th)", "ब्लेंड और डाइग्राफ़ (sh, ch, th)",
     ["E.G1.read_cvc"], ["guesses_from_first_letter", "skips_small_words"]),
    ("E.G2.spell_words", 2, "Words", "Spelling 4-5 letter words", "4-5 अक्षर के शब्द लिखना", ["E.G1.build_cvc"],
     ["says_letter_name_not_sound", "confuses_b_d"]),
    ("E.G2.read_sentences", 2, "Sentences", "Reading sentences smoothly", "वाक्य रवानी से पढ़ना",
     ["E.G1.read_short_sent"], ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G2.make_sentence", 2, "Sentences", "Making a sentence from words", "शब्दों से वाक्य बनाना",
     ["E.G1.read_short_sent", "E.G1.oral_vocab"], ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G2.simple_comp", 2, "Reading", "Answering questions about a text", "पाठ पर सवालों के जवाब",
     ["E.G2.read_sentences"], ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G3.read_passage", 3, "Reading", "Reading a short passage", "छोटा गद्यांश पढ़ना", ["E.G2.read_sentences"],
     ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G3.sentence_formation", 3, "Sentences", "Forming sentences", "वाक्य बनाना", ["E.G2.make_sentence"],
     ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G3.word_types", 3, "Grammar", "Naming, doing, describing words", "संज्ञा, क्रिया, विशेषण शब्द",
     ["E.G2.make_sentence"], ["skips_small_words", "guesses_from_first_letter"]),
    ("E.G3.story_comp", 3, "Reading", "Understanding and retelling a story", "कहानी समझना और सुनाना",
     ["E.G2.simple_comp", "E.G3.read_passage"], ["skips_small_words", "guesses_from_first_letter"]),
]

# id -> (checkpoints, title, steps)
ACTIVITIES = {
    "act_en_sound_hunt": (["E.G1.letter_sounds"], "Sound hunt", ["Say a sound.", "Children find things with it."]),
    "act_en_sound_cards": (["E.G1.letter_sounds", "E.G1.letter_names"], "Sound cards", ["Show a card.", "Say its sound."]),
    "act_en_blend_cat": (["E.G1.build_cvc"], "Blend c-a-t", ["Say c, a, t slowly.", "Blend them: cat."]),
    "act_en_read_cvc": (["E.G1.read_cvc"], "Read the word cards", ["Show a card.", "Children read it."]),
    "act_en_short_sent": (["E.G1.read_short_sent"], "Read a sentence together", ["Point and read.", "Echo read."]),
    "act_en_blends": (["E.G2.blends_digraphs"], "sh and ch words", ["Say sh.", "Sort words by sh/ch."]),
    "act_en_make_sent": (["E.G2.make_sentence"], "Build a sentence", ["Give three words.", "Say a sentence."]),
    "act_en_sentence3": (["E.G3.sentence_formation", "E.G3.word_types"], "Sentence builders", ["Pick words.", "Write."]),
    "act_en_passage": (["E.G3.read_passage", "E.G3.story_comp"], "Read and retell", ["Read a passage.", "Retell it."]),
}
PROBED = ["E.G1.letter_names", "E.G1.letter_sounds", "E.G1.read_cvc", "E.G1.read_short_sent", "E.G2.make_sentence"]
LADDER = [("letter", "E.G1.letter_names", "Letters", "अक्षर"), ("word", "E.G1.read_cvc", "Words", "शब्द"),
          ("sentence", "E.G1.read_short_sent", "Sentences", "वाक्य"),
          ("story", "E.G2.read_sentences", "Short story", "छोटी कहानी")]
LADDER_ITEMS = {"letter": ["a", "m", "s", "t", "p"], "word": ["cat", "sun", "pen", "dog", "hat"],
                "sentence": ["I can run.", "The cat is big.", "We like to play."],
                "story": ["The sun is hot. We sit under a tree."]}
# voice-bank stage/kind -> checkpoint (the contract's stage mapping)
BANK_CP = {("letter", "read_letter"): {1: "E.G1.letter_names"}, ("letter", "say_sound"): {1: "E.G1.letter_sounds"},
           ("word_build", None): {1: "E.G1.build_cvc", 2: "E.G2.spell_words"},
           ("word_read", None): {1: "E.G1.read_cvc", 2: "E.G2.blends_digraphs"},
           ("sentence_build", None): {1: "E.G2.make_sentence", 2: "E.G2.make_sentence", 3: "E.G3.sentence_formation"},
           ("reading", None): {1: "E.G1.read_short_sent", 2: "E.G2.read_sentences", 3: "E.G3.read_passage"}}


def _bank_cp(item: dict) -> str | None:
    by_grade = BANK_CP.get((item["stage"], item["kind"])) or BANK_CP.get((item["stage"], None))
    if not by_grade:
        return None
    g = max(1, min(int(item.get("grade") or 1), 3))
    return by_grade.get(g) or by_grade[max(by_grade)]


def _tip(mid: str) -> dict:
    cps = [n[0] for n in NODES if mid in n[6]]
    return {"id": mid, "checkpoint_ids": cps, "explain_hi": "समझाइए", "explain_en": f"About {mid}.",
            "game_hi": "खेल", "game_en": f"A game for {mid}.", "example": "b / d", "reviewed": True}


def build_content_dir(dest: Path) -> Path:
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for p in CONTENT.iterdir():
        (dest / p.name).symlink_to(p)

    def rewrite(name: str, fn) -> None:
        (dest / name).unlink()
        data = json.loads((CONTENT / name).read_text(encoding="utf-8"))
        fn(data)
        (dest / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def graph(d):
        for id_, grade, chapter, en, hi, pre, mis in NODES:
            d["nodes"].append({"id": id_, "subject": "english", "grade": grade, "domain": "english",
                               "chapter": chapter, "title_hi": hi, "title_en": en, "assess_via": ["teacher_tap", "class_voice"],
                               "item_types": ["oral_answer"], "misconceptions": mis, "prereqs": pre,
                               "nipun_ref": "English FLN", "language": "en"})

    def acts(d):
        for id_, (cps, title, steps) in ACTIVITIES.items():
            d["activities"].append({"id": id_, "checkpoint_ids": cps, "mode": "group", "title_hi": title,
                                    "materials_hi": "none", "steps_hi": steps, "duration_min": 8,
                                    "blackboard_hi": "", "reassessment": {"ask_hi": "Say it again.", "expected": ""},
                                    "source_doc": "test fixture", "reviewed": True, "language": "en"})

    def probes(d):
        for cp in PROBED:
            d["probes"].append({"checkpoint_id": cp, "kind": "misconception_check", "title_hi": f"Check {cp}",
                                "items": [{"ask_hi": "Say it.", "expect": "x"}], "pass_rule": "2/2",
                                "tell_hi": "2/2 good."})

    def ladder(d):
        d["subjects"]["english"] = {
            "title_en": "English reading level", "title_hi": "अंग्रेज़ी पढ़ने का स्तर",
            "beginner": {"key": "beginner", "title_en": "Beginner (not yet letters)", "title_hi": "शुरुआत (अक्षर अभी नहीं)"},
            "levels": [{"key": k, "title_en": en, "title_hi": hi, "checkpoint_id": cp, "ask_en": f"Read each {k}.",
                        "ask_hi": f"हर {hi} पढ़वाएँ।", "items": [{"show": s} for s in LADDER_ITEMS[k]],
                        "pass_min": len(LADDER_ITEMS[k]) - 1 if k != "story" else 1, "of": len(LADDER_ITEMS[k])}
                       for k, cp, en, hi in LADDER]}

    def bank(d):
        for it in d["items"]:
            if it.get("lang") == "en":
                it["checkpoint_id"] = _bank_cp(it)

    def tips(d):
        have = {t["id"] for t in d["tips"]}
        for n in NODES:
            for m in n[6]:
                if m not in have:
                    have.add(m)
                    d["tips"].append(_tip(m))

    def home(d):
        for id_ in ACTIVITIES:
            d["activities"].append({"id": id_, "title_hi": "घर पर", "title_en": "At home", "materials_hi": "कुछ नहीं",
                                    "materials_en": "none", "steps_hi": ["बोलिए"], "steps_en": ["say it"], "minutes": 5})

    rewrite("competency_graph.json", graph)
    rewrite("activities.json", acts)
    rewrite("probes.json", probes)
    rewrite("level_check.json", ladder)
    rewrite("voice_bank.json", bank)
    rewrite("misconception_tips.json", tips)
    rewrite("activity_home.json", home)
    return dest


if __name__ == "__main__":
    print(build_content_dir(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/eng_content")))
