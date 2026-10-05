from app.conversation.engine import ConversationEngine
from app.conversation.service import ConversationService
from app.repositories.conversations import ConversationRepository
import pytest

from .conftest import PROFILE, TENANT

OTHER_TENANT = "00000000-0000-0000-0000-000000000002"


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


def test_tenant_isolation_over_http(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    other = {"X-Tenant-Id": OTHER_TENANT}
    assert client.get(f"/api/conversations/{cid}", headers=other).status_code == 404
    assert client.get(f"/api/domain-profiles/{PROFILE}", headers=other).status_code == 404
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}, headers=other).status_code == 404


def test_repository_never_returns_other_tenants_rows(session_factory, llm):
    import asyncio

    service = ConversationService(session_factory, ConversationEngine(llm))
    cid, _ = asyncio.run(service.start(TENANT, PROFILE))
    with session_factory() as session:
        assert ConversationRepository(session, TENANT).get(cid) is not None
        assert ConversationRepository(session, OTHER_TENANT).get(cid) is None
        assert ConversationRepository(session, OTHER_TENANT).messages(cid) == []


def test_repository_requires_tenant(session_factory):
    with session_factory() as session, pytest.raises(ValueError):
        ConversationRepository(session, "")


def test_unconfigured_llm_returns_configuration_error(session_factory):
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
            resp = c.post("/api/conversations", json={})
        assert resp.status_code == 500 and resp.json()["error"]["code"] == "configuration_error"
    finally:
        app.dependency_overrides.clear()
