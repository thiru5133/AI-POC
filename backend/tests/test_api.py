from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.repositories.conversations import ConversationRepository
import pytest

from .conftest import PROFILE, TENANT, make_admin, make_tenant

OTHER_TENANT = "00000000-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def _signed_in(client, demo_admin):
    client.headers.update(demo_admin["headers"])


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_conversation_flow(client):
    created = client.post("/api/conversations", json={}).json()
    assert created["greeting"] == "Welcome to Demo Hotel. How can I help you?"
    cid = created["id"]

    reply = client.post(f"/api/conversations/{cid}/messages", json={"text": "What time is check-in?"})
    assert reply.status_code == 200
    assert "2 PM" in reply.json()["reply"]

    convo = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in convo["messages"]] == ["assistant", "user", "assistant"]
    assert convo["messages"][1]["text"] == "What time is check-in?"


def test_unknown_conversation_uses_error_envelope(client):
    resp = client.get("/api/conversations/nope")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "not_found" and "requestId" in err


def test_validation_error_envelope(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    resp = client.post(f"/api/conversations/{cid}/messages", json={})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


def test_voice_session_descriptor(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    data = client.post("/api/voice/session", json={"conversationId": cid}).json()
    assert data["transport"] == "websocket"
    assert data["wsPath"] == f"/ws/voice/{cid}"
    assert data["audio"]["mimeType"] == "audio/mpeg"


def test_domain_profile_endpoint(client):
    data = client.get(f"/api/domain-profiles/{PROFILE}").json()
    assert data["domainType"] == "hotel"
    assert data["config"]["identity"]["organizationName"] == "Demo Hotel"


def test_conversations_require_login(client):
    anonymous = {"Authorization": ""}
    assert client.post("/api/conversations", headers=anonymous).status_code == 401
    assert client.get("/api/conversations/x", headers=anonymous).status_code == 401


def test_client_supplied_tenant_is_ignored(client, session_factory):
    """Headers and body can no longer pick the tenant: the logged-in admin's own tenant always wins."""
    other_tenant = make_tenant(session_factory, "Other Org")
    cid = client.post(
        "/api/conversations", json={"tenantId": other_tenant}, headers={"X-Tenant-Id": other_tenant}
    ).json()["id"]
    from app.models import Conversation

    with session_factory() as session:
        assert session.get(Conversation, cid).tenant_id == TENANT


def test_tenant_isolation_over_http(client, session_factory):
    cid = client.post("/api/conversations", json={}).json()["id"]
    other_tenant = make_tenant(session_factory, "Other Org")
    other = make_admin(session_factory, other_tenant, "other-admin@example.com")["headers"]
    assert client.get(f"/api/conversations/{cid}", headers=other).status_code == 404
    assert client.get(f"/api/domain-profiles/{PROFILE}", headers=other).status_code == 404
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}, headers=other).status_code == 404


def test_repository_never_returns_other_tenants_rows(session_factory, llm):
    import asyncio

    service = ConversationService(session_factory, ConversationEngine(llm))
    cid, _ = asyncio.run(service.start(TENANT))
    with session_factory() as session:
        assert ConversationRepository(session, TENANT).get(cid) is not None
        assert ConversationRepository(session, OTHER_TENANT).get(cid) is None
        assert ConversationRepository(session, OTHER_TENANT).messages(cid) == []


def test_repository_requires_tenant(session_factory):
    with session_factory() as session, pytest.raises(ValueError):
        ConversationRepository(session, "")


def test_unconfigured_llm_returns_configuration_error(session_factory, demo_admin):
    from fastapi.testclient import TestClient
    from app.api import deps
    from app.core.errors import ConfigurationError
    from app.main import app

    def broken():
        raise ConfigurationError("ANTHROPIC_API_KEY is not set")

    app.dependency_overrides[deps.get_sessions] = lambda: session_factory
    app.dependency_overrides[deps.get_llm] = broken
    try:
        with TestClient(app) as c:
            resp = c.post("/api/conversations", headers=demo_admin["headers"])
        assert resp.status_code == 500 and resp.json()["error"]["code"] == "configuration_error"
    finally:
        app.dependency_overrides.clear()


# ---------- conversation history ----------
def _chat(client, text):
    cid = client.post("/api/conversations").json()["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"text": text})
    return cid


def test_conversations_are_saved_and_listed_newest_first(client):
    first = _chat(client, "What time is check-in?")
    second = _chat(client, "Do you have parking?")
    listing = client.get("/api/conversations").json()
    assert listing["total"] == 2 and [c["id"] for c in listing["items"]] == [second, first]
    newest = listing["items"][0]
    assert newest["preview"] == "Do you have parking?"
    assert newest["messageCount"] == 3  # greeting + the caller's message + the reply
    assert newest["startedAt"] and newest["lastMessageAt"] and newest["status"] == "active"

    detail = client.get(f"/api/conversations/{first}").json()
    assert detail["startedAt"]
    assert [(m["role"], m["text"]) for m in detail["messages"]][1] == ("user", "What time is check-in?")


def test_calls_where_nothing_was_said_are_hidden_unless_asked_for(client):
    said = _chat(client, "hello")
    silent = client.post("/api/conversations").json()["id"]  # only the greeting was ever saved
    assert [c["id"] for c in client.get("/api/conversations").json()["items"]] == [said]
    everything = client.get("/api/conversations", params={"includeEmpty": "true"}).json()
    assert {c["id"] for c in everything["items"]} == {said, silent} and everything["total"] == 2


def test_conversation_list_is_paged(client):
    ids = [_chat(client, f"question {i}") for i in range(5)]
    page1 = client.get("/api/conversations", params={"limit": 2}).json()
    page2 = client.get("/api/conversations", params={"limit": 2, "offset": 2}).json()
    page3 = client.get("/api/conversations", params={"limit": 2, "offset": 4}).json()
    assert page1["total"] == 5
    assert [c["id"] for c in page1["items"] + page2["items"] + page3["items"]] == list(reversed(ids))
    assert client.get("/api/conversations", params={"limit": 0}).status_code == 422
    assert client.get("/api/conversations", params={"limit": 500}).status_code == 422


def test_each_organization_only_sees_its_own_conversations(client, session_factory):
    mine = _chat(client, "my private question")
    other_tenant = make_tenant(session_factory, "Other Org")
    other = make_admin(session_factory, other_tenant, "other-admin@example.com")["headers"]
    theirs = client.post("/api/conversations", headers=other).json()["id"]
    client.post(f"/api/conversations/{theirs}/messages", json={"text": "their question"}, headers=other)

    assert [c["id"] for c in client.get("/api/conversations").json()["items"]] == [mine]
    their_list = client.get("/api/conversations", headers=other).json()
    assert [c["id"] for c in their_list["items"]] == [theirs] and their_list["total"] == 1
    assert "my private question" not in str(their_list)
    assert client.get(f"/api/conversations/{mine}", headers=other).status_code == 404


def test_conversation_history_requires_login(client):
    assert client.get("/api/conversations", headers={"Authorization": ""}).status_code == 401
