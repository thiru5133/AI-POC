import json

import jwt
import pytest

from app.auth.security import create_access_token
from app.core.config import Settings, get_settings
from app.main import app
from app.models import Conversation
from app.voice import vapi

from .test_phone import BASE, CALLER, DIALLED, SECRET, business

AUTH = {"Authorization": "Bearer vapi-secret"}


def vapi_settings(**over) -> Settings:
    base = dict(public_base_url=BASE, vapi_webhook_secret="vapi-secret", jwt_secret=SECRET)
    return Settings(_env_file=None, **{**base, **over})


@pytest.fixture
def configured(client):
    app.dependency_overrides[get_settings] = lambda: vapi_settings()


def incoming(dialled=DIALLED, call_id="call-1", kind="assistant-request"):
    """What Vapi really sends for an assistant-request: the numbers are on the message, `call.phoneNumber` is null."""
    return {
        "message": {
            "type": kind,
            "phoneNumber": {"id": "pn-1", "number": dialled},
            "customer": {"number": CALLER},
            "call": {"id": call_id, "phoneNumber": None, "customer": {"number": CALLER}},
        }
    }


def llm_path(assistant: dict) -> str:
    return assistant["model"]["url"].removeprefix(BASE) + "/chat/completions"


def spoken(resp) -> str:
    """The text of a chat-completion SSE stream."""
    lines = [line[6:] for line in resp.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    return "".join(json.loads(line)["choices"][0]["delta"].get("content", "") for line in lines[:-1])


# ---------- helpers ----------
def test_secret_is_read_from_bearer_or_legacy_header_and_compared_exactly():
    assert vapi.valid_secret("s", "Bearer s", None)
    assert vapi.valid_secret("s", None, "s")
    assert not vapi.valid_secret("s", "Bearer other", None)
    assert not vapi.valid_secret("s", None, None)
    assert not vapi.valid_secret("", "Bearer ", "")  # no configured secret never matches


def test_numbers_are_read_from_the_message_with_the_call_as_a_fallback():
    assert vapi.call_numbers(incoming()["message"]) == (DIALLED, CALLER, "call-1")
    old = {"call": {"id": "c", "phoneNumber": {"number": DIALLED}, "customer": {"number": CALLER}}}
    assert vapi.call_numbers(old) == (DIALLED, CALLER, "c")
    assert vapi.call_numbers({}) == (None, None, None)


def test_last_user_text_handles_plain_and_part_content():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}, {"role": "user", "content": [{"type": "text", "text": " yoga? "}]}]
    assert vapi.last_user_text(messages) == "yoga?"
    assert vapi.last_user_text([{"role": "assistant", "content": "x"}]) == ""


def test_llm_tokens_are_not_interchangeable_with_login_tokens():
    s = vapi_settings()
    claims = vapi.read_llm_token(s, vapi.create_llm_token(s, "t1", "c1"))
    assert (claims["tid"], claims["cid"]) == ("t1", "c1")
    with pytest.raises(jwt.PyJWTError):
        vapi.read_llm_token(s, create_access_token(s, "u1", "admin", "t1"))


# ---------- what the business admin is shown ----------
def test_the_phone_page_shows_the_vapi_url_when_the_server_uses_vapi(client, configured, session_factory):
    _, admin = business(session_factory, client)
    got = client.get("/api/org/phone", headers=admin["headers"]).json()
    assert got["provider"] == "vapi" and got["webhookUrl"] == BASE + "/api/vapi/webhook" and got["ready"] is True


# ---------- the webhook ----------
def test_webhook_needs_configuration(client):
    assert client.post("/api/vapi/webhook", json=incoming(), headers=AUTH).status_code == 500


def test_webhook_rejects_a_missing_or_wrong_credential(client, configured):
    assert client.post("/api/vapi/webhook", json=incoming()).status_code == 403
    assert client.post("/api/vapi/webhook", json=incoming(), headers={"Authorization": "Bearer nope"}).status_code == 403


def test_other_messages_are_acknowledged(client, configured):
    assert client.post("/api/vapi/webhook", json=incoming(kind="status-update"), headers=AUTH).json() == {}


def test_unknown_number_is_told_it_is_not_in_service(client, configured):
    resp = client.post("/api/vapi/webhook", json=incoming("+910000000000"), headers=AUTH)
    assert resp.status_code == 200 and "not in service" in resp.json()["error"]


def test_known_number_gets_its_own_business_assistant(client, configured, session_factory):
    tenant, _ = business(session_factory, client)
    resp = client.post("/api/vapi/webhook", json=incoming(), headers=AUTH)
    assistant = resp.json()["assistant"]
    assert assistant["firstMessage"].startswith("Welcome to FitZone")
    assert assistant["model"]["provider"] == "custom-llm" and assistant["model"]["url"].startswith(BASE + "/api/vapi/llm/")
    token = assistant["model"]["url"].rsplit("/", 1)[1]
    claims = vapi.read_llm_token(vapi_settings(), token)
    assert claims["tid"] == tenant
    with session_factory() as session:
        conv = session.get(Conversation, claims["cid"])
        assert conv.tenant_id == tenant and conv.user_id is None
        assert conv.context["channel"] == "phone" and conv.context["call_id"] == "call-1"
        assert conv.context["caller"]["phone"] == CALLER


