from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from auth import ApiKeyMiddleware, configured_keys


def client(*keys: str) -> TestClient:
    inner = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"), methods=["GET", "POST"])])
    return TestClient(ApiKeyMiddleware(inner, list(keys)))


def test_valid_key_is_let_through():
    assert client("k1").post("/mcp", headers={"X-API-Key": "k1"}).text == "ok"


def test_missing_or_wrong_key_is_refused():
    c = client("k1")
    assert c.post("/mcp").status_code == 401
    assert c.post("/mcp", headers={"X-API-Key": "nope"}).status_code == 401
    assert c.post("/mcp", headers={"Authorization": "Bearer k1"}).status_code == 401  # only the API key header counts


def test_several_keys_can_be_valid_at_once():
    c = client("old", "new")
    assert c.post("/mcp", headers={"X-API-Key": "old"}).status_code == 200
    assert c.post("/mcp", headers={"X-API-Key": "new"}).status_code == 200


def test_no_configured_keys_fails_closed():
    assert client().post("/mcp", headers={"X-API-Key": ""}).status_code == 401
    assert client().post("/mcp", headers={"X-API-Key": "anything"}).status_code == 401


def test_keys_are_read_from_a_comma_separated_variable(monkeypatch):
    monkeypatch.setenv("GB_MCP_API_KEYS", " a , b,,")
    assert configured_keys() == ["a", "b"]
    monkeypatch.delenv("GB_MCP_API_KEYS")
    assert configured_keys() == []
