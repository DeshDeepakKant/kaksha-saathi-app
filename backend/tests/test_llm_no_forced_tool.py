"""Claude 5.5 models 400 on a forced tool_choice or a temperature; llm.structured must adapt."""
from types import SimpleNamespace as NS

from app.ai import llm
from app.config import get_settings
from app.db import SessionLocal

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


class Msgs:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


class Client:
    def __init__(self, messages):
        self.messages = messages


def _tool(data):
    return NS(content=[NS(type="tool_use", id="t1", name="ret", input=data)],
              usage=NS(input_tokens=10, output_tokens=5))


def _text():
    return NS(content=[NS(type="text", text="here you go")], usage=NS(input_tokens=10, output_tokens=5))


def _run(monkeypatch, model, replies):
    msgs = Msgs(replies)
    monkeypatch.setattr(llm, "_client", lambda: Client(msgs))
    with SessionLocal() as s:
        res = llm.structured(s, feature="t", prompt_version="v1", model=model, system="sys", user="u",
                             schema=SCHEMA, tool_name="ret")
    return res, msgs.calls


def test_photo_model_is_sonnet_5_5():
    assert get_settings().model_photo == "claude-sonnet-5-5"


def test_sonnet_5_5_uses_auto_tool_choice_and_no_temperature(monkeypatch):
    res, calls = _run(monkeypatch, "claude-sonnet-5-5", [_tool({"a": 1})])
    assert res.data == {"a": 1}
    kw = calls[0]
    assert kw["tool_choice"] == {"type": "auto"}
    assert "temperature" not in kw
    assert "`ret` tool" in kw["system"][0]["text"]


def test_sonnet_5_5_retries_when_model_answers_in_text(monkeypatch):
    res, calls = _run(monkeypatch, "claude-sonnet-5-5", [_text(), _tool({"a": 2})])
    assert res.data == {"a": 2} and len(calls) == 2
    assert calls[1]["messages"][-1]["role"] == "user"


def test_older_models_still_force_the_tool(monkeypatch):
    _, calls = _run(monkeypatch, "claude-sonnet-5", [_tool({"a": 1})])
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "ret"}
