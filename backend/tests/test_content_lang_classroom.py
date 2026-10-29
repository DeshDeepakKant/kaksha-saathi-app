"""The teacher's content language reaches every classroom flow (contract §4), and Hindi is unchanged.

A fake Claude client records each system prompt; `app.speech.transcribe` is replaced to record what STT
was asked for; the teacher's prefs are patched (`services.prefs`). Library translations are patched in
`i18n.library.localized`, so no file under content/ is touched.
"""
import hashlib
import io
import json
import uuid
from datetime import date
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.ai import features, llm
from app.config import get_settings
from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import Plan, School, Teacher
from app.services import content_lang, prefs
from app.services.content import get_content

BORROW = "N.G2.sub_2digit_borrow"  # has a reviewed activity (act_borrow_sticks) and a probe

# sha256 of each prompt file as it was before content languages: the Hindi render must match exactly
ORIGINAL_V1 = {
    "planner.v1": "19b1d099ddf650414ecc409383b3572ffbda42333045fdba428cce1acb8eacf2",
    "note_extraction.v1": "296b80cfaba732ef77c875c99e93b350105339528be0ecc55d6aebfd3b7f149b",
    "photo_analysis.v1": "77fe18ebc2aca3569dd850e23be59d557cb52619ccaf766f2a835966a27e1610",
    "roadmap_draft.v1": "d9cf3cca6873c596c31b3a44b7c26801f8506ee1deb9b699260b95370d509a8d",
    "book_mapping.v1": "109d9be1565348624b7fea4b4e289bc101c014e3ba3cde8b2ad8e5fb378e296a",
    "book_mapping_revise.v1": "efd3d8d65c37fa75cf9609ef693dcf2d457b32869baabed81bd91b7a717fefce",
    "book_research.v1": "29fd6e8d205053c1b014b4308454f8e393aeba31dee6f5a73617803cd33c34f9",
    "voice_assessment.v1": "07a8b8137468e8eb4dcf572988ff67bcf6b2392e065d057ce8b4f195110282cf",
    "tutor.v1": "c512ab4ebc88505c4404a6dad0c1f85520c743295a76af311735bd8a4c4393f3",
}


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def cl(client):
    """Own school + teacher + class 2 with three children who all got BORROW wrong (so a plan has a group)."""
    with SessionLocal() as db:
        school = School(name="Lang Test School", code="LG" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="Lang Teacher", pin_hash=hash_pin("2222"))
        db.add(t)
        db.commit()
        tid, sid = t.id, school.id
    h = {"Authorization": f"Bearer {make_token(str(tid), 'teacher')}"}
    r = client.post("/v1/classes", headers=h, json={"grade": 2, "section": "L" + uuid.uuid4().hex[:4]})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = client.post(f"/v1/classes/{cid}/children/bulk", headers=h,
                    json=[{"first_name": n, "roll_no": i + 1} for i, n in enumerate(["Asha", "Ravi", "Meena"])])
    assert r.status_code == 200, r.text
    kids = client.get(f"/v1/classes/{cid}/roster", headers=h).json()
    r = client.post(f"/v1/classes/{cid}/captures/tap", headers=h, json={"items": [
        {"child_id": k["id"], "checkpoint_id": BORROW, "result": "incorrect"} for k in kids]})
    assert r.status_code == 200, r.text
    return {"headers": h, "class_id": cid, "kids": kids, "teacher_id": tid, "school_id": sid}


@pytest.fixture
def lang(monkeypatch):
    """Set this test's content language + voice provider for every user."""
    def set_(code="hi", provider="sarvam"):
        monkeypatch.setattr(prefs, "content_lang_for", lambda db, teacher=None, parent=None: code)
        monkeypatch.setattr(prefs, "provider_for", lambda db, teacher=None, parent=None: provider)
    return set_


@pytest.fixture
def stt(monkeypatch):
    """Record every `app.speech.transcribe` call; it hears `heard`."""
    import app.speech as speech
    calls = []

    def install(heard="चौथा अध्याय वजाबाकीचा आहे"):
        def fake(audio, filename, lang="hi", keyterms=None, preferred="sarvam"):
            calls.append({"filename": filename, "lang": lang, "keyterms": keyterms, "preferred": preferred})
            return NS(text=heard, lang=lang, provider=preferred, fallback_used=False, error=None)
        monkeypatch.setattr(speech, "transcribe", fake, raising=False)
        return calls
    return install


