"""Smart textbook mapping: /books/map, /books/map/revise, saving a book with the syllabus, web research.

Runs with no API key. Where AI behaviour matters, `llm._client` is replaced by a fake that answers the
structured (forced tool) call and the web-search call, and the settings get a dummy key.
"""
import io
import json
import uuid
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.ai import llm
from app.config import get_settings
from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import AiCall, School, Teacher
from app.services.content import get_content


@pytest.fixture(scope="module")
def bk(client):
    """A separate school + teacher + one class 2 and one class 3, so the DEMO data is untouched."""
    with SessionLocal() as db:
        school = School(name="Books Test School", code="BK" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="Books Teacher", pin_hash=hash_pin("1111"))
        db.add(t)
        db.commit()
        headers = {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}
    ids = {}
    for grade in (2, 3):
        r = client.post("/v1/classes", headers=headers, json={"grade": grade, "section": "B" + uuid.uuid4().hex[:4]})
        assert r.status_code == 200, r.text
        ids[grade] = r.json()["id"]
    return {"headers": headers, "c2": ids[2], "c3": ids[3]}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
    return buf.getvalue()


def _valid_ids(subject: str, grade: int) -> set[str]:
    c = get_content()
    return {x.id for x in c.for_grade(subject, grade)} | {i["checkpoint_id"] for i in c.template_roadmap(subject, grade)}


def _assert_items_valid(j: dict, subject: str, grade: int):
    ok = _valid_ids(subject, grade)
    assert j["items"], j
    assert len(j["items"]) <= 80 and len(j["chapters"]) <= 40
    for n, it in enumerate(j["items"]):
        assert it["position"] == n
        assert set(it) == {"chapter", "checkpoint_id", "custom_title", "position"}
        if it["checkpoint_id"] is None:
            assert it["custom_title"]
        else:
            assert it["checkpoint_id"] in ok and it["custom_title"] is None
    for ch in j["chapters"]:
        for t in ch["topics"]:
            assert t["checkpoint_id"] is None or t["checkpoint_id"] in ok


# ------------------------------------------------------------------ fake Claude
class FakeMessages:
    def __init__(self, tool_inputs=(), research=()):
        self.tool_inputs = list(tool_inputs)  # inputs for successive forced-tool calls
        self.research = list(research)  # full responses for successive web-search calls
        self.calls = []

    def create(self, **kw):  # no `temperature` parameter, like the newest SDK signature
        self.calls.append(kw)
        if any(t.get("type", "").startswith("web_search") for t in kw.get("tools", [])):
            r = self.research.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        block = NS(type="tool_use", id=f"tu_{len(self.calls)}", name=kw["tool_choice"]["name"],
                   input=self.tool_inputs.pop(0))
        return NS(content=[block], usage=NS(input_tokens=100, output_tokens=50), stop_reason="tool_use")


class FakeClient:
    def __init__(self, messages: FakeMessages):
        self.messages = messages
        self.options = []  # (timeout, max_retries) per with_options() call

    def with_options(self, *, timeout=None, max_retries=None):
        self.options.append((timeout, max_retries))
        return self


def _search_resp(stop, *, text=None, results=True, error=False):
    content = [NS(type="server_tool_use", id="srv_1", name="web_search", input={"query": "book"})]
    if error:
        content.append(NS(type="web_search_tool_result", tool_use_id="srv_1",
                          content=NS(type="web_search_tool_result_error", error_code="unavailable")))
    elif results:
        content.append(NS(type="web_search_tool_result", tool_use_id="srv_1",
                          content=[NS(type="web_search_result", url="https://ncert.nic.in/x", title="TOC")]))
    if text:
        content.append(NS(type="text", text=text))
    return NS(content=content, stop_reason=stop,
              usage=NS(input_tokens=200, output_tokens=80, server_tool_use=NS(web_search_requests=1)))


@pytest.fixture
def fake_ai(monkeypatch):
    def install(tool_inputs=(), research=(), web=True):
        msgs = FakeMessages(tool_inputs, research)
        client = FakeClient(msgs)
        monkeypatch.setattr(llm, "_client", lambda: client)
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")
        monkeypatch.setattr(get_settings(), "book_web_search", web)
        return msgs
    return install


def _model_map(**book):
    return {
        "book": {"title": "Joyful Mathematics", "grade": 2, "board": "NCERT", "publisher": "NCERT",
                 "read_from_cover": True, **book},
        "chapters": [
            {"title": "Mango Treat", "inferred": True, "basis": "book_knowledge",
             "topics": [{"text": "Count objects up to 20", "checkpoint_id": "N.G1.count_to_20"},
                        {"text": "Zebra quilt jamboree", "checkpoint_id": "N.G9.not_a_real_id"}]},
            {"title": "Web said so", "inferred": True, "basis": "web",
             "topics": [{"text": "Zebra quilt jamboree two", "checkpoint_id": None}]},
            {"title": "Xylophone yard", "inferred": False, "basis": "page", "topics": []},
        ],
        "confidence": 0.7,
    }


