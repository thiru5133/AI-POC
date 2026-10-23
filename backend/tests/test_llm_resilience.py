import httpx
import pytest
from openai import RateLimitError

from app.ai import openai_compatible as oc
from app.ai.base import LLMBusyError, LLMEvent
from app.conversation.engine import MAX_TOOL_RESULT_CHARS, ConversationEngine
from app.domain.loader import load_profile_file, parse_profile
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

from .test_engine import _collect, _ctx, _ToolThenAnswer


def _rate_limit(retry_after: str | None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "http://llm.test"))
    return RateLimitError("rate limited", response=response, body=None)


def test_retry_wait_follows_the_provider_but_never_beyond_a_phone_caller_s_patience():
    assert oc._retry_wait(_rate_limit("3")) == 3.0
    assert oc._retry_wait(_rate_limit(None)) == 2.0  # no hint: a short default
    assert oc._retry_wait(_rate_limit("900")) is None  # a daily quota will not clear in time


class _Stream:
    def __init__(self, text):
        self._text = text

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        from types import SimpleNamespace as NS

        yield NS(choices=[NS(delta=NS(content=self._text, tool_calls=None))])


def _provider(monkeypatch, outcomes):
    """A provider whose model calls fail or succeed in the order given."""
    provider = oc.OpenAICompatibleProvider("key", "model")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return _Stream(outcome)

    monkeypatch.setattr(provider._client.chat.completions, "create", create)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(oc.asyncio, "sleep", no_sleep)
    return provider, calls


async def _text(provider) -> str:
    return "".join([e.text async for e in provider.stream("sys", [{"role": "user", "content": "hi"}], []) if e.type == "text"])


async def test_a_passing_rate_limit_is_retried(monkeypatch):
    provider, calls = _provider(monkeypatch, [_rate_limit("1"), "Hello."])
    assert await _text(provider) == "Hello."
    assert len(calls) == 2


async def test_gives_up_with_busy_after_the_retries(monkeypatch):
    provider, calls = _provider(monkeypatch, [_rate_limit("1")] * (oc.MAX_RATE_LIMIT_RETRIES + 1))
    with pytest.raises(LLMBusyError):
        await _text(provider)
    assert len(calls) == oc.MAX_RATE_LIMIT_RETRIES + 1


async def test_a_long_wait_is_not_retried(monkeypatch):
    provider, calls = _provider(monkeypatch, [_rate_limit("900"), "never reached"])
    with pytest.raises(LLMBusyError):
        await _text(provider)
    assert len(calls) == 1


def test_provider_data_is_sent_back_with_the_tool_call():
    """Gemini 3 rejects a tool round trip unless the call's thought signature is echoed back."""
    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}, "provider_data": {"sig": "abc"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
    ]
    call = oc.to_openai_messages("sys", msgs)[2]["tool_calls"][0]
    assert call["extra_content"] == {"sig": "abc"}


async def test_a_huge_tool_result_is_cut_before_the_next_model_call():
    async def handler(ctx, args):
        return {"rooms": "x" * (MAX_TOOL_RESULT_CHARS * 3)}

    registry = ToolRegistry([Tool("lookup", "d", {"type": "object", "properties": {}}, handler)])
    llm = _ToolThenAnswer()
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["lookup"]})
    await _collect(ConversationEngine(llm, registry).run_turn(profile, _ctx(), [], "go"))
    assert len(llm.seen[1][-1]["content"][0]["content"]) == MAX_TOOL_RESULT_CHARS


async def test_provider_data_survives_the_tool_loop():
    class Signed(_ToolThenAnswer):
        async def stream(self, system, messages, tools):
            self.seen.append(list(messages))
            self.round += 1
            if self.round == 1:
                yield LLMEvent(type="tool_use", tool_id="t1", tool_name="lookup", tool_input={}, provider_data={"sig": "abc"})
            else:
                yield LLMEvent(type="text", text="Done.")

    async def handler(ctx, args):
        return {}

    registry = ToolRegistry([Tool("lookup", "d", {"type": "object", "properties": {}}, handler)])
    llm = Signed()
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["lookup"]})
    await _collect(ConversationEngine(llm, registry).run_turn(profile, _ctx(), [], "go"))
    assert llm.seen[1][-2]["content"][0]["provider_data"] == {"sig": "abc"}