class FakeMessages:
    """Answers forced-tool calls with `answer(kw)` (a dict, or a callable of the request)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        a = self.answers.pop(0)
        data = a(kw) if callable(a) else a
        block = NS(type="tool_use", id=f"tu_{len(self.calls)}", name=kw["tool_choice"]["name"], input=data)
        return NS(content=[block], usage=NS(input_tokens=100, output_tokens=50), stop_reason="tool_use")

    def system(self, i=0) -> str:
        return self.calls[i]["system"][0]["text"]


class FakeClient:  # hashable (llm caches per client), unlike SimpleNamespace
    def __init__(self, messages):
        self.messages = messages

    def with_options(self, **kw):
        return self


@pytest.fixture
def fake_ai(monkeypatch):
    def install(*answers):
        msgs = FakeMessages(answers)
        client = FakeClient(msgs)
        monkeypatch.setattr(llm, "_client", lambda: client)
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")
        monkeypatch.setattr(get_settings(), "book_web_search", False)
        return msgs
    return install


@pytest.fixture
def marathi_library(monkeypatch):
    """Pretend the pre-translated library has Marathi for everything: strings get an `MR:` prefix."""
    from app.i18n import library

    def localized(kind, id, field, lang, db=None, school_id=None):  # real library API: kind/field names, source()
        src = library.source(kind, id, field)
        if lang == "hi" or src is None:
            return {"text": src, "machine_translated": False}
        conv = (lambda s: f"MR:{s}")
        return {"text": [conv(s) for s in src] if isinstance(src, list) else conv(src), "machine_translated": True}
    monkeypatch.setattr(library, "localized", localized)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
    return buf.getvalue()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ prompts
@pytest.mark.parametrize("name", sorted(ORIGINAL_V1))
def test_hindi_prompt_renders_exactly_as_before(name):
    assert _sha(features.system_prompt(name, "hi")) == ORIGINAL_V1[name]
    assert _sha(features.system_prompt(name)) == ORIGINAL_V1[name]
    assert features.LANG_SLOT not in features.system_prompt(name, "hi")


@pytest.mark.parametrize("name", sorted(ORIGINAL_V1))
def test_other_language_prompt_carries_the_instruction(name):
    text = features.system_prompt(name, "mr")
    assert "Marathi" in text and "मराठी" in text and features.LANG_SLOT not in text
    assert "<!--" not in text  # the maintainer note never reaches the model


def test_unknown_language_falls_back_to_the_hindi_prompt():
    assert _sha(features.system_prompt("planner.v1", "xx")) == ORIGINAL_V1["planner.v1"]


# ------------------------------------------------------------------ STT
def test_pre_merge_stt_shim_passes_the_language(monkeypatch):
    import app.speech as speech
    seen = []

    class Rec:
        def transcribe(self, audio, filename, language="hi", keyterms=None):
            seen.append((filename, language, keyterms))
            return NS(text="ok")
    monkeypatch.delattr(speech, "transcribe", raising=False)
    monkeypatch.setattr(speech, "get_asr", lambda: Rec())
    assert content_lang.transcribe(b"x", "a.m4a", lang="ta", keyterms=["5"], preferred="gnani").text == "ok"
    assert seen == [("a.m4a", "ta", ["5"])]


@pytest.mark.parametrize("code,provider", [("hi", "sarvam"), ("mr", "gnani")])
def test_note_audio_uses_content_language_and_provider(client, cl, lang, stt, fake_ai, code, provider):
    lang(code, provider)
    calls = stt()
    cid = get_content().for_grade("numeracy", 2)[0].id
    msgs = fake_ai({"taught": [{"checkpoint_id": cid, "quote": "x"}], "children": []})
    r = client.post(f"/v1/classes/{cl['class_id']}/captures/note", headers=cl["headers"],
                    data={"subject": "numeracy"}, files={"audio": ("n.m4a", b"\x00\x01", "audio/mp4")})
    assert r.status_code == 200, r.text
    assert calls == [{"filename": "n.m4a", "lang": code, "keyterms": None, "preferred": provider}]
    assert r.json()["content_lang"] == code and r.json()["ai_status"] == "ready"
    system = msgs.system()
    if code == "hi":
        assert system.startswith(features.prompt("note_extraction.v1").replace(features.LANG_SLOT + "\n", ""))
        assert "Marathi" not in system
    else:
        assert "CONTENT LANGUAGE" in system and "Marathi" in system


def test_classroom_voice_passes_language_keyterms_and_provider(client, cl, lang, stt, fake_ai):
    lang("mr", "gnani")
    calls = stt(heard="का")
    msgs = fake_ai({"result": "correct", "confidence": 0.9, "misconception": None, "note_for_teacher_hi": "छान"})
    body = {"child_id": cl["kids"][0]["id"], "checkpoint_id": "L.G1.matra_basic", "target_items": ["का", "कि"]}
    r = client.post(f"/v1/classes/{cl['class_id']}/captures/voice", headers=cl["headers"],
                    data={"body_json": json.dumps(body)}, files={"audio": ("v.m4a", b"\x00\x01", "audio/mp4")})
    assert r.status_code == 200, r.text
    assert calls == [{"filename": "v.m4a", "lang": "mr", "keyterms": ["का", "कि"], "preferred": "gnani"}]
    assert r.json()["content_lang"] == "mr"
    assert "Marathi" in msgs.system()


def test_voice_in_hindi_keeps_the_old_call(client, cl, lang, stt):
    lang("hi")
    calls = stt(heard="का")
    body = {"child_id": cl["kids"][0]["id"], "checkpoint_id": "L.G1.matra_basic", "target_items": ["का"]}
    r = client.post(f"/v1/classes/{cl['class_id']}/captures/voice", headers=cl["headers"],
                    data={"body_json": json.dumps(body)}, files={"audio": ("v.m4a", b"\x00\x01", "audio/mp4")})
    assert r.status_code == 200, r.text
    assert calls == [{"filename": "v.m4a", "lang": "hi", "keyterms": ["का"], "preferred": "sarvam"}]


def test_book_revise_audio_and_prompt_use_content_language(client, cl, lang, stt, fake_ai):
    lang("mr", "gnani")
    calls = stt()
    draft = {"book": {"title": "गणित", "grade": 2}, "chapters": [
        {"title": "बेरीज", "inferred": False, "basis": "page", "topics": [{"text": "बेरीज", "checkpoint_id": None}]}]}
    revised = {"book": {"title": "गणित", "grade": 2, "board": "", "publisher": "", "read_from_cover": False},
               "chapters": [{"title": "वजाबाकी", "inferred": False, "basis": "page",
                             "topics": [{"text": "", "checkpoint_id": BORROW}]}], "confidence": 0.8}
    msgs = fake_ai(revised)
    r = client.post(f"/v1/classes/{cl['class_id']}/books/map/revise", headers=cl["headers"],
                    data={"subject": "numeracy", "draft": json.dumps(draft)},
                    files={"audio": ("c.m4a", b"\x00\x01", "audio/mp4")})
    assert r.status_code == 200, r.text
    assert calls == [{"filename": "c.m4a", "lang": "mr", "keyterms": None, "preferred": "gnani"}]
    j = r.json()
    assert j["status"] == "ready" and j["content_lang"] == "mr"
    assert "Write chapter titles and topic names in Marathi" in msgs.system()
    # an empty topic text is filled with the lesson title in the content language (English-first for Hindi)
    assert j["chapters"][0]["topics"][0]["text"] == content_lang.checkpoint_title(get_content(), BORROW, "mr")[0]


@pytest.mark.parametrize("code", ["hi", "mr"])
def test_book_map_prompt_and_response(client, cl, lang, fake_ai, code):
    lang(code)
    mapped = {"book": {"title": "Math", "grade": 2, "board": "", "publisher": "", "read_from_cover": False},
              "chapters": [{"title": "Ch", "inferred": False, "basis": "page",
                            "topics": [{"text": "x", "checkpoint_id": BORROW}]}], "confidence": 0.7}
    msgs = fake_ai(mapped)
    r = client.post(f"/v1/classes/{cl['class_id']}/books/map", headers=cl["headers"],
                    data={"subject": "numeracy", "book_title": "Math"})
    assert r.status_code == 200, r.text
    assert r.json()["content_lang"] == code
    head = features.prompt("book_mapping.v1").replace(features.LANG_SLOT + "\n", "")
    assert msgs.system().startswith(head + ("\n\nCANDIDATE CONCEPTS" if code == "hi" else "CONTENT LANGUAGE: "))
    assert ("Marathi" in msgs.system()) == (code == "mr")


def test_photo_and_roadmap_prompts_get_the_language(client, cl, lang, fake_ai):
    lang("ta")
    msgs = fake_ai({"page": {"legible": True}, "questions": [{"printed": "2 + 3", "student_answer": "5",
                                                              "self_verdict": "correct"}]},
                   {"chapters": [{"title": "கூட்டல்", "subtopics": []}], "confidence": 0.8})
    kid = cl["kids"][0]["id"]
    r = client.post(f"/v1/classes/{cl['class_id']}/captures/photo", headers=cl["headers"],
                    data={"child_id": str(kid), "subject": "numeracy"},
                    files={"image": ("p.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["content_lang"] == "ta" and "Tamil" in msgs.system(0)
    r = client.post(f"/v1/classes/{cl['class_id']}/roadmap/draft", headers=cl["headers"],
                    data={"subject": "numeracy"}, files={"image": ("i.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["content_lang"] == "ta" and "Tamil" in msgs.system(1)


# ------------------------------------------------------------------ plans
def _plan_answer(kw):
    """A valid plan: the first candidate for every group."""
    user = json.loads(kw["messages"][0]["content"][-1]["text"])
    return {"groups": [{"key": g["key"], "activity_id": g["candidates"][0]["id"], "why_hi": "कारण",
                        "teacher_script_hi": "पायरी", "time_min": 5, "order": i + 1,
                        "reassessment": g["candidates"][0]["reassessment"]}
                       for i, g in enumerate(user["groups"])],
            "whole_class_note_hi": "", "today_observation_to_collect_hi": "निरीक्षण"}


def _plan(client, cl, day, force=False):
    r = client.post(f"/v1/classes/{cl['class_id']}/plans", headers=cl["headers"],
                    params={"subject": "numeracy", "for_date": day, "force": force})
    assert r.status_code == 200, r.text
    return r.json()


def test_hindi_plan_prompt_and_payload_unchanged(client, cl, lang, fake_ai):
    lang("hi")
    msgs = fake_ai(_plan_answer)
    j = _plan(client, cl, "2031-01-06")
    assert j["generated_by"] == "ai" and j["content_lang"] == "hi" and "machine_translated" not in j
    assert _sha(msgs.system()) == ORIGINAL_V1["planner.v1"]
    user = json.loads(msgs.calls[0]["messages"][0]["content"][-1]["text"])
    act = get_content().activities["act_borrow_sticks"]
    cand = next(c for g in user["groups"] for c in g["candidates"] if c["id"] == act["id"])
    assert cand["steps_hi"] == act["steps_hi"] and cand["title_hi"] == act["title_hi"]
    g = next(g for g in j["groups"] if g["activity_id"] == act["id"])
    assert g["activity"]["steps_hi"] == act["steps_hi"] and "machine_translated" not in g["activity"]


def test_plan_in_marathi_localizes_candidates_and_response_not_storage(client, cl, lang, fake_ai, marathi_library):
    lang("mr")
    msgs = fake_ai(_plan_answer)
    j = _plan(client, cl, "2031-01-07")
    assert j["generated_by"] == "ai" and j["content_lang"] == "mr" and j["machine_translated"] is True
    assert "Marathi" in msgs.system()
    user = json.loads(msgs.calls[0]["messages"][0]["content"][-1]["text"])
    cand = next(c for g in user["groups"] for c in g["candidates"] if c["id"] == "act_borrow_sticks")
    assert all(s.startswith("MR:") for s in cand["steps_hi"])
    assert cand["reassessment"]["ask_hi"].startswith("MR:")
    g = next(g for g in j["groups"] if g["activity_id"] == "act_borrow_sticks")
    assert g["activity"]["machine_translated"] is True and g["activity"]["steps_hi"][0].startswith("MR:")
    with SessionLocal() as db:  # storage keeps the reviewed Hindi library text
        stored = db.get(Plan, j["id"]).payload
    sg = next(g for g in stored["groups"] if g["activity_id"] == "act_borrow_sticks")
    assert sg["activity"]["steps_hi"] == get_content().activities["act_borrow_sticks"]["steps_hi"]
    # latest shows the same localized view
    r = client.get(f"/v1/classes/{cl['class_id']}/plans/latest", headers=cl["headers"],
                   params={"subject": "numeracy"})
    assert r.json()["content_lang"] == "mr"


def test_saved_plan_is_rewritten_when_the_language_changes(client, cl, lang, fake_ai):
    lang("hi")
    first = _plan(client, cl, "2031-01-08")  # template plan (no key)
    assert first["content_lang"] == "hi"
    again = _plan(client, cl, "2031-01-08")
    assert again["id"] == first["id"] and again == first  # same language: the saved plan, untouched
    lang("mr")
    msgs = fake_ai(_plan_answer)
    mr = _plan(client, cl, "2031-01-08")
    assert mr["id"] == first["id"] and mr["content_lang"] == "mr" and len(msgs.calls) == 1


def test_template_plan_in_marathi_uses_the_localized_activity(client, cl, lang, marathi_library):
    lang("mr")
    j = _plan(client, cl, "2031-01-09")
    assert j["generated_by"] == "fallback" and j["content_lang"] == "mr" and j["machine_translated"] is True
    g = next(g for g in j["groups"] if g["activity_id"] == "act_borrow_sticks")
    assert g["teacher_script_hi"].startswith("MR:") and g["reassessment"]["ask_hi"].startswith("MR:")


# ------------------------------------------------------------------ probes + titles
def test_probe_hindi_unchanged_and_marathi_localized(client, cl, lang, marathi_library):
    lang("hi")
    j = client.get(f"/v1/checkpoints/{BORROW}/probe", headers=cl["headers"]).json()
    src = get_content().probes[BORROW]
    assert j["probe"] == src and j["suggestion"] == src["title_hi"] and j["content_lang"] == "hi"
    assert "machine_translated" not in j
    lang("mr")
    j = client.get(f"/v1/checkpoints/{BORROW}/probe", headers=cl["headers"]).json()
    assert j["content_lang"] == "mr" and j["machine_translated"] is True
    assert j["probe"]["title_hi"].startswith("MR:") and j["suggestion"] == j["probe"]["title_hi"]
    assert [i["ask_hi"] for i in j["probe"]["items"]] == ["MR:" + i["ask_hi"] for i in src["items"]]
    assert get_content().probes[BORROW]["title_hi"] == src["title_hi"]  # library untouched


def test_titles_endpoint(client, cl, lang, parent_headers, marathi_library):
    content = get_content()
    lang("hi")
    j = client.get("/v1/content/titles", headers=cl["headers"]).json()
    assert j["lang"] == "hi" and j["machine_translated"] is False
    assert j["titles"][BORROW] == content.checkpoints[BORROW].title_hi
    assert not any(c in j["titles"] for c in content.custom_ids if not c.startswith(f"C{cl['school_id']}-"))
    j = client.get("/v1/content/titles", headers=cl["headers"], params={"lang": "en"}).json()
    assert j["titles"][BORROW] == content.checkpoints[BORROW].title_en and j["machine_translated"] is False
    j = client.get("/v1/content/titles", headers=parent_headers, params={"lang": "mr"}).json()
    assert j["lang"] == "mr" and j["machine_translated"] is True
    assert j["titles"][BORROW] == "MR:" + content.checkpoints[BORROW].title_hi
    lang("mr")  # no ?lang: the caller's own content language
    assert client.get("/v1/content/titles", headers=cl["headers"]).json()["lang"] == "mr"
    assert client.get("/v1/content/titles", headers=cl["headers"], params={"lang": "xx"}).status_code == 422
    assert client.get("/v1/content/titles").status_code == 401


def test_saved_book_records_its_language(client, cl, lang):
    lang("mr")
    body = {"subject": "numeracy", "source": "book", "items": [{"checkpoint_id": BORROW, "chapter": "वजाबाकी"}],
            "book": {"title": "गणित", "chapters": [{"title": "वजाबाकी", "topics": [{"checkpoint_id": BORROW}]}]}}
    r = client.post(f"/v1/classes/{cl['class_id']}/syllabus", headers=cl["headers"], json=body)
    assert r.status_code == 200, r.text
    assert r.json()["book"]["content_lang"] == "mr"
