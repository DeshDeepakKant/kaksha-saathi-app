"""Parent content: misconception tips and 5-minute home versions of class activities."""
import json
import re
import unicodedata

from app.config import get_settings
from app.services import tips
from app.services.content import get_content

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
DEVANAGARI_RUN = re.compile(r"[ऀ-ॿ]+")
TIP_FIELDS = ("explain_hi", "explain_en", "game_hi", "game_en", "example")
HOME_TEXT = ("title_hi", "title_en", "materials_hi", "materials_en")
BLOCKED_HI = ("मारना", "मारो", "पीटना", "पीटो", "थप्पड़", "कमज़ोर", "कमजोर", "बेवकूफ़", "बेवकूफ", "मूर्ख",
              "गधा", "सज़ा", "सजा", "डाँट", "डांट", "नालायक")
BLOCKED_EN = re.compile(r"\b(beat|hit|slap|stupid|dumb|weak|lazy|idiot|punish\w*|slow learner)\b", re.I)


def _raw(name: str) -> dict:
    return json.loads((get_settings().content_dir / name).read_text("utf-8"))


def _home_entries() -> list[dict]:
    return _raw("activity_home.json")["activities"]


def _strings(entry: dict) -> list[str]:
    vals: list = []
    for v in entry.values():
        vals.extend(v if isinstance(v, list) else [v])
    return [v for v in vals if isinstance(v, str)]


def _is_english(s: str) -> bool:
    """English text may quote a single Hindi letter (e.g. "the letters 'न' and 'ण'"), never a Hindi word."""
    return all(len(run) <= 3 for run in DEVANAGARI_RUN.findall(s)) and bool(re.search(r"[A-Za-z]", s))


def test_every_graph_misconception_has_a_tip_with_its_checkpoints():
    graph: dict[str, set[str]] = {}
    for cp in get_content().checkpoints.values():
        for m in cp.misconceptions:
            graph.setdefault(m, set()).add(cp.id)
    all_ = tips.all_tips()
    assert set(graph) == set(all_), set(graph) ^ set(all_)
    for mid, cps in graph.items():
        assert set(all_[mid]["checkpoint_ids"]) == cps, mid
    assert len(_raw("misconception_tips.json")["tips"]) == len(all_), "duplicate tip ids"


def test_tip_fields_complete_and_in_the_right_script():
    for mid, t in tips.all_tips().items():
        for f in TIP_FIELDS:
            assert isinstance(t.get(f), str) and t[f].strip(), (mid, f)
        assert isinstance(t.get("reviewed"), bool), mid
        assert DEVANAGARI.search(t["explain_hi"]) and DEVANAGARI.search(t["game_hi"]), mid
        assert _is_english(t["explain_en"]) and _is_english(t["game_en"]), mid


def test_home_version_for_every_activity():
    acts = set(get_content().activities)
    home = [h["id"] for h in _home_entries()]
    assert acts == set(home) and len(home) == len(set(home)), acts ^ set(home)
    for aid in acts:
        assert tips.home_version(aid)["id"] == aid


def test_home_versions_short_complete_and_in_the_right_script():
    for h in _home_entries():
        hid = h["id"]
        for f in HOME_TEXT:
            assert isinstance(h.get(f), str) and h[f].strip(), (hid, f)
        assert h["minutes"] == 5, hid
        for lang in ("hi", "en"):
            steps = h[f"steps_{lang}"]
            assert 1 <= len(steps) <= 3 and all(isinstance(s, str) and s.strip() for s in steps), (hid, lang)
        assert len(h["steps_hi"]) == len(h["steps_en"]), hid
        for s in (h["title_hi"], h["materials_hi"], *h["steps_hi"]):
            assert DEVANAGARI.search(s), (hid, s)
        for s in (h["title_en"], h["materials_en"], *h["steps_en"]):
            assert _is_english(s), (hid, s)
        assert not DEVANAGARI.search(h["title_en"] + h["materials_en"]), hid


def test_text_is_nfc_and_child_safe():
    for e in list(tips.all_tips().values()) + _home_entries():
        for s in _strings(e):
            assert unicodedata.normalize("NFC", s) == s, (e["id"], s)
            assert not any(w in s for w in BLOCKED_HI), (e["id"], s)
            assert not BLOCKED_EN.search(s), (e["id"], s)


def test_loader_lookups():
    assert tips.get_tip("no_such_misconception") is None
    assert tips.get_tip("") is None and tips.get_tip(None) is None
    assert tips.home_version("act_no_such_activity") is None and tips.home_version(None) is None
    t = tips.get_tip("smaller_minus_larger")
    assert t and t["reviewed"] and "N.G2.sub_2digit_borrow" in t["checkpoint_ids"]
    for m, x in tips.all_tips().items():
        if not x["reviewed"]:  # not served to parents until a mentor reviews it
            assert tips.get_tip(m) is None and tips.get_tip(m, reviewed_only=False)["id"] == m
    t["explain_hi"] = "x"  # callers get copies; the cache is untouched
    assert tips.get_tip("smaller_minus_larger")["explain_hi"] != "x"
