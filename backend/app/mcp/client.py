"""Talks to a remote MCP server. `McpClient` is the seam: the SDK-backed client in production, a fake in tests.
The client holds no state: every call receives the full connection (URL, headers, transport, timeout) of one
specific server, so nothing can leak between tenants through it."""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

MAX_RESULT_CHARS = 8000  # keeps a chatty tool from flooding the LLM context
TRANSPORTS = ("streamable_http", "sse")


@dataclass(frozen=True)
class McpConnection:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    transport: str = "streamable_http"
    timeout: float = 15


@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    read_only: bool | None = None  # the server's own readOnlyHint, when it declares one


@dataclass
class McpCallResult:
    content: Any
    is_error: bool = False


class McpClient(ABC):
    @abstractmethod
    async def list_tools(self, conn: McpConnection) -> list[McpToolInfo]: ...

    @abstractmethod
    async def call_tool(self, conn: McpConnection, name: str, arguments: dict[str, Any]) -> McpCallResult: ...


def _no_redirect_client(
    headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None, auth: httpx.Auth | None = None
) -> httpx.AsyncClient:
    # The URL was checked against private/metadata addresses; following a redirect would skip that check.
    return httpx.AsyncClient(headers=headers, timeout=timeout or httpx.Timeout(30), auth=auth, follow_redirects=False)


class SdkMcpClient(McpClient):
    """Opens a short-lived MCP session per operation (no connection is shared between servers or tenants)."""

    async def _run(self, conn: McpConnection, action):
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamablehttp_client

        headers = conn.headers or None
        if conn.transport == "sse":
            transport = sse_client(
                conn.url, headers=headers, timeout=conn.timeout, httpx_client_factory=_no_redirect_client
            )
        else:
            transport = streamablehttp_client(
                conn.url, headers=headers, timeout=conn.timeout, httpx_client_factory=_no_redirect_client
            )

        async def go():
            async with transport as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await action(session)

        return await asyncio.wait_for(go(), timeout=conn.timeout + 5)

    async def list_tools(self, conn: McpConnection) -> list[McpToolInfo]:
        async def action(session):
            result = await session.list_tools()
            return [
                McpToolInfo(
                    t.name,
                    t.description or "",
                    t.inputSchema or {"type": "object", "properties": {}},
                    getattr(t.annotations, "readOnlyHint", None),
                )
                for t in result.tools
            ]

        return await self._run(conn, action)

    async def call_tool(self, conn: McpConnection, name: str, arguments: dict[str, Any]) -> McpCallResult:
        async def action(session):
            result = await session.call_tool(name, arguments)
            return McpCallResult(_content_of(result), bool(result.isError))

        return await self._run(conn, action)


def _content_of(result: Any) -> Any:
    """Turns an MCP CallToolResult into JSON-friendly data for the LLM."""
    structured = getattr(result, "structuredContent", None)
    if structured:
        return _cap(structured)
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if len(texts) == 1:
        try:
            return _cap(json.loads(texts[0]))
        except ValueError:
            pass
    return _cap({"text": "\n".join(texts)})


def _cap(value: Any) -> Any:
    if len(json.dumps(value, default=str)) <= MAX_RESULT_CHARS:
        return value
    return {"truncated": True, "text": json.dumps(value, default=str)[:MAX_RESULT_CHARS]}