# ------------------------------------------------------------------ /books/map
def test_typed_title_without_key_falls_back_to_template(client, bk):
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics", "board": "NCERT"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "fallback" and "template" in j["note"]
    assert j["used_web"] is False and 0 <= j["confidence"] <= 1
    assert j["book"] == {"title": "Joyful Mathematics", "grade": 2, "subject": "numeracy", "board": "NCERT",
                         "publisher": "", "identified_from": "typed"}
    assert j["chapters"] and all(c["basis"] == "template" and c["inferred"] is False for c in j["chapters"])
    _assert_items_valid(j, "numeracy", 2)


def test_book_grade_overrides_class_grade_and_aliases_resolve(client, bk):
    r = client.post(f"/v1/classes/{bk['c3']}/books/map", headers=bk["headers"],
                    data={"subject": "maths", "book_title": "Maths Magic", "book_grade": "1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["book"]["grade"] == 1 and j["book"]["subject"] == "numeracy"
    _assert_items_valid(j, "numeracy", 1)


@pytest.mark.parametrize("data,files", [
    ({"subject": "numeracy"}, None),  # no photo, no title
    ({"subject": "numeracy", "book_title": "   "}, None),  # blank title is no title
    ({"subject": "numeracy", "book_title": "X", "book_grade": "9"}, None),
    ({"subject": "numeracy", "book_title": "X", "book_grade": "two"}, None),
    ({"subject": "numeracy", "book_title": "x" * 121}, None),
    ({"subject": "nope", "book_title": "X"}, None),
    ({"subject": "numeracy"}, [("images", (f"p{i}.jpg", _jpeg(), "image/jpeg")) for i in range(7)]),
    ({"subject": "numeracy"}, [("images", ("p.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64, "image/heic"))]),
])
def test_map_bad_input_is_422(client, bk, data, files):
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"], data=data, files=files)
    assert r.status_code == 422, r.text


def test_map_needs_teacher_and_own_class(client, bk, teacher_headers):
    assert client.post(f"/v1/classes/{bk['c2']}/books/map", data={"subject": "numeracy", "book_title": "X"}
                       ).status_code == 401
    # another school's teacher can't map this class
    assert client.post(f"/v1/classes/{bk['c2']}/books/map", headers=teacher_headers,
                       data={"subject": "numeracy", "book_title": "X"}).status_code == 404


def test_six_photos_without_title_is_accepted(client, bk):
    files = [("images", (f"p{i}.jpg", _jpeg(), "application/octet-stream")) for i in range(6)]
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"], data={"subject": "numeracy"},
                    files=files)
    assert r.status_code == 200, r.text
    assert r.json()["book"]["identified_from"] == "none"


def test_model_mapping_is_validated(client, bk, fake_ai):
    msgs = fake_ai(tool_inputs=[_model_map()], web=False)
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics"},
                    files=[("images", ("cover.jpg", _jpeg(), "application/octet-stream")),
                           ("images", ("index.jpg", _jpeg(), "application/octet-stream"))])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ready" and j["used_web"] is False
    assert j["book"]["identified_from"] == "both" and j["book"]["board"] == "NCERT"
    mango, web, plain = j["chapters"]
    assert mango["inferred"] is True and mango["basis"] == "book_knowledge"
    assert mango["topics"][0] == {"text": "Count objects up to 20", "checkpoint_id": "N.G1.count_to_20"}
    assert mango["topics"][1] == {"text": "Zebra quilt jamboree", "checkpoint_id": None}  # unknown id dropped
    assert web["basis"] == "book_knowledge"  # no research notes were used, so "web" can't be claimed
    assert plain["topics"] == [] and plain["inferred"] is False
    _assert_items_valid(j, "numeracy", 2)
    assert [i["custom_title"] for i in j["items"]] == [None, "Zebra quilt jamboree", "Zebra quilt jamboree two",
                                                      "Xylophone yard"]
    assert j["items"][0]["checkpoint_id"] == "N.G1.count_to_20" and j["items"][0]["chapter"] == "Mango Treat"
    # one structured call, with the book model, both photos and the candidate concepts
    (call,) = msgs.calls
    assert call["model"] == get_settings().model_book
    assert sum(1 for b in call["messages"][0]["content"] if b["type"] == "image") == 2
    assert "N.G1.count_to_20" in call["system"][0]["text"]


def test_typed_title_researches_first_and_allows_web_basis(client, bk, fake_ai):
    msgs = fake_ai(tool_inputs=[_model_map()],
                   research=[_search_resp("end_turn", text="1. Mango Treat — counting to 20")])
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics", "board": "NCERT"})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ready" and j["used_web"] is True
    assert j["chapters"][1]["basis"] == "web"
    assert len(msgs.calls) == 2 and "Mango Treat — counting to 20" in msgs.calls[1]["messages"][0]["content"][-1]["text"]


def test_research_error_still_maps(client, bk, fake_ai):
    msgs = fake_ai(tool_inputs=[_model_map()], research=[_search_resp("end_turn", text="sorry", error=True)])
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics"})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ready" and j["used_web"] is False
    assert "RESEARCH NOTES: (none)" in msgs.calls[1]["messages"][0]["content"][-1]["text"]


def test_research_exception_still_maps(client, bk, fake_ai):
    fake_ai(tool_inputs=[_model_map()], research=[llm.LLMUnavailable("boom")])
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics"})
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["used_web"] is False


def test_cover_only_title_researches_then_refines_once(client, bk, fake_ai):
    refined = _model_map()
    refined["chapters"][0]["basis"] = "web"
    msgs = fake_ai(tool_inputs=[_model_map(), refined],
                   research=[_search_resp("end_turn", text="1. Mango Treat — counting")])
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"], data={"subject": "numeracy"},
                    files=[("images", ("cover.jpg", _jpeg(), "image/jpeg"))])
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ready", r.text
    assert j["book"]["identified_from"] == "cover" and j["book"]["title"] == "Joyful Mathematics"
    assert j["used_web"] is True and j["chapters"][0]["basis"] == "web"
    assert len(msgs.calls) == 3  # map, research, refine: never more


def test_model_with_no_chapters_falls_back(client, bk, fake_ai):
    fake_ai(tool_inputs=[{"chapters": [], "confidence": 0.1}, {"chapters": [], "confidence": 0.1}], web=False)
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Unknown Local Book"})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "fallback" and "identify" in j["note"]
    _assert_items_valid(j, "numeracy", 2)


def test_caps_chapters_and_items(client, bk, fake_ai):
    big = {"chapters": [{"title": f"Ch {n}", "inferred": False, "basis": "page",
                         "topics": [{"text": f"Zz topic {n}-{k}", "checkpoint_id": None} for k in range(3)]}
                        for n in range(60)], "confidence": 0.5}
    fake_ai(tool_inputs=[big], web=False)
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Big"})
    j = r.json()
    assert r.status_code == 200 and len(j["items"]) == 80 and len(j["chapters"]) <= 40


# ------------------------------------------------------------------ /books/map/revise
DRAFT = {"book": {"title": "Joyful Mathematics", "grade": 2, "board": "NCERT", "publisher": "NCERT",
                  "identified_from": "typed"},
         "chapters": [{"title": "Mango Treat", "inferred": True, "basis": "book_knowledge",
                       "topics": [{"text": "Count objects up to 20", "checkpoint_id": "N.G1.count_to_20"},
                                  {"text": "Bogus", "checkpoint_id": "NOPE"}]},
                      {"title": "Xylophone yard", "inferred": False, "basis": "page", "topics": []}]}


def test_revise_without_key_returns_draft_unchanged(client, bk):
    r = client.post(f"/v1/classes/{bk['c2']}/books/map/revise", headers=bk["headers"],
                    data={"subject": "numeracy", "draft": json.dumps(DRAFT),
                          "transcript": "chapter 2 is about shapes"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "fallback" and "by hand" in j["note"] and j["heard"] == "chapter 2 is about shapes"
    assert [c["title"] for c in j["chapters"]] == ["Mango Treat", "Xylophone yard"]
    assert j["chapters"][0]["topics"][0] == {"text": "Count objects up to 20", "checkpoint_id": "N.G1.count_to_20"}
    assert j["chapters"][0]["topics"][1]["checkpoint_id"] is None  # re-validated
    assert j["book"]["title"] == "Joyful Mathematics" and j["book"]["identified_from"] == "typed"
    _assert_items_valid(j, "numeracy", 2)


@pytest.mark.parametrize("data,files", [
    ({"subject": "numeracy", "draft": json.dumps(DRAFT)}, None),
    ({"subject": "numeracy", "draft": json.dumps(DRAFT), "transcript": "  "}, None),
    # no-key ASR hears nothing → same 422
    ({"subject": "numeracy", "draft": json.dumps(DRAFT)}, {"audio": ("c.m4a", b"\x00" * 100, "audio/mp4")}),
    ({"subject": "numeracy", "draft": "{not json", "transcript": "x"}, None),
    ({"subject": "numeracy", "draft": "[1, 2]", "transcript": "x"}, None),
    ({"subject": "numeracy", "transcript": "x"}, None),
])
def test_revise_bad_input_is_422(client, bk, data, files):
    r = client.post(f"/v1/classes/{bk['c2']}/books/map/revise", headers=bk["headers"], data=data, files=files)
    assert r.status_code == 422, r.text


def test_revise_with_model_applies_correction(client, bk, fake_ai):
    revised = {"book": {"title": "Joyful Mathematics", "grade": 2},
               "chapters": [DRAFT["chapters"][0],
                            {"title": "Xylophone yard", "inferred": False, "basis": "page",
                             "topics": [{"text": "Shapes around us", "checkpoint_id": None}]}],
               "confidence": 0.8, "note": ""}
    msgs = fake_ai(tool_inputs=[revised], web=False)
    r = client.post(f"/v1/classes/{bk['c2']}/books/map/revise", headers=bk["headers"],
                    data={"subject": "numeracy", "draft": json.dumps(DRAFT),
                          "transcript": "अध्याय 2 में आकृतियाँ हैं"})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ready", r.text
    assert j["heard"] == "अध्याय 2 में आकृतियाँ हैं" and j["chapters"][1]["topics"][0]["text"] == "Shapes around us"
    assert j["book"]["board"] == "NCERT"  # kept from the draft when the model leaves it out
    assert "अध्याय 2 में आकृतियाँ हैं" in msgs.calls[0]["messages"][0]["content"][-1]["text"]
    _assert_items_valid(j, "numeracy", 2)


# ------------------------------------------------------------------ save with the syllabus
def test_save_syllabus_with_book_and_read_it_back(client, bk):
    cid = bk["c3"]
    assert client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=bk["headers"]).json()["book"] is None
    body = {"subject": "numeracy", "source": "book",
            "items": [{"chapter": "Mango Treat", "checkpoint_id": "N.G1.count_to_20", "position": 0},
                      {"chapter": "Mango Treat", "custom_title": "Sharing mangoes equally", "position": 1}],
            "book": {"title": "Joyful Mathematics", "grade": 3, "board": "NCERT", "publisher": "NCERT",
                     "identified_from": "both",
                     "chapters": [{"title": "Mango Treat", "inferred": True, "basis": "book_knowledge",
                                   "topics": [{"text": "Count objects up to 20", "checkpoint_id": "N.G1.count_to_20"},
                                              {"text": "Sharing mangoes equally", "checkpoint_id": None}]}]}}
    r = client.post(f"/v1/classes/{cid}/syllabus", headers=bk["headers"], json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["source"] == "book" and saved["book"]["title"] == "Joyful Mathematics"
    g = client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=bk["headers"]).json()
    assert g["book"]["title"] == "Joyful Mathematics" and g["book"]["grade"] == 3 and g["book"]["board"] == "NCERT"
    topics = g["book"]["chapters"][0]["topics"]
    assert topics[0]["checkpoint_id"] == "N.G1.count_to_20"
    # the custom topic was created on the syllabus, and the book record points at it
    custom = [t["checkpoint_id"] for ch in g["chapters"] for t in ch["topics"] if t["custom"]]
    assert topics[1]["checkpoint_id"] in custom and topics[1]["checkpoint_id"].startswith("C")
    assert g["totals"]["topics"] == 2 and g["confirmed"] is True
    # other subjects of the same class have no book
    assert client.get(f"/v1/classes/{cid}/syllabus?subject=literacy", headers=bk["headers"]).json()["book"] is None
    # saving later without a book keeps the last saved book
    r2 = client.post(f"/v1/classes/{cid}/syllabus", headers=bk["headers"],
                     json={"subject": "numeracy", "items": [{"checkpoint_id": "N.G1.count_to_20"}]})
    assert r2.status_code == 200 and r2.json()["book"]["title"] == "Joyful Mathematics"


def test_save_syllabus_without_book_still_works(client, bk):
    cid = bk["c2"]
    r = client.post(f"/v1/classes/{cid}/syllabus", headers=bk["headers"],
                    json={"subject": "numeracy", "source": "import", "items": [{"checkpoint_id": "N.G1.count_to_20"}]})
    assert r.status_code == 200, r.text
    assert r.json()["book"] is None and r.json()["source"] == "import"


@pytest.mark.parametrize("book", [
    {"title": "x" * 121}, {"title": "B", "grade": 9}, {"title": "B", "chapters": [{"title": ""}]},
    {"title": "B", "chapters": [{"title": f"c{n}"} for n in range(41)]},
])
def test_save_bad_book_is_422(client, bk, book):
    r = client.post(f"/v1/classes/{bk['c2']}/syllabus", headers=bk["headers"],
                    json={"subject": "numeracy", "source": "book", "items": [{"checkpoint_id": "N.G1.count_to_20"}],
                          "book": book})
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ llm.web_research
def test_web_research_resumes_pause_turn(fake_ai):
    msgs = fake_ai(research=[_search_resp("pause_turn"), _search_resp("end_turn", text="1. Ch — concepts")])
    with SessionLocal() as db:
        notes = llm.web_research(db, feature="book_research", prompt_version="v1", model="claude-sonnet-5",
                                 system="s", user="BOOK: X")
        logged = [a for a in db.new if isinstance(a, AiCall)]
    assert notes == "1. Ch — concepts"
    assert len(msgs.calls) == 2
    second = msgs.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]  # resumed with no extra "continue" message
    assert msgs.calls[1]["tools"][0]["type"] == "web_search_20260209"
    assert logged and logged[0].feature == "book_research" and logged[0].cost_inr > 0


def test_web_research_stops_after_two_continuations(fake_ai):
    msgs = fake_ai(research=[_search_resp("pause_turn")] * 3 + [_search_resp("end_turn", text="never")])
    with SessionLocal() as db:
        llm.web_research(db, feature="book_research", prompt_version="v1", model="claude-sonnet-5",
                         system="s", user="BOOK: X")
    assert len(msgs.calls) == 3


def test_web_research_error_object_gives_no_notes(fake_ai):
    fake_ai(research=[_search_resp("end_turn", text="I could not search, but from memory...", error=True)])
    with SessionLocal() as db:
        assert llm.web_research(db, feature="book_research", prompt_version="v1", model="claude-sonnet-5",
                                system="s", user="BOOK: X") == ""


def test_web_research_without_key_is_unavailable():
    with SessionLocal() as db, pytest.raises(llm.LLMUnavailable):
        llm.web_research(db, feature="book_research", prompt_version="v1", model="claude-sonnet-5",
                         system="s", user="BOOK: X")


def test_two_charges_in_one_request_share_one_usage_row():
    """Web research + structured call both charge the day's counter; the second must not insert a duplicate."""
    from sqlalchemy import select

    from app.models.tables import UsageCounter

    db = SessionLocal()
    try:
        school = School(name="Charge test", code=f"CH{uuid.uuid4().hex[:6]}")
        db.add(school)
        db.flush()
        llm._charge(db, school.id, 1.5)
        llm._charge(db, school.id, 2.0)
        db.commit()
        rows = db.scalars(select(UsageCounter).where(UsageCounter.school_id == school.id)).all()
        assert len(rows) == 1 and rows[0].cost_inr == 3.5
    finally:
        db.rollback()
        db.close()


def test_web_research_respects_time_budget(fake_ai, monkeypatch):
    """A slow search must not hold the request open: requests get only the time left, without SDK retries."""
    msgs = fake_ai(research=[_search_resp("pause_turn", text="1. Ch — concepts")] * 3)
    clock = iter([100.0, 100.0, 141.0, 141.0, 141.0, 141.0])  # second turn starts with 4 s of a 45 s budget left
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(clock, 141.0))
    with SessionLocal() as db:
        notes = llm.web_research(db, feature="book_research", prompt_version="v1", model="claude-sonnet-5",
                                 system="s", user="BOOK: X", time_budget_s=45)
    client = llm._client()
    assert len(msgs.calls) == 1  # stopped instead of resuming with too little time left
    assert client.options == [(45.0, 0)]
    assert notes == "1. Ch — concepts"  # the finished search is still used


def test_book_research_passes_configured_budget(client, bk, fake_ai, monkeypatch):
    seen = {}
    real = llm.web_research
    def spy(*a, **kw):
        seen["budget"] = kw.get("time_budget_s")
        return real(*a, **kw)
    monkeypatch.setattr(llm, "web_research", spy)
    monkeypatch.setattr(get_settings(), "book_research_timeout_s", 30.0)
    fake_ai(tool_inputs=[_model_map()], research=[_search_resp("end_turn", text="1. Mango Treat — counting")])
    r = client.post(f"/v1/classes/{bk['c2']}/books/map", headers=bk["headers"],
                    data={"subject": "numeracy", "book_title": "Joyful Mathematics", "book_grade": "2"})
    assert r.status_code == 200, r.text
    assert seen["budget"] == 30.0
