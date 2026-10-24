from datetime import datetime

import httpx
import pytest
from pydantic import ValidationError

from app.conversation.context import ConversationContext
from app.conversation.prompt import build_system_prompt
from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError
from app.domain import hours as hrs
from app.domain.catalog import BY_KEY, PLATFORM_TOOLS, profile_config
from app.domain.loader import load_profile_file, parse_profile
from app.notifications import messaging
from app.notifications.messaging import ConsoleMessageSender, MessageSender, TwilioMessageSender, create_message_senders
from app.tools.builtin import MAX_CONFIRMATIONS_PER_CONVERSATION, builtin_tools

from .conftest import PROFILE, TENANT, RecordingEmailSender

WEEKDAYS = {d: "09:00-18:00" for d in ("mon", "tue", "wed", "thu", "fri")}


def ctx():
    return ConversationContext(session_id="s", tenant_id=TENANT, domain_profile_id=PROFILE)


# ---------- operating hours ----------
def test_is_open_and_next_opening():
    monday_noon = datetime(2026, 10, 19, 12, 0)  # a Monday
    saturday = datetime(2026, 10, 24, 12, 0)
    assert hrs.is_open(WEEKDAYS, monday_noon)
    assert not hrs.is_open(WEEKDAYS, monday_noon.replace(hour=18))  # closing time is exclusive
    assert not hrs.is_open(WEEKDAYS, saturday)
    assert hrs.next_opening(WEEKDAYS, monday_noon.replace(hour=7)) == "today at 09:00"
    assert hrs.next_opening(WEEKDAYS, monday_noon.replace(hour=20)) == "tomorrow at 09:00"
    assert hrs.next_opening(WEEKDAYS, saturday) == "Monday at 09:00"
    assert hrs.next_opening({}, saturday) is None


@pytest.mark.parametrize("bad", [{"mon": "9-5"}, {"mon": "18:00-09:00"}, {"funday": "09:00-10:00"}])
def test_invalid_hours_reject_the_profile(bad):
    config = load_profile_file("hotel")
    config["identity"]["hours"] = bad
    with pytest.raises(ValidationError):
        parse_profile(config)


def _prompt_at(monkeypatch, now: datetime, **identity):
    config = load_profile_file("hotel")
    config["identity"].update(hours=WEEKDAYS, timezone="UTC", **identity)
    monkeypatch.setattr("app.conversation.prompt._now", lambda tz: now)
    return build_system_prompt(parse_profile(config), ctx())


def test_prompt_says_open_during_hours(monkeypatch):
    prompt = _prompt_at(monkeypatch, datetime(2026, 10, 19, 12, 0))
    assert "The business is open right now." in prompt and "CLOSED" not in prompt


def test_prompt_says_closed_after_hours_with_reopening_and_guidance(monkeypatch):
    prompt = _prompt_at(monkeypatch, datetime(2026, 10, 24, 12, 0), afterHoursMessage="Offer to take a message.")
    assert "CLOSED right now" in prompt and "Monday at 09:00" in prompt and "Offer to take a message." in prompt


def test_no_hours_means_no_hours_text():
    prompt = build_system_prompt(parse_profile(load_profile_file("hotel")), ctx())
    assert "Operating hours" not in prompt and "CLOSED" not in prompt


# ---------- built-in tools ----------
class Recorder(MessageSender):
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, body):
        if self.fail:
            raise UpstreamError("down")
        self.sent.append((to, body))


def tools(**senders):
    return {t.name: t for t in builtin_tools(senders or {"sms": Recorder(), "whatsapp": Recorder(), "email": Recorder()})}


async def test_request_human_records_the_handoff():
    c = ctx()
    result = await tools()["request_human"].handler(c, {"reason": "billing dispute"})
    assert c.handoff_requested and c.handoff_reason == "billing dispute"
    assert result["status"] == "recorded" and "do not say they are being connected" in result["note"]


async def test_send_confirmation_sends_and_counts():
    sms = Recorder()
    c = ctx()
    out = await tools(sms=sms)["send_confirmation"].handler(c, {"channel": "sms", "to": "+91 98765-43210", "message": "Booked."})
    assert out == {"sent": True, "channel": "sms"}
    assert sms.sent == [("+919876543210", "Booked.")] and c.notifications_sent == 1


@pytest.mark.parametrize(
    "args",
    [
        {"channel": "fax", "to": "+919876543210", "message": "x"},
        {"channel": "sms", "to": "98765", "message": "x"},  # no country code
        {"channel": "email", "to": "not-an-email", "message": "x"},
        {"channel": "sms", "to": "+919876543210", "message": ""},
        {"channel": "sms", "to": "+919876543210", "message": "x" * 481},
    ],
)
async def test_send_confirmation_rejects_bad_input(args):
    sms = Recorder()
    out = await tools(sms=sms)["send_confirmation"].handler(ctx(), args)
    assert out["sent"] is False and not sms.sent


