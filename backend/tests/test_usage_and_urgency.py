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


# ---------- hanging up after a booking ----------
async def _spoken(tool_name, channel, final_text="Done."):
    from app.conversation.context import CALL_CLOSING  # noqa: F401

    async def ok(c, args):
        return {"ok": True}

    class _Llm(_CallsTool):
        async def stream(self, system, messages, tools):
            self.round += 1
            if self.round == 1:
                yield LLMEvent(type="tool_use", tool_id="t1", tool_name=self.tool, tool_input={})
            else:
                yield LLMEvent(type="text", text=final_text)

    registry = ToolRegistry([Tool(tool_name, "d", {"type": "object", "properties": {}}, ok)])
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": [tool_name]})
    c = ctx()
    c.channel = channel
    return "".join([x async for x in ConversationEngine(_Llm(tool_name), registry).run_turn(profile, c, [], "go")])


async def test_a_phone_call_says_goodbye_after_a_booking():
    from app.conversation.context import CALL_CLOSING

    assert (await _spoken("hotel__create_booking", "phone")).endswith(CALL_CLOSING)


async def test_no_goodbye_for_other_tools_chat_or_an_open_question():
    from app.conversation.context import CALL_CLOSING

    assert CALL_CLOSING not in await _spoken("hotel__search_rooms", "phone")
    assert CALL_CLOSING not in await _spoken("hotel__create_booking", "web")
    assert CALL_CLOSING not in await _spoken("hotel__create_booking", "phone", "Booked. Want an email?")


def test_vapi_assistant_ends_the_call_on_the_closing_phrase():
    from app.conversation.context import CALL_CLOSING
    from app.core.config import get_settings
    from app.voice import vapi

    profile = parse_profile(load_profile_file("hotel"))
    assert vapi.assistant_config(get_settings(), profile, "https://x/llm")["endCallPhrases"] == [CALL_CLOSING]


# ---------- the caller is texted automatically after a booking ----------
async def _booked_call(channel_setting, ctx_channel="phone", caller="+919000011122", output=None, enabled=True):
    from app.notifications.messaging import MessageSender

    class Rec(MessageSender):
        def __init__(self):
            self.sent = []

        def send(self, to, body):
            self.sent.append((to, body))

    sms, wa = Rec(), Rec()
    output = output or {"reference": "HB-1", "hotel_name": "Holiday Kandy Hills", "check_in": "2026-10-24", "check_out": "2026-10-25", "total_price": 140}

    async def book(c, args):
        return output

    registry = ToolRegistry([*builtin_tools({"sms": sms, "whatsapp": wa, "email": Rec()}), Tool("hotel__book_room", "d", {"type": "object", "properties": {}}, book)])
    names = ["hotel__book_room", *(["send_confirmation"] if enabled else [])]
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": names})
    c = ctx()
    c.channel, c.caller.phone = ctx_channel, caller
    engine = ConversationEngine(_CallsTool("hotel__book_room"), registry, confirmation_channel=channel_setting)
    _ = [x async for x in engine.run_turn(profile, c, [], "book it")]
    return c, sms, wa


async def test_a_phone_booking_texts_the_callers_own_number():
    c, sms, _ = await _booked_call("sms")
    (to, body), = sms.sent
    assert to == "+919000011122" and "HB-1" in body and "hotel name Holiday Kandy Hills" in body
    assert "check in 2026-10-24" in body and "check out 2026-10-25" in body and "Total 140" in body
    assert c.notifications_sent == 1 and (usage.CONFIRMATION, 1) in c.usage_log


async def test_the_channel_can_be_whatsapp():
    _, sms, wa = await _booked_call("whatsapp")
    assert sms.sent == [] and len(wa.sent) == 1


async def test_no_text_when_off_on_chat_without_caller_id_or_without_the_tool():
    for kwargs in ({"channel_setting": ""}, {"channel_setting": "sms", "ctx_channel": "web"}, {"channel_setting": "sms", "caller": None}, {"channel_setting": "sms", "enabled": False}):
        _, sms, wa = await _booked_call(**kwargs)
        assert sms.sent == [] and wa.sent == []


