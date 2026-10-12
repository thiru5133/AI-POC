"""Per-organization MCP integration: configuration, secrecy, SSRF guard and, above all, tenant isolation."""

import pytest

from app.ai.base import LLMEvent, LLMProvider
from app.api import deps
from app.main import app
from app.mcp.client import McpCallResult, McpClient, McpConnection, McpToolInfo
from app.mcp.security import InvalidMcpUrlError, validate_mcp_url
from app.models import McpServer

from .conftest import make_admin, make_tenant

# Public IP literals: valid for the SSRF guard without DNS and without enabling private hosts.
URL_A = "http://93.184.216.34/mcp"
URL_B = "http://93.184.216.35/mcp"
URL_DOWN = "http://93.184.216.36/mcp"


class FakeMcpClient(McpClient):
    """Pretends to be the remote servers: each URL serves its own tools and records every request it receives."""

    def __init__(self):
        self.tools_by_url: dict[str, list[McpToolInfo]] = {}
        self.requests: list[tuple[str, McpConnection, str, dict]] = []  # (op, connection, tool, args)

    def serve(self, url: str, *tool_names: str):
        self.tools_by_url[url] = [McpToolInfo(n, f"{n} description") for n in tool_names]

    async def list_tools(self, conn):
        self.requests.append(("list", conn, "", {}))
        if conn.url not in self.tools_by_url:
            raise ConnectionError("down")
        return self.tools_by_url[conn.url]

    async def call_tool(self, conn, name, arguments):
        self.requests.append(("call", conn, name, arguments))
        return McpCallResult({"answer": f"{conn.url} says hi"})


class ToolCallingLLM(LLMProvider):
    """Calls the first tool it is offered (if any), then answers. Records the tools offered on every turn."""

    def __init__(self):
        self.offered: list[list[str]] = []
        self.systems: list[str] = []

    async def stream(self, system, messages, tools):
        self.offered.append([t.name for t in tools])
        self.systems.append(system)
        if tools and isinstance(messages[-1]["content"], str):
            yield LLMEvent(type="tool_use", tool_id="t1", tool_name=tools[0].name, tool_input={"q": 1})
        else:
            yield LLMEvent(type="text", text="Done.")


@pytest.fixture
def fake(client):
    fake = FakeMcpClient()
    app.dependency_overrides[deps.get_mcp_client] = lambda: fake
    return fake


@pytest.fixture
def llm_spy(client):
    spy = ToolCallingLLM()
    app.dependency_overrides[deps.get_llm] = lambda: spy
    return spy


@pytest.fixture
def two_orgs(session_factory):
    a = make_admin(session_factory, make_tenant(session_factory, "Org A"), "a@example.com")
    b = make_admin(session_factory, make_tenant(session_factory, "Org B"), "b@example.com")
    return a, b


def key(value: str, name: str = "X-API-Key") -> dict:
    return {"name": name, "value": value, "secret": True}


def add(client, admin, name="Bookings", url=URL_A, headers=None, **extra):
    body = {"name": name, "url": url, "headers": headers or [], **extra}
    return client.post("/api/org/mcp-servers", json=body, headers=admin["headers"])


# ---------- configuration ----------
def test_admin_configures_tests_updates_and_deletes_a_server(client, fake, two_orgs):
    a, _ = two_orgs
    fake.serve(URL_A, "check_availability", "book_room")
    created = add(client, a, headers=[key("secret-key-123")])
    assert created.status_code == 201
    server = created.json()
    assert server["enabled"] is True and server["transport"] == "streamable_http" and server["timeoutSeconds"] == 15
    assert server["headers"] == [{"name": "X-API-Key", "secret": True, "value": None, "hasValue": True}]
    assert "secret-key-123" not in created.text  # a secret is never sent back

    tested = client.post(f"/api/org/mcp-servers/{server['id']}/test", headers=a["headers"]).json()
    assert tested["ok"] is True and [t["name"] for t in tested["tools"]] == ["check_availability", "book_room"]
    assert fake.requests[-1][1].headers == {"X-API-Key": "secret-key-123"}

    patched = client.patch(
        f"/api/org/mcp-servers/{server['id']}", json={"enabled": False, "name": "Hotel"}, headers=a["headers"]
    ).json()
    assert patched["enabled"] is False and patched["name"] == "Hotel"
    assert patched["headers"][0]["hasValue"] is True  # untouched when `headers` is omitted

    assert client.delete(f"/api/org/mcp-servers/{server['id']}", headers=a["headers"]).status_code == 204
    assert client.get("/api/org/mcp-servers", headers=a["headers"]).json() == []