async def test_send_confirmation_sticks_to_the_first_contact_and_is_capped():
    sms, c = Recorder(), ctx()
    tool = tools(sms=sms)["send_confirmation"]
    first = {"channel": "sms", "to": "+919876543210", "message": "Booked."}
    assert (await tool.handler(c, first))["sent"] is True
    other = await tool.handler(c, {**first, "to": "+919000000000"})  # a different number: refused
    assert other["sent"] is False and len(sms.sent) == 1
    for _ in range(MAX_CONFIRMATIONS_PER_CONVERSATION - 1):
        assert (await tool.handler(c, first))["sent"] is True
    assert (await tool.handler(c, first))["sent"] is False  # over the cap
    assert len(sms.sent) == MAX_CONFIRMATIONS_PER_CONVERSATION


async def test_delivery_failure_is_reported_without_internal_detail():
    c = ctx()
    out = await tools(sms=Recorder(fail=True))["send_confirmation"].handler(
        c, {"channel": "sms", "to": "+919876543210", "message": "Booked."}
    )
    assert out == {"sent": False, "reason": "The message could not be delivered."} and c.notifications_sent == 0


def test_new_business_profiles_enable_the_platform_tools():
    config = profile_config(BY_KEY["fitness"], "FitZone Anna Nagar")
    assert config["enabledTools"] == list(PLATFORM_TOOLS)
    assert parse_profile(config).enabled_tools == list(PLATFORM_TOOLS)


# ---------- senders ----------
def twilio(**overrides) -> Settings:
    base = dict(twilio_account_sid="AC123", twilio_auth_token="tok", twilio_sms_from="+14155550100",
                twilio_whatsapp_from="+14155238886")
    return Settings(_env_file=None, **{**base, **overrides})


def test_sender_choice_depends_on_twilio_config():
    mail = RecordingEmailSender()
    configured = create_message_senders(twilio(), mail)
    assert isinstance(configured["sms"], TwilioMessageSender) and isinstance(configured["whatsapp"], TwilioMessageSender)
    unconfigured = create_message_senders(twilio(twilio_account_sid=""), mail)
    assert isinstance(unconfigured["sms"], ConsoleMessageSender)
    configured["email"].send("a@example.com", "Booked.")
    assert mail.sent[0][0] == "a@example.com"


def test_twilio_posts_sms_and_whatsapp(monkeypatch):
    seen = []

    def fake_post(url, data, auth, timeout):
        seen.append((url, data, auth))
        return httpx.Response(201)

    monkeypatch.setattr(messaging.httpx, "post", fake_post)
    TwilioMessageSender(twilio()).send("+919876543210", "Hi")
    TwilioMessageSender(twilio(), whatsapp=True).send("+919876543210", "Hi")
    assert seen[0][0].endswith("/Accounts/AC123/Messages.json") and seen[0][2] == ("AC123", "tok")
    assert seen[0][1] == {"To": "+919876543210", "From": "+14155550100", "Body": "Hi"}
    assert seen[1][1]["To"] == "whatsapp:+919876543210" and seen[1][1]["From"] == "whatsapp:+14155238886"


def test_twilio_errors_and_missing_config(monkeypatch):
    monkeypatch.setattr(messaging.httpx, "post", lambda *a, **k: httpx.Response(400, text="bad"))
    with pytest.raises(UpstreamError, match=r"error \(400\)") as err:
        TwilioMessageSender(twilio()).send("+919876543210", "Hi")
    assert "tok" not in err.value.message

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(messaging.httpx, "post", boom)
    with pytest.raises(UpstreamError, match="could not be reached"):
        TwilioMessageSender(twilio()).send("+919876543210", "Hi")
    with pytest.raises(ConfigurationError, match="TWILIO_ACCOUNT_SID"):
        TwilioMessageSender(twilio(twilio_auth_token="")).send("+919876543210", "Hi")
    with pytest.raises(ConfigurationError, match="TWILIO_SMS_FROM"):
        TwilioMessageSender(twilio(twilio_sms_from="")).send("+919876543210", "Hi")


# ---------- a Trial Twilio account only accepts its own templates ----------
def _twilio_post(monkeypatch, replies):
    import httpx

    from app.notifications import messaging

    sent = []

    def post(url, data, auth, timeout):
        sent.append(data["Body"])
        status, body = replies.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(messaging.httpx, "post", post)
    return sent


def _settings():
    from app.core.config import Settings

    return Settings(_env_file=None, twilio_account_sid="AC1", twilio_auth_token="t", twilio_sms_from="+17372508034")


def test_a_trial_account_falls_back_to_the_template(monkeypatch):
    from app.notifications.messaging import TwilioMessageSender

    sent = _twilio_post(monkeypatch, [(400, {"code": 572006}), (201, {})])
    TwilioMessageSender(_settings()).send("+916383135741", "Your booking is confirmed.")
    assert sent == ["Your booking is confirmed.", "sms_order_confirmation"]


def test_staff_alerts_use_the_alert_template_and_other_errors_still_raise(monkeypatch):
    from app.core.errors import UpstreamError
    from app.notifications.messaging import create_alert_sms_sender

    sent = _twilio_post(monkeypatch, [(400, {"code": 572006}), (201, {})])
    create_alert_sms_sender(_settings()).send("+916383135741", "A caller needs a person.")
    assert sent[-1] == "sms_internal_alerts"
    _twilio_post(monkeypatch, [(400, {"code": 21211})])
    with pytest.raises(UpstreamError):
        create_alert_sms_sender(_settings()).send("+1", "x")