# ---------- no double booking, and an email when the text cannot be delivered ----------
async def _book_twice(sms_fails):
    from app.core.errors import UpstreamError
    from app.notifications.messaging import MessageSender

    class Rec(MessageSender):
        def __init__(self, fail=False):
            self.sent, self.fail = [], fail

        def send(self, to, body):
            if self.fail:
                raise UpstreamError("trial")
            self.sent.append((to, body))

    sms, email = Rec(sms_fails), Rec()
    made = []

    async def book(c, args):
        made.append(args)
        return {"reference": "HB-1", "hotel_name": "Holiday Colombo", "guest_email": "guest@example.com", "total_price": 200}

    class Twice(LLMProvider):
        def __init__(self):
            self.round = 0

        async def stream(self, system, messages, tools):
            self.round += 1
            if self.round in (1, 3):
                yield LLMEvent(type="tool_use", tool_id=f"t{self.round}", tool_name="hotel__book_room", tool_input={"a": 1})
            else:
                yield LLMEvent(type="text", text="Booked.")

    registry = ToolRegistry([*builtin_tools({"sms": sms, "whatsapp": Rec(), "email": email}), Tool("hotel__book_room", "d", {"type": "object", "properties": {}}, book)])
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["hotel__book_room", "send_confirmation"]})
    c = ctx()
    c.channel, c.caller.phone = "phone", "+919000011122"
    engine = ConversationEngine(Twice(), registry, confirmation_channel="sms")
    for _ in range(2):  # the same request twice, as when a caller says "book it" again
        _ = [x async for x in engine.run_turn(profile, c, [], "book it")]
        engine.llm.round = 0  # a fresh answer sequence for the next request
    return made, sms, email


async def test_the_same_booking_is_not_made_twice():
    made, _, _ = await _book_twice(sms_fails=False)
    assert len(made) == 1


async def test_when_the_text_fails_no_email_is_sent_instead():
    _, sms, email = await _book_twice(sms_fails=True)
    assert email.sent == [] and sms.sent == []  # the caller asked for a text, so nothing else is sent in its place


def test_the_vapi_assistant_has_an_end_call_tool_and_the_stream_can_hang_up():
    import json as _json

    from app.core.config import get_settings
    from app.voice import vapi

    profile = parse_profile(load_profile_file("hotel"))
    assert vapi.assistant_config(get_settings(), profile, "https://x/llm")["model"]["tools"] == [{"type": "endCall"}]
    chunk = _json.loads(vapi.sse_end_call_chunk()[6:])
    call = chunk["choices"][0]["delta"]["tool_calls"][0]
    assert call["function"]["name"] == "endCall" and chunk["choices"][0]["finish_reason"] == "tool_calls"


# ---------- a promised look-up must actually happen ----------
class _Stalls(LLMProvider):
    """Promises to check, calls nothing; only after being told to does it call the tool and answer."""

    def __init__(self, stalls=True):
        self.stalls, self.round, self.nudged = stalls, 0, False

    async def stream(self, system, messages, tools):
        self.round += 1
        if any(isinstance(m["content"], str) and m["content"].startswith("You said you would look") for m in messages):
            self.nudged = True
        called = any(isinstance(m["content"], list) and any(b.get("type") == "tool_result" for b in m["content"]) for m in messages)
        if called:
            yield LLMEvent(type="text", text=" We have a standard option at 210 dollars.")
        elif self.nudged:
            yield LLMEvent(type="tool_use", tool_id="t1", tool_name="hotel__search_rooms", tool_input={})
        elif self.stalls:
            yield LLMEvent(type="text", text="Got it. I'll check the availability for you. One moment, please.")
        else:
            yield LLMEvent(type="text", text="Which date would you like?")