def test_headers_are_free_form_secret_or_plain(client, fake, two_orgs, session_factory):
    a, _ = two_orgs
    fake.serve(URL_A, "t")
    headers = [
        {"name": "x-api-key", "value": "k-1", "secret": True},  # any name, any case
        {"name": "Authorization", "value": "Bearer b-1", "secret": True},
        {"name": "X-Tenant-Hint", "value": "emea", "secret": False},
    ]
    server = add(client, a, headers=headers).json()
    shown = {h["name"]: h for h in server["headers"]}
    assert shown["X-Tenant-Hint"]["value"] == "emea"  # plain headers are visible
    assert shown["x-api-key"]["value"] is None and shown["Authorization"]["value"] is None

    client.post(f"/api/org/mcp-servers/{server['id']}/test", headers=a["headers"])
    assert fake.requests[-1][1].headers == {"x-api-key": "k-1", "Authorization": "Bearer b-1", "X-Tenant-Hint": "emea"}

    with session_factory() as session:
        stored = session.get(McpServer, server["id"]).headers
    by_name = {h["name"]: h for h in stored}
    assert "k-1" not in by_name["x-api-key"]["value"] and "b-1" not in by_name["Authorization"]["value"]  # encrypted
    assert by_name["X-Tenant-Hint"]["value"] == "emea"


def test_editing_headers_keeps_secrets_that_are_not_resent(client, fake, two_orgs):
    a, _ = two_orgs
    fake.serve(URL_A, "t")
    sid = add(client, a, headers=[key("original"), {"name": "X-Env", "value": "prod", "secret": False}]).json()["id"]
    path = f"/api/org/mcp-servers/{sid}"

    # re-send the secret without a value (keep), change the plain one, add another secret
    edited = client.patch(
        path,
        json={"headers": [{"name": "X-API-Key", "secret": True}, {"name": "X-Env", "value": "staging"}, key("n-2", "X-Other")]},
        headers=a["headers"],
    ).json()
    assert [h["name"] for h in edited["headers"]] == ["X-API-Key", "X-Env", "X-Other"]
    client.post(f"{path}/test", headers=a["headers"])
    assert fake.requests[-1][1].headers == {"X-API-Key": "original", "X-Env": "staging", "X-Other": "n-2"}

    # replace the secret's value; and dropping a header from the list removes it
    client.patch(path, json={"headers": [key("rotated")]}, headers=a["headers"])
    client.post(f"{path}/test", headers=a["headers"])
    assert fake.requests[-1][1].headers == {"X-API-Key": "rotated"}
    client.patch(path, json={"headers": []}, headers=a["headers"])
    client.post(f"{path}/test", headers=a["headers"])
    assert fake.requests[-1][1].headers == {}

    # a secret cannot be kept if nothing was ever saved under that name
    assert client.patch(path, json={"headers": [{"name": "X-New", "secret": True}]}, headers=a["headers"]).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "Host", "value": "evil.example"},  # protocol headers are managed by the system
        {"name": "Content-Length", "value": "1"},
        {"name": "Mcp-Session-Id", "value": "x"},
        {"name": "Bad Name", "value": "x"},
        {"name": "X-A", "value": "line1\r\nX-Injected: 1"},  # header injection
        {"name": "X-A", "value": ""},  # nothing to keep and nothing given
    ],
)
def test_unsafe_headers_are_refused(client, fake, two_orgs, bad):
    a, _ = two_orgs
    assert add(client, a, headers=[bad]).status_code == 422


def test_header_limits(client, fake, two_orgs):
    a, _ = two_orgs
    twice = [{"name": "X-A", "value": "1"}, {"name": "x-a", "value": "2"}]
    assert add(client, a, headers=twice).status_code == 422
    many = [{"name": f"X-H{i}", "value": "v"} for i in range(11)]
    assert add(client, a, headers=many).status_code == 422
    assert add(client, a, headers=many[:10]).status_code == 201


def test_transport_and_timeout_are_configurable(client, fake, two_orgs):
    a, _ = two_orgs
    fake.serve(URL_A, "t")
    server = add(client, a, transport="sse", timeoutSeconds=30).json()
    assert server["transport"] == "sse" and server["timeoutSeconds"] == 30
    client.post(f"/api/org/mcp-servers/{server['id']}/test", headers=a["headers"])
    conn = fake.requests[-1][1]
    assert (conn.transport, conn.timeout) == ("sse", 30.0)

    changed = client.patch(
        f"/api/org/mcp-servers/{server['id']}", json={"transport": "streamable_http", "timeoutSeconds": 5}, headers=a["headers"]
    ).json()
    assert changed["transport"] == "streamable_http" and changed["timeoutSeconds"] == 5
    assert add(client, a, name="X", transport="websocket").status_code == 422
    assert add(client, a, name="Y", timeoutSeconds=0).status_code == 422
    assert add(client, a, name="Z", timeoutSeconds=600).status_code == 422


