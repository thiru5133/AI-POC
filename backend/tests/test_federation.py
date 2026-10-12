"""A domain's compare-all assistant: one standard tool per capability, fanned out to every partner."""

import asyncio

import pytest
from sqlalchemy import select

from app.mcp.client import McpCallResult, McpClient, McpToolInfo
from app.mcp.federation import DomainToolSet, ResultCache, is_read_only
from app.mcp.tools import McpToolSource
from app.models import Tenant
from app.core.config import get_settings

from .conftest import make_admin, make_tenant
from .test_mcp import URL_A, URL_B, URL_DOWN

URL_C = "http://93.184.216.37/mcp"


class RecordingClient(McpClient):
    def __init__(self):
        self.tools: dict[str, list[McpToolInfo]] = {}
        self.calls: list[tuple[str, str, dict]] = []

    async def list_tools(self, conn):
        if conn.url not in self.tools:
            raise ConnectionError("down")
        return self.tools[conn.url]

    async def call_tool(self, conn, name, arguments):
        self.calls.append((conn.url, name, arguments))
        if conn.url == URL_DOWN:
            raise ConnectionError("boom")
        return McpCallResult({"from": conn.url, "price": 100})


def tools(*names):
    return [McpToolInfo(n, f"{n} description", {"type": "object", "properties": {"city": {"type": "string"}}}) for n in names]


@pytest.fixture
def world(client, session_factory):
    """Two hotel partners (each with an MCP server), one school partner, and the hotel marketplace."""
    from app.models import McpServer

    ids = {}
    for name, domain, url in (("Alpha Hotel", "hotel", URL_A), ("Beta Hotel", "hotel", URL_B), ("Bright School", "school", URL_C)):
        tid = make_tenant(session_factory, name, domain)
        ids[name] = tid
        with session_factory() as session:
            session.add(McpServer(tenant_id=tid, name="Bookings", url=url, headers=[]))
            session.commit()
    with session_factory() as session:
        domain = session.scalars(select(Tenant).where(Tenant.id == ids["Alpha Hotel"])).one().domain_id
    from app.tenants.service import ensure_marketplace
    from app.models import Domain

    with session_factory() as session:
        market = ensure_marketplace(session, session.get(Domain, domain))
        session.commit()
        ids["market"] = market.id
    return ids


def source(session_factory, fake):
    return McpToolSource(lambda: session_factory(), get_settings(), fake, result_cache=ResultCache())


def test_one_standard_tool_per_capability_not_one_per_partner(session_factory, world):
    fake = RecordingClient()
    fake.tools = {URL_A: tools("check_availability", "book_room"), URL_B: tools("check_availability", "book_room"), URL_C: tools("admit")}
    ts = asyncio.run(source(session_factory, fake).for_tenant(world["market"]))
    names = sorted(d.name for d in ts.definitions)
    assert names == ["all_book_room", "all_check_availability"]  # 2 tools, not 4; the school's tool is not offered
    avail = next(d for d in ts.definitions if d.name == "all_check_availability")
    assert avail.input_schema["properties"]["partner"]["enum"] == ["Alpha Hotel", "Beta Hotel"]
    assert "partner" not in avail.input_schema.get("required", [])  # reads may ask everyone
    book = next(d for d in ts.definitions if d.name == "all_book_room")
    assert "partner" in book.input_schema["required"]  # a write must name exactly one partner


def test_a_read_fans_out_in_parallel_and_merges_with_partial_failure(session_factory, world):
    fake = RecordingClient()
    fake.tools = {URL_A: tools("check_availability"), URL_B: tools("check_availability")}
    ts = asyncio.run(source(session_factory, fake).for_tenant(world["market"]))
    out, is_error = asyncio.run(ts.execute("all_check_availability", {"city": "Goa"}))
    assert is_error is False and out["partners_asked"] == 2 and out["partners_failed"] == 0
    assert {r["partner"] for r in out["results"]} == {"Alpha Hotel", "Beta Hotel"}
    assert sorted(u for u, _, _ in fake.calls) == [URL_A, URL_B] and all(a == {"city": "Goa"} for _, _, a in fake.calls)


def test_a_broken_partner_does_not_break_the_answer(session_factory, world):
    from app.models import McpServer

    fake = RecordingClient()
    fake.tools = {URL_A: tools("check_availability"), URL_B: tools("check_availability")}
    ts = asyncio.run(source(session_factory, fake).for_tenant(world["market"]))
    # Beta's server dies after discovery.
    for route in ts._caps["all_check_availability"].routes:
        if route.partner == "Beta Hotel":
            object.__setattr__(route.spec.conn, "url", URL_DOWN)
    out, is_error = asyncio.run(ts.execute("all_check_availability", {}))
    assert is_error is False and out["partners_failed"] == 1
    failed = next(r for r in out["results"] if r["partner"] == "Beta Hotel")
    assert "could not be reached" in failed["error"] and "result" in next(r for r in out["results"] if r["partner"] == "Alpha Hotel")


def test_writes_go_to_exactly_one_named_partner(session_factory, world):
    fake = RecordingClient()
    fake.tools = {URL_A: tools("book_room"), URL_B: tools("book_room")}
    ts = asyncio.run(source(session_factory, fake).for_tenant(world["market"]))
    refused, is_error = asyncio.run(ts.execute("all_book_room", {"room": "deluxe"}))
    assert is_error and fake.calls == []  # never sent to everyone

    out, is_error = asyncio.run(ts.execute("all_book_room", {"partner": "beta hotel", "room": "deluxe"}))
    assert not is_error and out["partners_asked"] == 1
    assert fake.calls == [(URL_B, "book_room", {"room": "deluxe"})]  # `partner` is not forwarded to the partner's server

    unknown, is_error = asyncio.run(ts.execute("all_book_room", {"partner": "Nope"}))
    assert is_error and unknown["partners"] == ["Alpha Hotel", "Beta Hotel"]


def test_identical_reads_are_cached_briefly(session_factory, world):
    fake = RecordingClient()
    fake.tools = {URL_A: tools("check_availability"), URL_B: tools("check_availability")}
    src = source(session_factory, fake)
    for _ in range(2):
        ts = asyncio.run(src.for_tenant(world["market"]))
        asyncio.run(ts.execute("all_check_availability", {"city": "Goa"}))
    assert len(fake.calls) == 2  # the second turn reused the first answer
    ts = asyncio.run(src.for_tenant(world["market"]))
    asyncio.run(ts.execute("all_check_availability", {"city": "Pune"}))
    assert len(fake.calls) == 4


def test_a_normal_partner_still_sees_only_its_own_servers(session_factory, world):
    fake = RecordingClient()
    fake.tools = {URL_A: tools("check_availability"), URL_B: tools("check_availability")}
    ts = asyncio.run(source(session_factory, fake).for_tenant(world["Alpha Hotel"]))
    assert [d.name for d in ts.definitions] == ["bookings__check_availability"]


def test_read_only_detection_prefers_the_servers_hint():
    assert is_read_only(McpToolInfo("check_availability", "")) and not is_read_only(McpToolInfo("book_room", ""))
    assert not is_read_only(McpToolInfo("get_thing", "", read_only=False))
    assert is_read_only(McpToolInfo("reserve", "", read_only=True))
