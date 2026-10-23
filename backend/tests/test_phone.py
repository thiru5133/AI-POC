import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from app.ai.base import LLMEvent, LLMProvider
from app.api import deps
from app.auth.security import create_access_token, decode_access_token
from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError, UpstreamError
from app.main import app
from app.models import Conversation
from app.voice import phone

from .conftest import make_admin, make_tenant

SECRET = get_settings().jwt_secret
BASE = "https://abc.example.app"
DIALLED = "+914412345678"
HUMAN = "+919876543210"
CALLER = "+919000011122"


def phone_settings(**over) -> Settings:
    base = dict(public_base_url=BASE, twilio_auth_token="tok", twilio_account_sid="AC1", jwt_secret=SECRET)
    return Settings(_env_file=None, **{**base, **over})


@pytest.fixture
def configured(client):
    app.dependency_overrides[get_settings] = lambda: phone_settings()


class RecordingCallControl(phone.CallControl):
    def __init__(self, fail=False):
        self.transfers, self.fail = [], fail

    def transfer(self, call_sid, to):
        if self.fail:
            raise UpstreamError("down")
        self.transfers.append((call_sid, to))


@pytest.fixture
def control(client):
    ctl = RecordingCallControl()
    app.dependency_overrides[deps.get_call_control] = lambda: ctl
    return ctl


def sign(form: dict, url: str = BASE + "/api/phone/incoming", token: str = "tok") -> str:
    data = url + "".join(f"{k}{form[k]}" for k in sorted(form))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def call(client, form: dict, signature: str | None = None):
    return client.post(
        "/api/phone/incoming",
        content=urlencode(form),
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature if signature is not None else sign(form)},
    )


def business(session_factory, client, name="FitZone Anna Nagar", domain="fitness", transfer=HUMAN, number=DIALLED):
    tenant = make_tenant(session_factory, name, domain)
    admin = make_admin(session_factory, tenant, f"{name.split()[-1].lower()}@example.com")
    body = {"number": number, "transferNumber": transfer}
    assert client.put("/api/org/phone", json=body, headers=admin["headers"]).status_code == 200
    return tenant, admin


# ---------- helpers ----------
@pytest.mark.parametrize(
    "raw,expected",
    [("+91 44-1234 5678", "+914412345678"), ("+14155550100", "+14155550100"), ("(415) 555", None), ("anonymous", None), ("", None), (None, None)],
)
def test_phone_numbers_are_normalised(raw, expected):
    assert phone.normalize_phone(raw) == expected


def test_signature_matches_the_twilio_algorithm_and_detects_tampering():
    form = {"To": DIALLED, "From": CALLER, "CallSid": "CA1"}
    sig = sign(form)
    assert phone.twilio_signature("tok", BASE + "/api/phone/incoming", form) == sig
    assert phone.valid_twilio_signature("tok", BASE + "/api/phone/incoming", form, sig)
    assert not phone.valid_twilio_signature("tok", BASE + "/api/phone/incoming", {**form, "To": "+1"}, sig)
    assert not phone.valid_twilio_signature("other", BASE + "/api/phone/incoming", form, sig)
    assert not phone.valid_twilio_signature("tok", BASE + "/api/phone/incoming", form, "")


