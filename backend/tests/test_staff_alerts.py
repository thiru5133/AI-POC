import asyncio

import pytest

from app.ai.base import LLMBusyError, LLMEvent, LLMProvider
from app.conversation import service as svc
from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService, accepts_offer
from app.core.errors import UpstreamError
from app.notifications.messaging import MessageSender
from app.notifications.staff import StaffAlerts
from app.repositories.phone import PhoneRepository

from .conftest import TENANT, RecordingEmailSender, make_admin

HUMAN = "+919876543210"


class RecordingSms(MessageSender):
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, body):
        if self.fail:
            raise UpstreamError("down")
        self.sent.append((to, body))


class BrokenThenFine(LLMProvider):
    """Fails for the first `broken` turns, then answers."""

    def __init__(self, broken=1):
        self.broken = broken

    async def stream(self, system, messages, tools):
        if self.broken:
            self.broken -= 1
            raise RuntimeError("llm is down")
        yield LLMEvent(type="text", text="Check-in starts at 2 PM.")


def build(session_factory, llm, sms=None, email=None):
    sms, email = sms or RecordingSms(), email or RecordingEmailSender()
    return ConversationService(session_factory, ConversationEngine(llm), StaffAlerts(session_factory, sms, email)), sms, email


async def call(service, transfer_available=True):
    conv_id, _ = await service.start(TENANT)
    await service.update_context(TENANT, conv_id, {"channel": "phone", "transfer_available": transfer_available, "caller": {"phone": "+919000011122"}})
    return conv_id


async def settle(service):
    await asyncio.gather(*service._tasks)


@pytest.fixture
def staff(session_factory):
    with session_factory() as session:
        PhoneRepository(session, TENANT).save("+914412345678", HUMAN)
        session.commit()
    make_admin(session_factory, TENANT, "owner@example.com")


@pytest.mark.parametrize("text,expected", [("yes please", True), ("Yeah, sure", True), ("ok connect me", True), ("no thanks", False), ("no, I don't want that", False), ("what time is check-in", False), ("", False)])
def test_only_a_clear_yes_accepts_the_offer(text, expected):
    assert accepts_offer(text) is expected


async def test_a_broken_assistant_says_so_and_offers_a_person(session_factory, staff):
    service, sms, _ = build(session_factory, BrokenThenFine())
    conv_id = await call(service)
    assert await service.reply(TENANT, conv_id, "Is there a room?") == svc.OFFER_TRANSFER
    await settle(service)
    assert sms.sent == []  # nobody is pinged until the caller says yes
    state = await service.get(TENANT, conv_id)
    assert state["context"]["pending_offer"] and not state["context"]["handoff_requested"]


async def test_yes_connects_and_pings_the_business(session_factory, staff):
    service, sms, email = build(session_factory, BrokenThenFine(broken=5))  # still broken: the answer must not need it
    conv_id = await call(service)
    await service.reply(TENANT, conv_id, "Is there a room?")
    assert await service.reply(TENANT, conv_id, "yes please") == svc.ACCEPTED_TRANSFER
    await settle(service)
    state = await service.get(TENANT, conv_id)
    assert state["context"]["handoff_requested"] and state["context"]["pending_offer"] is None
    assert [to for to, _ in sms.sent] == [HUMAN] and "+919000011122" in sms.sent[0][1] and "system problem" in sms.sent[0][1]
    assert [to for to, _, _ in email.sent] == ["owner@example.com"]


async def test_when_nobody_can_take_the_call_the_caller_is_promised_a_callback(session_factory, staff):
    service, sms, _ = build(session_factory, BrokenThenFine(broken=5))
    conv_id = await call(service, transfer_available=False)
    assert await service.reply(TENANT, conv_id, "Is there a room?") == svc.OFFER_CALLBACK
    assert await service.reply(TENANT, conv_id, "yes") == svc.ACCEPTED_CALLBACK
    await settle(service)
    assert len(sms.sent) == 1  # the business is still told, so they can call back


