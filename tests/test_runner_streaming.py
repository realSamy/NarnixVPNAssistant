"""Tests for the streaming runner: draft throttling, stage signals, and the
final-answer delivery path.

These do not touch a real model: `create_agent` is swapped for a fake whose
`astream_events` yields a scripted event sequence, and the Worker is a stub
recording every callback. This makes the runner's streaming contract fully
deterministic and fast.
"""

import types

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.agents.runner import AgentRunner, _content_to_text, _final_output_text
from app.schemas.chat import ChatUser, MessageIn


class FakeAgent:
    def __init__(self, events):
        self.events = events
        self.calls: list = []

    async def astream_events(self, input, config=None, version="spec"):
        self.calls.append((input, config, version))
        for event in self.events:
            yield event


class FakeWorker:
    def __init__(self):
        self.drafts: list[tuple[int, str, int]] = []
        self.stages: list[tuple[int, str, int]] = []
        self.calls: list[dict] = []

    async def send_draft(self, chat_id, text, draft_id, can_stop=True, keep_on_stop=True):
        self.drafts.append((chat_id, text, draft_id))
        return True

    async def send_stage(self, chat_id, step, draft_id):
        self.stages.append((chat_id, step, draft_id))
        return True

    async def send_typing(self, chat_id, thread_id):
        return {}

    async def call(self, payload):
        self.calls.append(payload)
        return {"ok": True}


class FakeOutbox:
    async def enqueue(self, payload):
        pass


def _runner(worker):
    return AgentRunner(
        model=None,
        checkpointer=None,
        worker=worker,
        outbox=FakeOutbox(),
        search=None,
        fetcher=None,
    )


def _message():
    return MessageIn(
        chat_id=42,
        thread_id=7,
        user=ChatUser(id=1000, first_name="Ali", lang="en"),
        text="what is my plan?",
        message_count=1,
        message_limit=20,
    )


_EVENT = {
    "event": "on_chat_model_stream",
    "data": {"chunk": AIMessageChunk(content="I will check the catalog first.")},
}
_EVENT_TOOL = {"event": "on_tool_start", "data": {"input": {}}, "name": "get_packages"}
_EVENT_END = {
    "event": "on_chain_end",
    "data": {"output": {"messages": [AIMessage(content="Your plan is Premium.")]}},
}


def _wire(monkeypatch, events):
    monkeypatch.setattr("app.agents.runner.create_agent", lambda **kw: FakeAgent(events))
    monkeypatch.setattr(
        "app.agents.runner.config.get_settings",
        lambda: types.SimpleNamespace(draft_min_interval_ms=0),
    )


async def test_streaming_draft_stage_and_answer(monkeypatch):
    _wire(monkeypatch, [_EVENT, _EVENT_TOOL, _EVENT_END])
    worker = FakeWorker()
    runner = _runner(worker)

    await runner.schedule("session-1", _message())

    texts = [text for _, text, _ in worker.drafts]
    assert texts[0].startswith("Thinking")                       # seeded immediately
    assert "I will check the catalog first." in texts           # preamble drafted live
    assert "" in texts                                          # cleared before answer

    assert ("checking",) in {(stage,) for _, stage, _ in worker.stages}

    # Final answer = the on_chain_end AIMessage, not the preamble buffer.
    assert worker.calls[-1]["action"] == "answer"
    assert worker.calls[-1]["text"] == "Your plan is Premium."
    assert worker.calls[-1].get("parse_mode") == "html"


async def test_tool_start_resets_buffer(monkeypatch):
    # A post-tool token stream AFTER on_tool_start: with a buffer reset,
    # "post-tool text" is drafted on its own; the delivered answer is still
    # the on_chain_end message, proving the source is the final AIMessage.
    _wire(
        monkeypatch,
        [
            _EVENT,
            _EVENT_TOOL,
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content="post-tool text")},
            },
            _EVENT_END,
        ],
    )
    worker = FakeWorker()
    runner = _runner(worker)

    await runner.schedule("session-2", _message())

    texts = [text for _, text, _ in worker.drafts]
    assert "post-tool text" in texts
    assert worker.calls[-1]["text"] == "Your plan is Premium."


def test_content_to_text_blocks():
    assert _content_to_text("hi") == "hi"
    assert _content_to_text([{"text": "a"}, {"text": "b"}]) == "ab"
    assert _content_to_text(123) == ""


def test_final_output_text_extraction():
    assert _final_output_text({"messages": [AIMessage(content=[{"text": "x"}])]}) == "x"
    assert _final_output_text(AIMessage(content="direct")) == "direct"
    assert _final_output_text({}) == ""
    assert _final_output_text("plain string") == ""
