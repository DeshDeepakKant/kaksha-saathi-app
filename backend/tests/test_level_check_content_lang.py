"""The level check shows reading items in the class's learning language; Hindi stays as it was."""
import pytest

from app.i18n.script import in_script
from app.services import level_check as lc
from app.speech import capabilities


def test_literacy_ladder_in_tamil_keeps_levels_and_swaps_items():
    hi, ta = lc.ladder_in("literacy", "hi"), lc.ladder_in("literacy", "ta")
    assert hi is lc.ladder("literacy")
    assert [lv["key"] for lv in ta["levels"]] == [lv["key"] for lv in hi["levels"]]
    assert [lv["checkpoint_id"] for lv in ta["levels"]] == [lv["checkpoint_id"] for lv in hi["levels"]]
    assert ta["machine_translated"] is True and ta["content_lang"] == "ta"
    for lv in ta["levels"]:
        assert len(lv["items"]) == lv["of"] and all(in_script(i["show"], "ta") for i in lv["items"])
    assert lc.ladder_in("numeracy", "ta") is lc.ladder("numeracy")  # numbers need no change


def test_level_check_endpoint_follows_teacher_content_language(client, teacher_headers, monkeypatch):
    monkeypatch.setattr(capabilities, "content_languages", lambda: ["en", "hi", "ta"])
    cid = client.get("/v1/classes", headers=teacher_headers).json()[0]["id"]
    before = client.get(f"/v1/classes/{cid}/level_check?subject=literacy", headers=teacher_headers).json()
    assert "content_lang" not in before and before["levels"][0]["items"][0]["show"] == "क"
    try:
        assert client.post("/v1/me/prefs", headers=teacher_headers, json={"content_lang": "ta"}).status_code == 200
        r = client.get(f"/v1/classes/{cid}/level_check?subject=literacy", headers=teacher_headers).json()
        assert r["content_lang"] == "ta" and in_script(r["levels"][0]["items"][0]["show"], "ta")
        assert r["levels"][0]["ask_content"] and r["levels"][0]["ask_en"] == before["levels"][0]["ask_en"]
    finally:
        client.post("/v1/me/prefs", headers=teacher_headers, json={"content_lang": "hi"})
