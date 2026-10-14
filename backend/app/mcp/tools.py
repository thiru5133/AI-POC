"""Per-tenant MCP tools for the conversation engine.

`McpToolSource.for_tenant(tenant_id)` builds a `McpToolSet` from ONLY that tenant's enabled servers, loaded
through the tenant-scoped repository. The tool set can call nothing but those servers, with those credentials.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from app.ai.base import ToolDefinition
from app.core.config import Settings
from app.mcp.client import McpClient, McpConnection, McpToolInfo
from app.mcp.headers import to_plain
from app.mcp.security import apply_localhost_alias, validate_mcp_url
from app.models import Tenant  # noqa: E402
from app.repositories.mcp import McpServerRepository

log = logging.getLogger(__name__)

TOOL_CACHE_SECONDS = 60
MAX_FEDERATED_PARTNERS = 25
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass(frozen=True)
class ServerSpec:
    id: str
    tenant_id: str
    name: str
    conn: McpConnection
    version: str  # changes when the server's configuration changes; part of the cache key


def slugify(name: str) -> str:
    return _NAME_RE.sub("_", name.strip().lower()).strip("_") or "server"


def connection_for(settings: Settings, row) -> McpConnection:
    """The connection to use for a saved server (URL re-validated, secret headers decrypted)."""
    url = apply_localhost_alias(row.url, settings.mcp_localhost_alias)
    url = validate_mcp_url(url, settings.mcp_allow_private_hosts)  # DNS may have changed since it was saved
    return McpConnection(
        url=url,
        headers=to_plain(settings, row.headers),
        transport=row.transport,
        timeout=float(row.timeout_seconds),
    )


class ToolListCache:
    """Tool lists per (tenant, server, config version). The tenant id is part of every key."""

    def __init__(self, ttl: float = TOOL_CACHE_SECONDS):
        self._ttl = ttl
        self._items: dict[tuple[str, str, str], tuple[float, list[McpToolInfo]]] = {}

    def get(self, spec: ServerSpec) -> list[McpToolInfo] | None:
        hit = self._items.get((spec.tenant_id, spec.id, spec.version))
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        return None

    def put(self, spec: ServerSpec, tools: list[McpToolInfo]) -> None:
        self._items[(spec.tenant_id, spec.id, spec.version)] = (time.monotonic(), tools)


class McpToolSet:
    def __init__(self, client: McpClient):
        self._client = client
        self._routes: dict[str, tuple[ServerSpec, str]] = {}
        self.definitions: list[ToolDefinition] = []

    def add(self, spec: ServerSpec, tools: list[McpToolInfo]) -> None:
        prefix = slugify(spec.name)
        for tool in tools:
            name = f"{prefix}__{_NAME_RE.sub('_', tool.name)}"[:64]
            base, n = name, 2
            while name in self._routes:  # two servers whose names slugify the same
                name = f"{base[:60]}_{n}"
                n += 1
            self._routes[name] = (spec, tool.name)
            description = f"[{spec.name}] {tool.description}".strip()
            self.definitions.append(ToolDefinition(name, description, tool.input_schema))

    def owns(self, name: str) -> bool:
        return name in self._routes

    async def execute(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        spec, tool_name = self._routes[name]
        try:
            result = await self._client.call_tool(spec.conn, tool_name, arguments)
        except Exception as exc:
            log.warning("mcp call failed", extra={"tenant_id": spec.tenant_id, "tool": name, "error": repr(exc)})
            return {"error": f"The '{spec.name}' system could not be reached ({type(exc).__name__})."}, True
        content = result.content if isinstance(result.content, dict) else {"result": result.content}
        return content, result.is_error


class McpToolSource:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        client: McpClient,
        cache: ToolListCache | None = None,
        result_cache=None,
    ):
        self._sf = session_factory
        self._settings = settings
        self._client = client
        self._cache = cache or ToolListCache()
        self._results = result_cache

    def _specs(self, tenant_id: str) -> list[ServerSpec]:
        with self._sf() as session:
            specs = []
            for row in McpServerRepository(session, tenant_id).list_enabled():
                try:
                    conn = connection_for(self._settings, row)
                except Exception as exc:
                    log.warning("mcp server skipped", extra={"tenant_id": tenant_id, "server": row.name, "error": repr(exc)})
                    continue
                specs.append(ServerSpec(row.id, tenant_id, row.name, conn, row.updated_at.isoformat()))
            return specs

    async def _tools(self, spec: ServerSpec) -> list[McpToolInfo]:
        cached = self._cache.get(spec)
        if cached is not None:
            return cached
        tools = await self._client.list_tools(spec.conn)
        self._cache.put(spec, tools)
        return tools

    def _marketplace_domain(self, tenant_id: str) -> str | None:
        """The domain id when `tenant_id` is a domain's shared compare-all assistant, else None."""
        with self._sf() as session:
            tenant = session.get(Tenant, tenant_id)
            return tenant.domain_id if tenant is not None and tenant.is_marketplace else None

    def _partner_specs(self, domain_id: str) -> list[tuple[str, ServerSpec]]:
        """(partner name, server) for every enabled server of every active partner in the domain."""
        with self._sf() as session:
            partners = list(
                session.scalars(
                    select(Tenant)
                    .where(Tenant.domain_id == domain_id, Tenant.is_active == true(), Tenant.is_marketplace == false())
                    .order_by(Tenant.name)
                    .limit(MAX_FEDERATED_PARTNERS)
                )
            )
            out = []
            for partner in partners:
                for row in McpServerRepository(session, partner.id).list_enabled():
                    try:
                        conn = connection_for(self._settings, row)
                    except Exception as exc:
                        log.warning("mcp server skipped", extra={"tenant_id": partner.id, "server": row.name, "error": repr(exc)})
                        continue
                    out.append((partner.name, ServerSpec(row.id, partner.id, row.name, conn, row.updated_at.isoformat())))
            return out

    async def for_domain(self, domain_id: str) -> "DomainToolSet":
        """One standard tool per capability, fanned out to every partner of the domain. Never raises."""
        from app.mcp.federation import DomainToolSet

        tool_set = DomainToolSet(self._client, self._results)
        try:
            pairs = await asyncio.to_thread(self._partner_specs, domain_id)
            gate = asyncio.Semaphore(8)

            async def discover(spec: ServerSpec):
                async with gate:
                    return await self._tools(spec)

            results = await asyncio.gather(*(discover(s) for _, s in pairs), return_exceptions=True)
        except Exception:
            log.exception("loading partner tools failed", extra={"domain_id": domain_id})
            return tool_set.finalize()
        for (partner, spec), result in zip(pairs, results):
            if isinstance(result, BaseException):
                log.warning("mcp tool discovery failed", extra={"tenant_id": spec.tenant_id, "server": spec.name, "error": repr(result)})
                continue
            tool_set.add_partner(partner, spec, result)
        return tool_set.finalize()

    async def for_tenant(self, tenant_id: str):
        """Never raises: a broken or unreachable server just contributes no tools. A domain's compare-all assistant
        gets the federated tool set of all its partners; every other tenant gets only its own servers."""
        domain_id = await asyncio.to_thread(self._marketplace_domain, tenant_id)
        if domain_id:
            return await self.for_domain(domain_id)
        tool_set = McpToolSet(self._client)
        try:
            specs = await asyncio.to_thread(self._specs, tenant_id)
            results = await asyncio.gather(*(self._tools(s) for s in specs), return_exceptions=True)
        except Exception:
            log.exception("loading mcp tools failed", extra={"tenant_id": tenant_id})
            return tool_set
        for spec, result in zip(specs, results):
            if isinstance(result, BaseException):
                log.warning("mcp tool discovery failed", extra={"tenant_id": tenant_id, "server": spec.name, "error": repr(result)})
                continue
            tool_set.add(spec, result)
        return tool_set