async def _stalled(stalls, tools=True):
    seen = []

    async def search(c, args):
        seen.append(args)
        return {"options": 1}

    registry = ToolRegistry([Tool("hotel__search_rooms", "d", {"type": "object", "properties": {}}, search)] if tools else [])
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["hotel__search_rooms"] if tools else []})
    c = ctx()
    llm = _Stalls(stalls)
    text = "".join([x async for x in ConversationEngine(llm, registry).run_turn(profile, c, [], "two guests")])
    return text, seen


async def test_a_promise_to_check_without_a_tool_call_is_followed_up():
    text, seen = await _stalled(stalls=True)
    assert len(seen) == 1 and text.startswith("Got it.") and text.endswith("210 dollars.")


async def test_no_nudge_when_nothing_was_promised_or_no_tools_exist():
    text, seen = await _stalled(stalls=False)
    assert seen == [] and text == "Which date would you like?"
    text, seen = await _stalled(stalls=True, tools=False)
    assert seen == [] and "One moment" in text


@pytest.mark.parametrize(
    "text,stalls",
    [
        ("I'll need to check availability for a room for two guests. Let me do that for you.", True),
        ("Got it. I'll check the availability for you. One moment, please.", True),
        ("Let me quickly check the availability for your stay. Just a moment, please.", True),
        ("I'll book that for you now.", True),
        ("Please hold on while I look that up.", True),
        ("Check-in starts at 2 PM.", False),
        ("Your booking is confirmed. Thank you for calling. Goodbye.", False),
        ("I found availability. The standard option is 210 dollars.", False),
        ("Could you please provide the check-in and check-out dates?", False),
        ("A staff member will follow up with you shortly.", False),
    ],
)
def test_which_replies_count_as_promising_a_look_up(text, stalls):
    from app.conversation.engine import _STALLING

    assert bool(_STALLING.search(text)) is stalls


async def test_a_question_that_mentions_a_moment_is_not_chased():
    text, seen = await _stalled(stalls=False)
    assert seen == []  # a plain question gets no follow-up either


# ---------- one goodbye, and an honest note about how the confirmation went ----------
async def test_no_second_goodbye_when_the_assistant_already_said_it():
    from app.conversation.context import CALL_CLOSING

    text = await _spoken("hotel__create_booking", "phone", "Your booking is confirmed. Thank you for calling. Goodbye.")
    assert text.count("Goodbye") == 1 and CALL_CLOSING in text


async def test_the_assistant_is_told_the_text_failed_and_nothing_goes_by_email():
    from app.core.errors import UpstreamError
    from app.notifications.messaging import MessageSender

    class Down(MessageSender):
        def send(self, to, body):
            raise UpstreamError("trial")

    class Mail(MessageSender):
        def __init__(self):
            self.sent = []

        def send(self, to, body):
            self.sent.append(to)

    mail, results = Mail(), []

    async def book(c, args):
        return {"reference": "HB-1", "guest_email": "drew@example.com"}

    class Llm(LLMProvider):
        def __init__(self):
            self.round = 0

        async def stream(self, system, messages, tools):
            self.round += 1
            if self.round == 1:
                yield LLMEvent(type="tool_use", tool_id="t", tool_name="hotel__book_room", tool_input={"a": 1})
            else:
                results.extend(m["content"] for m in messages if isinstance(m["content"], list))
                yield LLMEvent(type="text", text="Done.")

    registry = ToolRegistry([*builtin_tools({"sms": Down(), "whatsapp": Down(), "email": mail}), Tool("hotel__book_room", "d", {"type": "object", "properties": {}}, book)])
    profile = parse_profile({**load_profile_file("hotel"), "enabledTools": ["hotel__book_room", "send_confirmation"]})
    c = ctx()
    c.channel, c.caller.phone = "phone", "+919000011122"
    _ = [x async for x in ConversationEngine(Llm(), registry, confirmation_channel="sms").run_turn(profile, c, [], "go")]
    assert mail.sent == [] and "could NOT be delivered" in str(results[-1])