def test_unreachable_server_reports_failure_not_a_crash(client, fake, two_orgs):
    a, _ = two_orgs
    sid = add(client, a, url=URL_DOWN).json()["id"]
    result = client.post(f"/api/org/mcp-servers/{sid}/test", headers=a["headers"]).json()
    assert result["ok"] is False and result["tools"] == [] and "Could not reach the server" in result["error"]


def test_validation_and_limits(client, fake, two_orgs):
    a, _ = two_orgs
    assert add(client, a, name="x", url="ftp://93.184.216.34/").status_code == 422
    assert add(client, a, name="x", url="http://user:pw@93.184.216.34/").status_code == 422
    assert add(client, a, name="x", url="http://169.254.169.254/latest/meta-data").status_code == 422
    assert add(client, a, name="x", url="http://10.0.0.5/mcp").status_code == 422  # private hosts off by default
    assert add(client, a, name="   ").status_code == 422
    assert add(client, a, name="One").status_code == 201
    assert add(client, a, name="one", url=URL_B).status_code == 409  # names are unique per organization, any case
    for i in range(4):
        assert add(client, a, name=f"S{i}", url=URL_B).status_code == 201
    assert add(client, a, name="Sixth", url=URL_B).status_code == 409  # limit of 5


def test_access_control(client, fake, session_factory, two_orgs):
    assert client.get("/api/org/mcp-servers").status_code == 401
    superadmin = make_admin(session_factory, None, "root@example.com")
    with session_factory() as session:
        from app.models import User

        session.get(User, superadmin["user_id"]).role = "superadmin"
        session.commit()
    from app.auth.security import create_access_token
    from app.core.config import get_settings

    token = create_access_token(get_settings(), superadmin["user_id"], "superadmin", None)
    assert client.get("/api/org/mcp-servers", headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ---------- SSRF guard ----------
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://93.184.216.34/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata: refused even in development
        "http://[fe80::1]/",
        "http://0.0.0.0/",
        "http://user:pw@93.184.216.34/",
        "not a url",
    ],
)
def test_url_guard_always_refuses_dangerous_urls(url):
    with pytest.raises(InvalidMcpUrlError):
        validate_mcp_url(url, allow_private_hosts=True)


def test_url_guard_private_hosts_only_when_allowed():
    for url in ("http://localhost:8101/mcp", "http://127.0.0.1/mcp", "http://192.168.1.10/mcp", "http://10.1.2.3/mcp"):
        with pytest.raises(InvalidMcpUrlError):
            validate_mcp_url(url, allow_private_hosts=False)
        assert validate_mcp_url(url, allow_private_hosts=True) == url
    assert validate_mcp_url(URL_A, allow_private_hosts=False) == URL_A


def test_sdk_client_never_follows_redirects():
    from app.mcp.client import _no_redirect_client

    assert _no_redirect_client().follow_redirects is False  # a redirect could otherwise skip the URL check


# ---------- tenant isolation ----------
def test_one_organization_cannot_see_or_touch_anothers_servers(client, fake, two_orgs):
    a, b = two_orgs
    fake.serve(URL_A, "secret_tool")
    sid = add(client, a, headers=[key("a-secret")]).json()["id"]

    assert client.get("/api/org/mcp-servers", headers=b["headers"]).json() == []
    path = f"/api/org/mcp-servers/{sid}"
    assert client.patch(path, json={"enabled": False}, headers=b["headers"]).status_code == 404
    assert client.patch(path, json={"headers": []}, headers=b["headers"]).status_code == 404
    assert client.delete(path, headers=b["headers"]).status_code == 404
    assert client.post(f"{path}/test", headers=b["headers"]).status_code == 404
    assert [r for r in fake.requests if r[1].url == URL_A] == []  # B's attempts never reached A's server

    assert add(client, b, name="Bookings", url=URL_B).status_code == 201  # the same name is free for B
    mine = client.get("/api/org/mcp-servers", headers=a["headers"]).json()
    assert [s["url"] for s in mine] == [URL_A] and mine[0]["enabled"] is True and mine[0]["headers"][0]["hasValue"]


def test_each_conversation_only_gets_and_calls_its_own_organizations_tools(client, fake, llm_spy, two_orgs, session_factory):
    a, b = two_orgs
    c = make_admin(session_factory, make_tenant(session_factory, "Org C"), "c@example.com")  # no MCP at all
    fake.serve(URL_A, "check_availability")
    fake.serve(URL_B, "list_orders")
    add(client, a, name="Hotel", url=URL_A, headers=[key("token-A")])
    add(client, b, name="Shop", url=URL_B, headers=[key("token-B", "Authorization")], transport="sse")

    def talk(admin):
        start = len(llm_spy.offered)
        cid = client.post("/api/conversations", headers=admin["headers"]).json()["id"]
        reply = client.post(f"/api/conversations/{cid}/messages", json={"text": "hello"}, headers=admin["headers"])
        assert reply.status_code == 200
        return llm_spy.offered[start], llm_spy.systems[start]  # tools + prompt on the turn's first LLM round

    tools_a, system_a = talk(a)
    tools_b, _ = talk(b)
    tools_c, system_c = talk(c)

    assert tools_a == ["hotel__check_availability"]
    assert tools_b == ["shop__list_orders"]
    assert tools_c == []
    assert "tools connected" in system_a and "tools connected" not in system_c

    calls = [r for r in fake.requests if r[0] == "call"]
    assert [(r[1].url, r[1].headers, r[1].transport, r[2]) for r in calls] == [
        (URL_A, {"X-API-Key": "token-A"}, "streamable_http", "check_availability"),
        (URL_B, {"Authorization": "token-B"}, "sse", "list_orders"),
    ]


