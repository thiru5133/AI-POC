import pytest

from app import usage
from app.ai.base import LLMEvent, LLMProvider
from app.conversation.context import ConversationContext
from app.conversation.engine import ConversationEngine
from app.conversation.prompt import build_system_prompt
from app.conversation.service import ConversationService
from app.domain.catalog import BY_KEY, profile_config
from app.domain.loader import load_profile_file, parse_profile
from app.models import Conversation
from app.repositories.usage import UsageRepository
from app.tools.base import Tool
from app.tools.builtin import builtin_tools
from app.tools.registry import ToolRegistry

from .conftest import PROFILE, TENANT, make_admin, make_tenant


def ctx():
    return ConversationContext(session_id="s", tenant_id=TENANT, domain_profile_id=PROFILE)


# ---------- usage metering ----------
@pytest.mark.parametrize(
    "name,expected",
    [
        ("book_class", True), ("gym__book_class", True), ("hotel__create_booking", True), ("reserve_table", True),
        ("schedule_visit", True), ("gym__search_sessions", False), ("cancel_booking", False), ("list_bookings", False),
    ],
)
def test_booking_tools_are_recognised_by_name(name, expected):
    assert usage.is_booking_tool(name) is expected


class _CallsTool(LLMProvider):
    def __init__(self, tool):
        self.tool, self.round = tool, 0

    async def stream(self, system, messages, tools):
        self.round += 1
        if self.round == 1:
            yield LLMEvent(type="tool_use", tool_id="t1", tool_name=self.tool, tool_input={})
        else:
            yield LLMEvent(type="text", text="Done.")


async def _run(tool_name, handler):
    registry = ToolRegistry([Tool(tool_name, "d", {"type": "object", "properties": {}}, handler)])
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": [tool_name]})
    c = ctx()
    _ = [x async for x in ConversationEngine(_CallsTool(tool_name), registry).run_turn(profile, c, [], "go")]
    return c.usage_log


async def test_successful_tool_calls_and_bookings_are_metered():
    async def ok(c, args):
        return {"ok": True}

    assert await _run("gym__book_class", ok) == [(usage.TOOL_CALL, 1), (usage.BOOKING, 1)]
    assert await _run("gym__search", ok) == [(usage.TOOL_CALL, 1)]


async def test_failed_tool_calls_are_not_metered():
    async def boom(c, args):
        raise RuntimeError("down")

    assert await _run("gym__book_class", boom) == []


def test_usage_is_counted_per_business_over_http(client, session_factory):
    a = make_admin(session_factory)
    b = make_admin(session_factory, make_tenant(session_factory, "Other Hotel"), "other@example.com")
    cid = client.post("/api/conversations", headers=a["headers"]).json()["id"]
    for text in ("hello", "any rooms?"):
        assert client.post(f"/api/conversations/{cid}/messages", json={"text": text}, headers=a["headers"]).status_code == 200
    mine = client.get("/api/org/usage", headers=a["headers"]).json()
    assert (mine["conversations"], mine["messages"], mine["periodDays"]) == (1, 2, 30)
    theirs = client.get("/api/org/usage", headers=b["headers"]).json()
    assert (theirs["conversations"], theirs["messages"]) == (0, 0)  # other businesses' usage is never included
    assert client.get("/api/org/usage").status_code == 401
    assert client.get("/api/org/usage?days=0", headers=a["headers"]).status_code == 422


async def test_voice_seconds_become_minutes(client, session_factory):
    a = make_admin(session_factory)
    cid = client.post("/api/conversations", headers=a["headers"]).json()["id"]
    service = ConversationService(session_factory, ConversationEngine(_CallsTool("x")))
    await service.record_usage(TENANT, cid, usage.VOICE_SECONDS, 150)
    assert client.get("/api/org/usage", headers=a["headers"]).json()["voiceMinutes"] == 2.5


def test_usage_repository_rejects_unknown_kinds(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError):
            UsageRepository(session, TENANT).record("bogus")


# ---------- urgency ----------
async def flag(c, level, reason="r"):
    return await {t.name: t for t in builtin_tools({})}["flag_urgency"].handler(c, {"level": level, "reason": reason})


async def test_emergency_is_flagged_and_requests_a_person():
    c = ctx()
    out = await flag(c, "emergency", "chest pain")
    assert (c.urgency, c.urgency_reason, c.handoff_requested) == ("emergency", "chest pain", True)
    assert out["recorded"] is True and "EMERGENCY" in out["note"]


async def test_frustration_does_not_request_a_person_and_urgency_is_only_raised():
    c = ctx()
    await flag(c, "frustrated")
    assert (c.urgency, c.handoff_requested) == ("frustrated", False)
    await flag(c, "urgent")
    await flag(c, "frustrated", "later")  # a lower level never overwrites a higher one
    assert (c.urgency, c.handoff_requested) == ("urgent", True)


async def test_unknown_level_is_rejected():
    c = ctx()
    assert (await flag(c, "panic"))["recorded"] is False and c.urgency == "normal"


def test_hospital_profile_has_the_emergency_rule_others_do_not():
    hospital = parse_profile(profile_config(BY_KEY["hospital"], "City Care"))
    fitness = parse_profile(profile_config(BY_KEY["fitness"], "FitZone"))
    assert "112" in hospital.identity.emergency_guidance and not fitness.identity.emergency_guidance
    assert "EMERGENCY (" in build_system_prompt(hospital, ctx())
    assert "EMERGENCY (" not in build_system_prompt(fitness, ctx())
    assert "call flag_urgency" in build_system_prompt(hospital, ctx())


def test_prompt_remembers_the_callers_state():
    c = ctx()
    c.urgency, c.urgency_reason = "urgent", "child has a fever"
    prompt = build_system_prompt(parse_profile(profile_config(BY_KEY["hospital"], "City Care")), c)
    assert "CALLER STATE: urgent (child has a fever)" in prompt
    assert "CALLER STATE" not in build_system_prompt(parse_profile(load_profile_file("hotel")), ctx())


def test_conversation_list_shows_urgency_and_handoff(client, session_factory):
    a = make_admin(session_factory)
    cid = client.post("/api/conversations", headers=a["headers"]).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"text": "help"}, headers=a["headers"])
    with session_factory() as session:
        conv = session.get(Conversation, cid)
        conv.context = {**conv.context, "urgency": "emergency", "handoff_requested": True}
        session.commit()
    item = client.get("/api/conversations", headers=a["headers"]).json()["items"][0]
    assert item["urgency"] == "emergency" and item["handoffRequested"] is True
