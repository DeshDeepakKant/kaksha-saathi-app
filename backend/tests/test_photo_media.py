"""Photos arrive as application/octet-stream from phones; the server must send Claude the real type."""
import io

from PIL import Image

from app.ai import features
from app.ai.features import Proposal


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    return buf.getvalue()


def test_index_photo_sends_real_media_type(client, teacher_headers, monkeypatch):
    seen = {}

    def fake(session, **kw):
        seen["mt"] = kw["media_type"]
        return Proposal("roadmap", {"chapters": []}, "fallback")
    monkeypatch.setattr(features, "draft_roadmap", fake)
    r = client.post("/v1/classes/1/roadmap/draft", headers=teacher_headers, data={"subject": "numeracy"},
                    files={"image": ("index.jpg", _jpeg(), "application/octet-stream")})
    assert r.status_code == 200 and seen["mt"] == "image/jpeg"


def test_work_photo_sends_real_media_type(client, teacher_headers, monkeypatch):
    seen = {}

    def fake(session, **kw):
        seen["mt"] = kw["media_type"]
        return Proposal("photo", {"page": {}, "questions": []}, "fallback")
    monkeypatch.setattr(features, "analyze_photo", fake)
    r = client.post("/v1/classes/1/captures/photo", headers=teacher_headers,
                    data={"child_id": "1", "subject": "numeracy"},
                    files={"image": ("work.png", _png(), "application/octet-stream")})
    assert r.status_code == 200 and seen["mt"] == "image/png"


def test_unsupported_photo_format_is_422(client, teacher_headers):
    r = client.post("/v1/classes/1/roadmap/draft", headers=teacher_headers, data={"subject": "numeracy"},
                    files={"image": ("index.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64, "image/heic")})
    assert r.status_code == 422