# ---------- the custom LLM endpoint ----------
def test_a_turn_streams_the_businesss_answer_and_is_saved(client, configured, session_factory):
    _, admin = business(session_factory, client)
    assistant = client.post("/api/vapi/webhook", json=incoming(), headers=AUTH).json()["assistant"]
    body = {"messages": [{"role": "system", "content": "ignored"}, {"role": "user", "content": "What time is the yoga class?"}]}
    resp = client.post(llm_path(assistant), json=body)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    assert "Check-in starts at 2 PM." in spoken(resp)
    assert client.get("/api/conversations", headers=admin["headers"]).json()["items"][0]["messageCount"] == 3


def test_the_llm_endpoint_refuses_bad_tokens(client, configured):
    assert client.post("/api/vapi/llm/garbage/chat/completions", json={"messages": []}).status_code == 401
    login = create_access_token(vapi_settings(), "u1", "admin", "t1")
    assert client.post(f"/api/vapi/llm/{login}/chat/completions", json={"messages": []}).status_code == 401


def test_each_number_reaches_only_its_own_business(client, configured, session_factory):
    first, _ = business(session_factory, client)
    second, _ = business(session_factory, client, "Night Gym", number="+914499998888")
    a = client.post("/api/vapi/webhook", json=incoming(DIALLED), headers=AUTH).json()["assistant"]
    b = client.post("/api/vapi/webhook", json=incoming("+914499998888", "call-2"), headers=AUTH).json()["assistant"]
    tokens = [vapi.read_llm_token(vapi_settings(), x["model"]["url"].rsplit("/", 1)[1]) for x in (a, b)]
    assert [t["tid"] for t in tokens] == [first, second] and tokens[0]["cid"] != tokens[1]["cid"]


# ---------- the business's own number ----------
def test_the_assistant_knows_the_number_set_on_the_phone_page(client, configured, session_factory, llm):
    _, admin = business(session_factory, client)
    assistant = client.post("/api/vapi/webhook", json=incoming(), headers=AUTH).json()["assistant"]
    ask = lambda: client.post(llm_path(assistant), json={"messages": [{"role": "user", "content": "What is your number?"}]})
    ask()
    assert DIALLED in llm.calls[-1]["system"]
    new = "+914499998888"  # a change on the Phone page applies to the next turn of the same call
    assert client.put("/api/org/phone", json={"number": new}, headers=admin["headers"]).status_code == 200
    ask()
    assert new in llm.calls[-1]["system"] and DIALLED not in llm.calls[-1]["system"]


def test_the_number_is_not_saved_with_the_conversation(client, configured, session_factory):
    business(session_factory, client)
    assistant = client.post("/api/vapi/webhook", json=incoming(), headers=AUTH).json()["assistant"]
    client.post(llm_path(assistant), json={"messages": [{"role": "user", "content": "hi"}]})
    cid = vapi.read_llm_token(vapi_settings(), assistant["model"]["url"].rsplit("/", 1)[1])["cid"]
    with session_factory() as session:
        assert "business_phone" not in session.get(Conversation, cid).context


# ---------- a call that dies on an error is reported to the business ----------
@pytest.fixture
def alerted(client, session_factory, configured):
    from app.ai.base import LLMProvider
    from app.api import deps
    from app.conversation.engine import ConversationEngine
    from app.conversation.service import ConversationService
    from app.notifications.staff import StaffAlerts

    from .conftest import RecordingEmailSender
    from .test_staff_alerts import RecordingSms

    class Silent(LLMProvider):
        async def stream(self, system, messages, tools):
            return
            yield  # pragma: no cover

    sms, email = RecordingSms(), RecordingEmailSender()
    service = ConversationService(session_factory, ConversationEngine(Silent()), StaffAlerts(session_factory, sms, email, BASE))
    app.dependency_overrides[deps.get_service] = lambda: service
    yield sms, email
    app.dependency_overrides.pop(deps.get_service, None)


def ended(reason, dialled=DIALLED, call_id="call-1"):
    body = incoming(dialled, call_id, kind="end-of-call-report")
    body["message"]["endedReason"] = reason
    return body


def test_error_endings_are_told_apart_from_normal_ones():
    assert vapi.is_error_ending("pipeline-error-openai-llm-failed")
    assert vapi.is_error_ending("assistant-request-returned-error")
    assert not any(vapi.is_error_ending(r) for r in ("customer-ended-call", "assistant-ended-call", "silence-timed-out", None))


def test_a_call_that_ended_on_an_error_alerts_the_business_once(client, session_factory, alerted):
    sms, email = alerted
    business(session_factory, client)
    assert client.post("/api/vapi/webhook", json=incoming(), headers=AUTH).status_code == 200  # the call starts
    for _ in range(2):  # Vapi may repeat a report
        assert client.post("/api/vapi/webhook", json=ended("pipeline-error-openai-llm-failed"), headers=AUTH).status_code == 200
    assert len(sms.sent) == 1 and CALLER in sms.sent[0][1] and "pipeline-error" in sms.sent[0][1]
    assert email.sent[0][1].startswith("A call at FitZone Anna Nagar dropped")


def test_a_normal_ending_or_an_unknown_number_alerts_nobody(client, session_factory, alerted):
    sms, email = alerted
    business(session_factory, client)
    client.post("/api/vapi/webhook", json=ended("customer-ended-call"), headers=AUTH)
    client.post("/api/vapi/webhook", json=ended("pipeline-error-x", dialled="+14155550100"), headers=AUTH)
    assert sms.sent == [] and email.sent == []
