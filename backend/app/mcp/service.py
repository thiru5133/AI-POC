"""An admin's MCP server configuration. Every operation is scoped to the caller's own tenant."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.mcp.client import TRANSPORTS, McpClient, McpToolInfo
from app.mcp.headers import HeaderInput, InvalidMcpConfigError, build_stored
from app.mcp.security import is_local_url, validate_mcp_url
from app.mcp.tools import connection_for
from app.models import McpServer
from app.repositories.mcp import McpServerRepository


@dataclass
class McpTestResult:
    ok: bool
    tools: list[McpToolInfo]
    error: str | None = None


@dataclass
class McpSettings:
    """The editable fields of a server. `None` on update means "leave unchanged"."""

    name: str | None = None
    url: str | None = None
    headers: list[HeaderInput] | None = None
    transport: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _leaf_errors(exc: BaseException) -> list[BaseException]:
    """MCP client errors arrive wrapped in (nested) ExceptionGroups: find the real causes."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaf_errors(inner)]
    return [exc]


def describe_failure(exc: BaseException) -> str:
    """A message an admin can act on, without leaking internals."""
    for leaf in _leaf_errors(exc):
        if isinstance(leaf, httpx.HTTPStatusError):
            status = leaf.response.status_code
            if status in (401, 403):
                return f"The server rejected the credentials ({status}). Check the headers you configured."
            return f"The server answered with an error ({status})."
        if isinstance(leaf, (httpx.ConnectError, httpx.ConnectTimeout, ConnectionError, TimeoutError)):
            return "Could not reach the server. Check the URL, and that it is running."
    return f"Could not connect ({type(_leaf_errors(exc)[0]).__name__}). Check the URL, transport and headers."


def _check_transport(transport: str) -> None:
    if transport not in TRANSPORTS:
        raise InvalidMcpConfigError(f"Transport must be one of: {', '.join(TRANSPORTS)}")


def _check_timeout(seconds: int) -> None:
    if not 1 <= seconds <= 60:
        raise InvalidMcpConfigError("The timeout must be between 1 and 60 seconds")


class McpConfigService:
    def __init__(self, session_factory: Callable[[], Session], settings: Settings, client: McpClient):
        self._sf = session_factory
        self._settings = settings
        self._client = client

    # ---- sync implementations (run in a worker thread) ----
    def _list(self, tenant_id: str) -> list[McpServer]:
        with self._sf() as session:
            return McpServerRepository(session, tenant_id).list_all()

    def _create(self, tenant_id: str, data: McpSettings) -> McpServer:
        url = validate_mcp_url(data.url or "", self._settings.mcp_allow_private_hosts)
        transport = data.transport or "streamable_http"
        timeout = data.timeout_seconds or 15
        _check_transport(transport)
        _check_timeout(timeout)
        headers = build_stored(self._settings, data.headers or [])
        with self._sf() as session:
            repo = McpServerRepository(session, tenant_id)
            if repo.count() >= self._settings.mcp_max_servers_per_tenant:
                raise ConflictError(f"At most {self._settings.mcp_max_servers_per_tenant} MCP servers can be configured")
            if repo.get_by_name(data.name or ""):
                raise ConflictError("You already have an MCP server with that name")
            server = McpServer(
                name=data.name,
                url=url,
                headers=headers,
                transport=transport,
                timeout_seconds=timeout,
                enabled=True,
                updated_at=_now(),
            )
            try:
                repo.add(server)
                session.commit()
            except IntegrityError:
                session.rollback()
                raise ConflictError("You already have an MCP server with that name") from None
            return server

    def _update(self, tenant_id: str, server_id: str, data: McpSettings) -> McpServer:
        with self._sf() as session:
            repo = McpServerRepository(session, tenant_id)
            server = repo.get(server_id)
            if server is None:
                raise NotFoundError("MCP server not found")
            if data.name is not None:
                if data.name.lower() != server.name.lower() and repo.get_by_name(data.name):
                    raise ConflictError("You already have an MCP server with that name")
                server.name = data.name
            if data.url is not None:
                server.url = validate_mcp_url(data.url, self._settings.mcp_allow_private_hosts)
            if data.headers is not None:
                server.headers = build_stored(self._settings, data.headers, server.headers)
            if data.transport is not None:
                _check_transport(data.transport)
                server.transport = data.transport
            if data.timeout_seconds is not None:
                _check_timeout(data.timeout_seconds)
                server.timeout_seconds = data.timeout_seconds
            if data.enabled is not None:
                server.enabled = data.enabled
            server.updated_at = _now()  # invalidates cached tool lists for this server
            session.commit()
            return server

    def _delete(self, tenant_id: str, server_id: str) -> None:
        with self._sf() as session:
            repo = McpServerRepository(session, tenant_id)
            server = repo.get(server_id)
            if server is None:
                raise NotFoundError("MCP server not found")
            repo.delete(server)
            session.commit()

    def _connection(self, tenant_id: str, server_id: str):
        with self._sf() as session:
            server = McpServerRepository(session, tenant_id).get(server_id)
            if server is None:
                raise NotFoundError("MCP server not found")
            return connection_for(self._settings, server)

    # ---- async API ----
    async def list(self, tenant_id: str) -> list[McpServer]:
        return await asyncio.to_thread(self._list, tenant_id)

    async def create(self, tenant_id: str, data: McpSettings) -> McpServer:
        return await asyncio.to_thread(self._create, tenant_id, data)

    async def update(self, tenant_id: str, server_id: str, data: McpSettings) -> McpServer:
        return await asyncio.to_thread(self._update, tenant_id, server_id, data)

    async def delete(self, tenant_id: str, server_id: str) -> None:
        await asyncio.to_thread(self._delete, tenant_id, server_id)

    async def test(self, tenant_id: str, server_id: str) -> McpTestResult:
        """Connects with the saved configuration and lists the server's tools."""
        conn = await asyncio.to_thread(self._connection, tenant_id, server_id)
        try:
            return McpTestResult(True, await self._client.list_tools(conn))
        except Exception as exc:
            message = describe_failure(exc)
            if "Could not reach" in message and is_local_url(conn.url):
                message += " Running in Docker? Use host.docker.internal instead of localhost."
            return McpTestResult(False, [], message)