async def test_no_carries_on_with_the_assistant_and_pings_nobody(session_factory, staff):
    service, sms, email = build(session_factory, BrokenThenFine(broken=1))
    conv_id = await call(service)
    await service.reply(TENANT, conv_id, "Is there a room?")
    assert await service.reply(TENANT, conv_id, "no, what time is check-in?") == "Check-in starts at 2 PM."
    await settle(service)
    assert sms.sent == [] and email.sent == []


async def test_the_business_is_pinged_once_per_conversation(session_factory, staff):
    service, sms, _ = build(session_factory, BrokenThenFine(broken=9))
    conv_id = await call(service)
    for text in ("hello", "yes", "hello again", "yes"):
        await service.reply(TENANT, conv_id, text)
    await settle(service)
    assert len(sms.sent) == 1


def test_a_failing_ping_never_raises(session_factory, staff):
    alerts = StaffAlerts(session_factory, RecordingSms(fail=True), RecordingEmailSender())
    alerts._email.fail = True
    alerts.send(TENANT, "Demo Hotel", "Needs a person.", None)  # both channels fail; nothing propagates


# ---------- a rate-limited model is not a broken assistant ----------
class RateLimited(LLMProvider):
    async def stream(self, system, messages, tools):
        raise LLMBusyError("429")
        yield  # pragma: no cover  (makes this an async generator)


async def test_a_rate_limited_model_asks_to_repeat_and_does_not_offer_or_ping(session_factory, staff):
    service, sms, email = build(session_factory, RateLimited())
    conv_id = await call(service)
    assert await service.reply(TENANT, conv_id, "Is there a room?") == svc.BUSY_REPLY
    await settle(service)
    state = await service.get(TENANT, conv_id)
    assert state["context"]["pending_offer"] is None and not state["context"]["handoff_requested"]
    assert sms.sent == [] and email.sent == []


async def test_the_openai_client_does_not_wait_out_a_rate_limit():
    import httpx
    from openai import RateLimitError

    from app.ai.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider("key", "model", "http://localhost:1")
    assert provider._client.max_retries == 0  # a retry would sleep 10-20 s in the middle of a call

    async def limited(**kwargs):
        raise RateLimitError("slow down", response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)

    provider._client.chat.completions.create = limited
    with pytest.raises(LLMBusyError):
        async for _ in provider.stream("system", [{"role": "user", "content": "hi"}], []):
            pass


# ---------- what the admin is told, and what happens when nothing arrives ----------
def test_the_email_has_the_callers_number_the_time_and_a_link(session_factory, staff, caplog):
    email = RecordingEmailSender()
    alerts = StaffAlerts(session_factory, RecordingSms(), email, "https://app.example.com/")
    assert alerts.send(TENANT, "Demo Hotel", "The booking system is down.", "+919000011122", "conv-1", "Booking problem") is True
    (to, subject, body), = email.sent
    assert to == "owner@example.com" and subject == "Booking problem"
    assert "+919000011122" in body and "UTC" in body and "https://app.example.com/conversations/conv-1" in body


def test_one_working_channel_is_enough(session_factory, staff, caplog):
    alerts = StaffAlerts(session_factory, RecordingSms(fail=True), RecordingEmailSender())
    with caplog.at_level("ERROR"):
        assert alerts.send(TENANT, "Demo Hotel", "r", None) is True
    assert "NOT delivered" not in caplog.text


def test_when_nothing_arrives_it_is_logged_as_an_error(session_factory, staff, caplog):
    email = RecordingEmailSender()
    email.fail = True
    alerts = StaffAlerts(session_factory, RecordingSms(fail=True), email)
    with caplog.at_level("ERROR"):
        assert alerts.send(TENANT, "Demo Hotel", "r", "+919000011122") is False
    assert "NOT delivered" in caplog.text
