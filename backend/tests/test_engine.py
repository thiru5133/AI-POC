from app.ai.fake import FakeLLMProvider
from app.ai.base import LLMEvent, LLMProvider
from app.conversation.chunker import sentences
from app.conversation.context import ConversationContext
from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.domain.loader import load_profile_file, parse_profile
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

from .conftest import PROFILE, TENANT


def _ctx():
    return ConversationContext(session_id="s", tenant_id=TENANT, domain_profile_id=PROFILE)


async def _collect(agen):
    return [x async for x in agen]


async def test_engine_streams_reply():
    engine = ConversationEngine(FakeLLMProvider(lambda s, m: "Hello there."))
    profile = parse_profile(load_profile_file("hotel"))
    out = "".join(await _collect(engine.run_turn(profile, _ctx(), [], "hi")))
    assert out == "Hello there."


async def test_sentence_chunker_splits_and_keeps_decimals():
    async def deltas():
        for piece in ["It costs 2.", "5 dollars. Check", "-in is at 2 PM! Bye"]:
            yield piece

    assert await _collect(sentences(deltas())) == ["It costs 2.5 dollars.", "Check-in is at 2 PM!", "Bye"]


class _ToolThenAnswer(LLMProvider):
    def __init__(self):
        self.round = 0
        self.seen = []

    async def stream(self, system, messages, tools):
        self.seen.append(messages)
        self.round += 1
        if self.round == 1:
            yield LLMEvent(type="tool_use", tool_id="t1", tool_name="lookup", tool_input={"q": "x"})
        else:
            yield LLMEvent(type="text", text="Done.")


async def test_tool_loop_executes_backend_tool_not_llm():
    called = []

    async def handler(ctx, args):
        called.append(args)
        return {"value": 42}

    registry = ToolRegistry([Tool("lookup", "d", {"type": "object", "properties": {}}, handler)])
    llm = _ToolThenAnswer()
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["lookup"]})
    out = "".join(await _collect(ConversationEngine(llm, registry).run_turn(profile, _ctx(), [], "go")))
    assert out == "Done." and called == [{"q": "x"}]
    assert llm.seen[1][-1]["content"][0]["type"] == "tool_result"


async def test_tool_failure_is_reported_to_llm_not_raised():
    async def boom(ctx, args):
        raise RuntimeError("api down")

    registry = ToolRegistry([Tool("lookup", "d", {"type": "object", "properties": {}}, boom)])
    llm = _ToolThenAnswer()
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["lookup"]})
    await _collect(ConversationEngine(llm, registry).run_turn(profile, _ctx(), [], "go"))
    assert llm.seen[1][-1]["content"][0]["is_error"] is True


async def test_context_retained_across_turns(session_factory, llm):
    service = ConversationService(session_factory, ConversationEngine(llm))
    conv_id, greeting = await service.start(TENANT)
    assert greeting.startswith("Welcome to Demo Hotel")
    await service.reply(TENANT, conv_id, "I need a room from October 10th to 12th")
    await service.reply(TENANT, conv_id, "Two adults")
    second_call_messages = llm.calls[1]["messages"]
    contents = [m["content"] for m in second_call_messages]
    assert "I need a room from October 10th to 12th" in contents[0]  # earlier turn is in the prompt
    assert contents[-1] == "Two adults"
    assert second_call_messages[0]["role"] == "user"  # greeting dropped, roles alternate


def test_openai_message_translation():
    from app.ai.openai_compatible import to_openai_messages

    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"q": "x"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"v\": 1}"}]},
    ]
    out = to_openai_messages("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"q": "x"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "{\"v\": 1}"}


def test_factory_selects_groq_and_requires_key():
    import pytest
    from app.ai.factory import create_llm_provider
    from app.ai.openai_compatible import OpenAICompatibleProvider
    from app.core.config import Settings
    from app.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError):
        create_llm_provider(Settings(_env_file=None, llm_provider="groq", groq_api_key=""))
    provider = create_llm_provider(Settings(_env_file=None, llm_provider="groq", groq_api_key="k"))
    assert isinstance(provider, OpenAICompatibleProvider)