def test_disabled_and_broken_servers_do_not_break_the_conversation(client, fake, llm_spy, two_orgs):
    a, _ = two_orgs
    fake.serve(URL_A, "alive")
    off = add(client, a, name="Off", url=URL_B).json()["id"]
    client.patch(f"/api/org/mcp-servers/{off}", json={"enabled": False}, headers=a["headers"])
    add(client, a, name="Broken", url=URL_DOWN)
    add(client, a, name="Alive", url=URL_A)

    cid = client.post("/api/conversations", headers=a["headers"]).json()["id"]
    reply = client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}, headers=a["headers"])
    assert reply.status_code == 200 and reply.json()["reply"] == "Done."
    assert llm_spy.offered[0] == ["alive__alive"]  # only the healthy, enabled server contributes tools
    assert not [r for r in fake.requests if r[1].url == URL_B]  # disabled servers are never contacted


def test_tool_failures_reach_the_llm_as_errors(client, fake, llm_spy, two_orgs):
    a, _ = two_orgs
    fake.serve(URL_A, "flaky")
    add(client, a, name="Hotel", url=URL_A)

    async def explode(conn, name, arguments):
        raise TimeoutError("slow")

    fake.call_tool = explode
    cid = client.post("/api/conversations", headers=a["headers"]).json()["id"]
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}, headers=a["headers"]).status_code == 200
    assert len(llm_spy.offered) == 2  # the failure went back to the LLM as an error result and the turn finished


def test_failure_messages_are_actionable_even_inside_exception_groups():
    import httpx

    from app.mcp.service import describe_failure

    def status_error(code):
        request = httpx.Request("POST", URL_A)
        return httpx.HTTPStatusError(str(code), request=request, response=httpx.Response(code, request=request))

    assert "rejected the credentials (401)" in describe_failure(ExceptionGroup("x", [ExceptionGroup("y", [status_error(401)])]))
    assert "Could not reach the server" in describe_failure(ExceptionGroup("x", [httpx.ConnectError("refused")]))
    assert "error (500)" in describe_failure(status_error(500))


def test_localhost_alias_redirects_only_the_connection():
    from app.mcp.security import apply_localhost_alias

    alias = "host.docker.internal"
    assert apply_localhost_alias("http://localhost:8101/mcp", alias) == "http://host.docker.internal:8101/mcp"
    assert apply_localhost_alias("https://127.0.0.1/mcp?x=1", alias) == "https://host.docker.internal/mcp?x=1"
    assert apply_localhost_alias("http://93.184.216.34/mcp", alias) == "http://93.184.216.34/mcp"  # other hosts untouched
    assert apply_localhost_alias("http://localhost:8101/mcp", "") == "http://localhost:8101/mcp"  # off by default


def test_saved_localhost_url_connects_via_the_alias_but_is_shown_as_typed(client, fake, two_orgs):
    from app.core.config import Settings

    a, _ = two_orgs
    app.dependency_overrides[deps.get_settings] = lambda: Settings(
        _env_file=None, mcp_allow_private_hosts=True, mcp_localhost_alias="127.0.0.2"
    )
    fake.serve("http://127.0.0.2:8101/mcp", "t")
    server = add(client, a, url="http://localhost:8101/mcp").json()
    assert server["url"] == "http://localhost:8101/mcp"
    result = client.post(f"/api/org/mcp-servers/{server['id']}/test", headers=a["headers"]).json()
    assert result["ok"] is True and fake.requests[-1][1].url == "http://127.0.0.2:8101/mcp"


def test_unreachable_localhost_explains_docker(client, fake, two_orgs):
    from app.core.config import Settings

    a, _ = two_orgs
    app.dependency_overrides[deps.get_settings] = lambda: Settings(_env_file=None, mcp_allow_private_hosts=True)
    server = add(client, a, url="http://localhost:8101/mcp").json()
    result = client.post(f"/api/org/mcp-servers/{server['id']}/test", headers=a["headers"]).json()
    assert result["ok"] is False and "host.docker.internal" in result["error"]
