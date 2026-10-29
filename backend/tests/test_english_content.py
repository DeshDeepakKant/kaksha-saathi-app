"""English as a built-in subject: content/ checks (docs/english_subject_contract.md, "Content agent").

Reads the content files directly, so it needs no database and no API key.
"""
import json
import re

from app.config import get_settings
from app.services import tips
from app.services.content import get_content

EN_NODES = {
    "E.G1.letter_names": [],
    "E.G1.letter_sounds": ["E.G1.letter_names"],
    "E.G1.oral_vocab": [],
    "E.G1.build_cvc": ["E.G1.letter_sounds"],
    "E.G1.read_cvc": ["E.G1.build_cvc"],
    "E.G1.sight_words": ["E.G1.read_cvc"],
    "E.G1.read_short_sent": ["E.G1.read_cvc"],
    "E.G2.blends_digraphs": ["E.G1.read_cvc"],
    "E.G2.spell_words": ["E.G1.build_cvc"],
    "E.G2.read_sentences": ["E.G1.read_short_sent"],
    "E.G2.make_sentence": ["E.G1.read_short_sent", "E.G1.oral_vocab"],
    "E.G2.simple_comp": ["E.G2.read_sentences"],
    "E.G3.read_passage": ["E.G2.read_sentences"],
    "E.G3.sentence_formation": ["E.G2.make_sentence"],
    "E.G3.word_types": ["E.G2.make_sentence"],
    "E.G3.story_comp": ["E.G2.simple_comp", "E.G3.read_passage"],
}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _raw(name: str) -> dict:
    return json.loads((get_settings().content_dir / name).read_text("utf-8"))


def _en_nodes():
    c = get_content()  # other tests register teachers' custom topics in this cache: leave those out
    return {x.id: x for x in c.checkpoints.values() if x.subject == "english" and x.id not in c.custom_ids}


def _en_activities():
    return [a for a in get_content().activities.values() if a.get("language") == "en"]


def _bank_en():
    return [i for i in _raw("voice_bank.json")["items"] if i["lang"] == "en"]


def test_sixteen_english_nodes_with_the_contract_prerequisites():
    nodes = _en_nodes()
    assert set(nodes) == set(EN_NODES)
    for cid, pre in EN_NODES.items():
        cp = nodes[cid]
        assert set(cp.prereqs) == set(pre), cid
        assert all(p in get_content().checkpoints for p in cp.prereqs), cid
        assert cp.language == "en" and cp.grade == int(cid[3]), cid
        assert cp.title_en.strip() and DEVANAGARI.search(cp.title_hi), cid
        assert 2 <= len(cp.misconceptions) <= 3 and cp.assess_via and cp.item_types and cp.chapter, cid
        assert all(re.fullmatch(r"[a-z0-9_]+", m) for m in cp.misconceptions), cid
    assert get_content().descendants_ok()


def test_english_nodes_do_not_leak_into_hindi_or_maths_listings():
    c = get_content()
    for subject in ("literacy", "numeracy"):
        assert not [x for x in c.template_roadmap(subject, 3) if x["checkpoint_id"].startswith("E.")]
    road = [x["checkpoint_id"] for x in c.template_roadmap("english", 3)]
    assert set(road) == set(EN_NODES)
    pos = {cid: i for i, cid in enumerate(road)}
    for cid, pre in EN_NODES.items():
        assert all(pos[p] < pos[cid] for p in pre), f"roadmap lists {cid} before a prerequisite"


def test_activities_cover_every_node_and_are_classroom_ready():
    acts = _en_activities()
    assert len(acts) == 9 and all(a["id"].startswith("act_en_") for a in acts)
    covered = set()
    for a in acts:
        assert a["mode"] == "group" and a["language"] == "en" and a["reviewed"] is True, a["id"]
        assert a["source_doc"] == "team-written, pending educator review", a["id"]
        ids = a["checkpoint_ids"]
        assert ids and all(i in EN_NODES for i in ids), a["id"]
        covered.update(ids)
        assert 8 <= a["duration_min"] <= 25, a["id"]
        assert 3 <= len(a["steps_hi"]) <= 6 and all(s.strip() and len(s) <= 260 for s in a["steps_hi"]), a["id"]
        for f in ("title_hi", "materials_hi", "blackboard_hi"):
            assert a[f].strip(), (a["id"], f)
        r = a["reassessment"]
        assert r["ask_hi"].strip() and r["expected"].strip(), a["id"]
        # English text lives in the *_hi fields: no Devanagari anywhere in an English activity
        text = " ".join([a["title_hi"], a["materials_hi"], a["blackboard_hi"], *a["steps_hi"], r["ask_hi"], r["expected"]])
        assert not DEVANAGARI.search(text), a["id"]
    assert covered == set(EN_NODES), set(EN_NODES) - covered
    for grade in "123":
        gap_nodes = {c for c in EN_NODES if c[3] == grade}
        assert gap_nodes <= covered
    assert not [a for a in get_content().activities.values()
                if a.get("language") != "en" and any(i.startswith("E.") for i in a["checkpoint_ids"])]


def test_activities_are_found_through_the_planner_lookup():
    c = get_content()
    for cid in EN_NODES:
        assert c.activities_for({cid}), f"no reviewed English activity for {cid}"


def test_probes_cover_the_five_contract_nodes():
    probes = {k: v for k, v in get_content().probes.items() if k.startswith("E.")}
    assert set(probes) == {"E.G1.letter_names", "E.G1.letter_sounds", "E.G1.read_cvc",
                           "E.G1.read_short_sent", "E.G2.make_sentence"}
    for cid, p in probes.items():
        assert cid in EN_NODES and p["title_hi"].strip() and p["pass_rule"].strip() and p["tell_hi"].strip()
        assert len(p["items"]) >= 3 and all(i["ask_hi"].strip() for i in p["items"]), cid
        assert not DEVANAGARI.search(json.dumps(p, ensure_ascii=False)), cid