def test_stream_tokens_are_not_interchangeable_with_login_tokens():
    s = phone_settings()
    token = phone.create_stream_token(s, "t1", "c1", HUMAN)
    claims = phone.read_stream_token(s, token)
    assert (claims["tid"], claims["cid"], claims["xfer"]) == ("t1", "c1", HUMAN)
    with pytest.raises(UnauthorizedError):
        decode_access_token(s, token)  # a stream token is not a login
    with pytest.raises(jwt.PyJWTError):
        phone.read_stream_token(s, create_access_token(s, "u1", "admin", "t1"))  # and a login is not a stream token
    expired = jwt.encode({"aud": phone.TOKEN_AUDIENCE, "tid": "t", "cid": "c", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, SECRET, "HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        phone.read_stream_token(s, expired)


# ---------- the webhook ----------
def test_webhook_needs_public_url_and_credentials(client):
    assert call(client, {"To": DIALLED}, "x").status_code == 500


def test_webhook_rejects_a_bad_signature(client, configured):
    form = {"To": DIALLED, "From": CALLER, "CallSid": "CA1"}
    assert call(client, form, "bogus").status_code == 403
    assert call(client, form, sign(form, token="wrong")).status_code == 403
    assert call(client, form, sign(form, url="https://evil.example/api/phone/incoming")).status_code == 403


def test_unknown_number_gets_a_polite_goodbye(client, configured):
    form = {"To": "+910000000000", "From": CALLER, "CallSid": "CA1"}
    resp = call(client, form)
    assert resp.status_code == 200 and "not in service" in resp.text and "<Hangup/>" in resp.text


def test_known_number_opens_a_stream_for_its_own_business(client, configured, session_factory):
    tenant, _ = business(session_factory, client)
    form = {"To": DIALLED, "From": CALLER, "CallSid": "CA42"}
    resp = call(client, form)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/xml")
    assert f'<Stream url="wss://abc.example.app/ws/phone">' in resp.text
    claims = phone.read_stream_token(phone_settings(), re.search(r'name="token" value="([^"]+)"', resp.text).group(1))
    assert claims["tid"] == tenant and claims["xfer"] == HUMAN
    with session_factory() as session:
        conv = session.get(Conversation, claims["cid"])
        assert conv.tenant_id == tenant and conv.user_id is None
        assert conv.context["channel"] == "phone" and conv.context["call_sid"] == "CA42"
        assert conv.context["caller"]["phone"] == CALLER and conv.context["transfer_available"] is True


def test_no_transfer_when_the_business_is_closed_or_has_no_transfer_number(client, configured, session_factory):
    form = {"To": DIALLED, "From": CALLER, "CallSid": "CA1"}
    tenant, _ = business(session_factory, client, transfer=None)
    resp = call(client, form)
    assert phone.read_stream_token(phone_settings(), re.search(r'value="([^"]+)"/></Stream>', resp.text).group(1))["xfer"] is None

    from app.models import DomainProfileRow
    from sqlalchemy import select

    other, _ = business(session_factory, client, "Night Gym", number="+914499998888")
    with session_factory() as session:  # closed every day
        row = session.scalars(select(DomainProfileRow).where(DomainProfileRow.tenant_id == other)).first()
        row.config = {**row.config, "identity": {**row.config["identity"], "hours": {"mon": "closed"}}}
        session.commit()
    resp = call(client, {**form, "To": "+914499998888"}, None)
    assert phone.read_stream_token(phone_settings(), re.search(r'value="([^"]+)"/></Stream>', resp.text).group(1))["xfer"] is None


# ---------- the business's own phone settings ----------
def test_admin_sets_reads_and_clears_the_business_number(client, configured, session_factory):
    tenant, admin = business(session_factory, client)
    got = client.get("/api/org/phone", headers=admin["headers"]).json()
    assert got == {
        "number": DIALLED,
        "transferNumber": HUMAN,
        "domainName": "Fitness & gyms",
        "domainNumber": None,
        "provider": "twilio",
        "webhookUrl": BASE + "/api/phone/incoming",
        "publicUrl": f"http://localhost:5173/call/{tenant}",
        "ready": True,
    }
    cleared = client.put("/api/org/phone", json={"number": None}, headers=admin["headers"]).json()
    assert cleared["number"] is None and cleared["publicUrl"] is None  # no number, nothing to share
    assert client.get("/api/org/phone", headers=admin["headers"]).json()["number"] is None


def test_phone_settings_validation_and_isolation(client, configured, session_factory):
    _, admin = business(session_factory, client)
    other = make_admin(session_factory, make_tenant(session_factory, "Other Gym", "fitness"), "other@example.com")
    put = lambda who, body: client.put("/api/org/phone", json=body, headers=who["headers"])
    assert put(other, {"number": DIALLED}).json()["error"]["code"] == "number_taken"  # numbers are unique across businesses
    assert put(admin, {"number": "12345"}).status_code == 422
    assert put(admin, {"number": DIALLED, "transferNumber": DIALLED}).json()["error"]["code"] == "transfer_loop"
    assert client.get("/api/org/phone", headers=other["headers"]).json()["number"] is None  # not the other business's
    assert client.get("/api/org/phone").status_code == 401


# ---------- the audio stream ----------
def wait_for(condition, seconds: float = 3.0) -> None:
    import time

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert condition(), "timed out"


def media(text: str) -> dict:
    return {"event": "media", "media": {"payload": base64.b64encode(text.encode()).decode()}}


def start(token: str) -> dict:
    return {"event": "start", "streamSid": "MZ1", "start": {"streamSid": "MZ1", "callSid": "CA42", "customParameters": {"token": token}}}


def audio_of(event: dict) -> str:
    assert event["event"] == "media" and event["streamSid"] == "MZ1"
    return base64.b64decode(event["media"]["payload"]).decode()


def open_stream(client, session_factory, **kw):
    tenant, admin = business(session_factory, client, **kw)
    resp = call(client, {"To": DIALLED, "From": CALLER, "CallSid": "CA42"})
    return tenant, admin, re.search(r'name="token" value="([^"]+)"', resp.text).group(1)


def test_a_call_is_greeted_and_answered_in_phone_audio(client, configured, control, session_factory, tts):
    tenant, admin, token = open_stream(client, session_factory)
    with client.websocket_connect("/ws/phone") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(start(token))
        assert audio_of(ws.receive_json()).startswith("AUDIO:Welcome to FitZone")  # the greeting, as audio
        ws.send_json(media("What time is the yoga class?"))
        assert audio_of(ws.receive_json()) == "AUDIO:Check-in starts at 2 PM."
        assert audio_of(ws.receive_json()) == "AUDIO:Anything else?"
        ws.send_json({"event": "stop"})
    messages = client.get("/api/conversations", headers=admin["headers"]).json()["items"][0]
    assert messages["messageCount"] == 3  # greeting, question, answer
    usage = client.get("/api/org/usage", headers=admin["headers"]).json()
    assert usage["conversations"] == 1 and usage["messages"] == 1


def test_the_stream_refuses_calls_without_a_valid_token(client, configured, control, session_factory):
    open_stream(client, session_factory)
    for bad in ("", "garbage", jwt.encode({"aud": "other", "tid": "t", "cid": "c"}, SECRET, "HS256")):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/phone") as ws:
            ws.send_json(start(bad))
            ws.receive_json()


class AsksForAPerson(LLMProvider):
    def __init__(self):
        self.round = 0

    async def stream(self, system, messages, tools):
        self.round += 1
        if self.round == 1:
            yield LLMEvent(type="tool_use", tool_id="t1", tool_name="request_human", tool_input={"reason": "wants a person"})
        else:
            yield LLMEvent(type="text", text="One moment, connecting you now.")


def test_a_call_is_handed_to_a_person_after_the_assistant_finishes_speaking(client, configured, control, session_factory):
    app.dependency_overrides[deps.get_llm] = lambda: AsksForAPerson()
    _, _, token = open_stream(client, session_factory)
    with client.websocket_connect("/ws/phone") as ws:
        ws.send_json(start(token))
        ws.receive_json()  # greeting
        ws.send_json(media("I want to talk to someone"))
        assert audio_of(ws.receive_json()) == "AUDIO:One moment, connecting you now."
        mark = ws.receive_json()
        assert mark["event"] == "mark" and mark["mark"]["name"] == "handoff"
        assert control.transfers == []  # not before the caller has heard the sentence
        ws.send_json({"event": "mark", "mark": {"name": "handoff"}})  # Twilio: the audio has been played
        wait_for(lambda: control.transfers)  # the call stays open until Twilio takes it over, so only then hang up
        ws.send_json({"event": "stop"})
    assert control.transfers == [("CA42", HUMAN)]


def test_a_failed_transfer_apologises_and_does_not_retry(client, configured, session_factory):
    ctl = RecordingCallControl(fail=True)
    app.dependency_overrides[deps.get_call_control] = lambda: ctl
    app.dependency_overrides[deps.get_llm] = lambda: AsksForAPerson()
    _, _, token = open_stream(client, session_factory)
    with client.websocket_connect("/ws/phone") as ws:
        ws.send_json(start(token))
        ws.receive_json()
        ws.send_json(media("a person please"))
        ws.receive_json()  # the assistant's sentence
        assert ws.receive_json()["event"] == "mark"
        ws.send_json({"event": "mark", "mark": {"name": "handoff"}})
        assert "couldn't connect you" in audio_of(ws.receive_json())
        ws.send_json({"event": "stop"})
    assert ctl.transfers == []


def test_twilio_call_control_posts_the_transfer(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, data, auth, timeout):
        seen.update(url=url, data=data, auth=auth)
        return httpx.Response(200)

    monkeypatch.setattr(phone.httpx, "post", fake_post)
    phone.TwilioCallControl(phone_settings()).transfer("CA42", HUMAN)
    assert seen["url"].endswith("/Accounts/AC1/Calls/CA42.json") and seen["auth"] == ("AC1", "tok")
    assert seen["data"] == {"Twiml": f"<Response><Dial>{HUMAN}</Dial></Response>"}
    monkeypatch.setattr(phone.httpx, "post", lambda *a, **k: httpx.Response(400, text="no"))
    with pytest.raises(UpstreamError, match=r"error \(400\)"):
        phone.TwilioCallControl(phone_settings()).transfer("CA42", HUMAN)