def test_practice_items_for_the_english_nodes():
    items = [i for i in get_content().practice_items if i["checkpoint_id"].startswith("E.")]
    by_cp = {}
    for i in items:
        by_cp.setdefault(i["checkpoint_id"], []).append(i)
    for cid in ("E.G1.letter_names", "E.G1.read_cvc", "E.G1.read_short_sent"):
        assert len(by_cp.get(cid, [])) >= 3, cid
    assert len({i["id"] for i in get_content().practice_items}) == len(get_content().practice_items)
    for i in items:
        assert i["checkpoint_id"] in EN_NODES and i["language"] == "en" and i["tier"] in (1, 2, 3), i["id"]
        if i["type"] == "tap_choice":
            assert i["correct"] in i["options"], i["id"]
        else:
            assert i["type"] == "say_word" and i["target"] in i["accept"], i["id"]


def test_voice_bank_english_items_carry_the_stage_mapping():
    items = _bank_en()
    assert len(items) == 159
    for it in items:
        cp, st, g = it["checkpoint_id"], it["stage"], it["grade"]
        assert cp in EN_NODES, (it["id"], cp)
        if st == "letter":
            want = "E.G1.letter_sounds" if it["kind"] == "say_sound" else "E.G1.letter_names"
        elif st == "word_build":
            want = "E.G1.build_cvc" if g == 1 else "E.G2.spell_words"
        elif st == "word_read":
            want = "E.G1.read_cvc" if g == 1 else "E.G2.blends_digraphs"
        elif st == "sentence_build":
            want = "E.G3.sentence_formation" if g == 3 else "E.G2.make_sentence"
        else:
            want = {1: "E.G1.read_short_sent", 2: "E.G2.read_sentences", 3: "E.G3.read_passage"}[g]
        assert cp == want, (it["id"], cp, want)
    assert all(i["reviewed"] is True for i in items)  # reviewed flags are untouched
    ids = [i["id"] for i in _raw("voice_bank.json")["items"]]
    assert len(ids) == len(set(ids))
    # Hindi items keep their own checkpoints
    assert all((i["checkpoint_id"] or "L.").startswith("L.") for i in _raw("voice_bank.json")["items"] if i["lang"] == "hi")


def test_english_level_check_ladder():
    lad = _raw("level_check.json")["subjects"]["english"]
    assert lad["title_en"] == "English reading level" and lad["title_hi"] == "अंग्रेज़ी पढ़ने का स्तर"
    assert lad["beginner"]["key"] == "beginner"
    assert [lv["key"] for lv in lad["levels"]] == ["letter", "word", "sentence", "story"]
    assert [lv["checkpoint_id"] for lv in lad["levels"]] == [
        "E.G1.letter_names", "E.G1.read_cvc", "E.G1.read_short_sent", "E.G2.read_sentences"]
    bank = {i["id"]: i for i in _bank_en()}
    cps = get_content().checkpoints
    literacy = _raw("level_check.json")["subjects"]["literacy"]["levels"]
    for lv, hi in zip(lad["levels"], literacy):
        assert cps[lv["checkpoint_id"]].subject == "english"
        assert lv["of"] == len(lv["items"]) and 1 <= lv["pass_min"] <= lv["of"]
        assert (lv["pass_min"], lv["of"]) == (hi["pass_min"], hi["of"]), lv["key"]
        assert set(lv) == set(hi), lv["key"]
        for it in lv["items"]:
            src = bank[it["from"]]  # copied from a reviewed English voice-bank item
            assert src["reviewed"] is True
            assert it["show"] == (src["display"].get("text") or src["target"]), it
            assert src["checkpoint_id"] == lv["checkpoint_id"], it
    assert len({it["from"] for lv in lad["levels"] for it in lv["items"]}) == sum(lv["of"] for lv in lad["levels"])


def test_tips_and_home_versions_exist_for_every_english_node_and_activity():
    all_ = tips.all_tips()
    graph_m: dict[str, set[str]] = {}
    for cp in _en_nodes().values():
        for m in cp.misconceptions:
            graph_m.setdefault(m, set()).add(cp.id)
    for mid, cps in graph_m.items():
        t = all_[mid]
        assert set(t["checkpoint_ids"]) == cps, mid
        assert DEVANAGARI.search(t["explain_hi"]) and DEVANAGARI.search(t["game_hi"]), mid
        assert t["explain_en"].strip() and t["game_en"].strip() and t["example"].strip(), mid
        assert t["reviewed"] is True and t["source_doc"] == "team-written, pending educator review", mid
        assert tips.get_tip(mid)["id"] == mid  # served to parents
    hv = {h["id"]: h for h in _raw("activity_home.json")["activities"]}
    for a in _en_activities():
        h = hv[a["id"]]
        assert h["minutes"] == 5 and DEVANAGARI.search(h["title_hi"]) and h["title_en"].strip(), a["id"]
        assert 1 <= len(h["steps_hi"]) == len(h["steps_en"]) <= 3, a["id"]
        assert tips.home_version(a["id"])["id"] == a["id"]


def test_hindi_and_maths_content_is_unchanged_in_shape():
    c = get_content()
    built_in = [x for x in c.checkpoints.values() if x.id not in c.custom_ids]
    assert len([x for x in built_in if x.subject == "literacy"]) == 20
    assert len([x for x in built_in if x.subject == "numeracy"]) == 25
    assert len([a for a in c.activities.values() if a.get("language") != "en"]) == 18
    assert all(x.language == "hi" for x in built_in if x.subject == "literacy")
