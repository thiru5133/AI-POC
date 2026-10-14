"""One standard tool per capability across every partner of a domain.

Without this, an assistant comparing five hotels would see five copies of `check_availability` (one per partner's MCP
server) and spend five model round trips calling them one by one. A `DomainToolSet` instead offers each capability
once: the model makes ONE call and the platform fans it out to the partners in parallel, then merges the answers.

What keeps this safe and cheap:
- the fan-out is bounded (parallelism limit, per-call timeout, result size cap) and one slow or broken partner only
  shows up as an error entry next to the other partners' answers;
- only read-only tools fan out. Anything that changes state (a booking, a cancellation) must name exactly one
  `partner`, so a booking can never be placed at every hotel at once;
- every call still goes through that partner's own saved connection and credentials; nothing is shared between partners;
- identical read-only lookups are answered from a short-lived cache.
"""

import asyncio
import copy
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.ai.base import ToolDefinition
from app.mcp.client import MAX_RESULT_CHARS, McpClient, McpToolInfo
from app.mcp.tools import ServerSpec

log = logging.getLogger(__name__)

MAX_PARALLEL_CALLS = 8
CALL_TIMEOUT_SECONDS = 10.0
RESULT_CACHE_SECONDS = 20
MIN_PER_PARTNER_CHARS = 800
_READ_PREFIXES = ("search", "get", "list", "check", "find", "view", "lookup", "read", "describe", "compare", "quote", "show", "fetch")
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def is_read_only(tool: McpToolInfo) -> bool:
    """The server's own `readOnlyHint` wins; without one, only obviously read-named tools count as read-only."""
    if tool.read_only is not None:
        return tool.read_only
    return tool.name.lower().startswith(_READ_PREFIXES)


@dataclass(frozen=True)
class PartnerRoute:
    partner: str
    spec: ServerSpec
    tool: str


class ResultCache:
    """Short-lived answers to identical read-only fan-out calls (same tool, arguments and set of partners)."""

    def __init__(self, ttl: float = RESULT_CACHE_SECONDS):
        self._ttl = ttl
        self._items: dict[str, tuple[float, tuple[dict[str, Any], bool]]] = {}

    def get(self, key: str):
        hit = self._items.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        self._items.pop(key, None)
        return None

    def put(self, key: str, value: tuple[dict[str, Any], bool]) -> None:
        if len(self._items) > 500:  # crude bound; entries are tiny and expire in seconds
            self._items.clear()
        self._items[key] = (time.monotonic(), value)


@dataclass
class _Capability:
    info: McpToolInfo
    routes: list[PartnerRoute]


class DomainToolSet:
    def __init__(self, client: McpClient, cache: ResultCache | None = None):
        self._client = client
        self._cache = cache or ResultCache()
        self._caps: dict[str, _Capability] = {}  # exposed tool name -> capability
        self.definitions: list[ToolDefinition] = []
        self._finalized = False

    def add_partner(self, partner: str, spec: ServerSpec, tools: list[McpToolInfo]) -> None:
        for tool in tools:
            name = f"all_{_NAME_RE.sub('_', tool.name)}"[:64]
            cap = self._caps.setdefault(name, _Capability(tool, []))
            cap.routes.append(PartnerRoute(partner, spec, tool.name))

    def finalize(self) -> "DomainToolSet":
        """Builds the model-facing definitions once every partner has been added."""
        self.definitions = []
        for name, cap in self._caps.items():
            partners = sorted({r.partner for r in cap.routes})
            schema = copy.deepcopy(cap.info.input_schema) or {"type": "object", "properties": {}}
            props = schema.setdefault("properties", {})
            read_only = is_read_only(cap.info)
            props["partner"] = {
                "type": "string",
                "enum": partners,
                "description": (
                    "Leave out to ask every partner at once."
                    if read_only
                    else "REQUIRED: the one partner to act with (this changes something, so it is never sent to everyone)."
                ),
            }
            if not read_only:
                schema["required"] = [*schema.get("required", []), "partner"]
            scope = f"all {len(partners)} partners ({', '.join(partners)})" if read_only else "ONE named partner"
            description = f"[{scope}] {cap.info.description}".strip()
            self.definitions.append(ToolDefinition(name, description, schema))
        self._finalized = True
        return self

    def owns(self, name: str) -> bool:
        return name in self._caps

    async def execute(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        cap = self._caps[name]
        args = dict(arguments)
        wanted = args.pop("partner", None)
        read_only = is_read_only(cap.info)
        partners = sorted({r.partner for r in cap.routes})

        if wanted:
            routes = [r for r in cap.routes if r.partner.lower() == str(wanted).strip().lower()]
            if not routes:
                return {"error": f"Unknown partner '{wanted}'.", "partners": partners}, True
        elif read_only:
            routes = cap.routes
        else:
            return {"error": "This changes something: name the one partner to use.", "partners": partners}, True

        cache_key = None
        if read_only:
            cache_key = json.dumps([name, args, sorted(f"{r.spec.id}" for r in routes)], sort_keys=True, default=str)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        gate = asyncio.Semaphore(MAX_PARALLEL_CALLS)
        per_partner = max(MIN_PER_PARTNER_CHARS, MAX_RESULT_CHARS // len(routes))

        async def call(route: PartnerRoute) -> dict[str, Any]:
            async with gate:
                try:
                    timeout = min(route.spec.conn.timeout, CALL_TIMEOUT_SECONDS)
                    result = await asyncio.wait_for(
                        self._client.call_tool(route.spec.conn, route.tool, args), timeout=timeout
                    )
                except Exception as exc:
                    log.warning(
                        "partner call failed",
                        extra={"tenant_id": route.spec.tenant_id, "tool": route.tool, "error": repr(exc)},
                    )
                    return {"partner": route.partner, "error": f"could not be reached ({type(exc).__name__})"}
            content = result.content if isinstance(result.content, dict) else {"result": result.content}
            text = json.dumps(content, default=str)
            if len(text) > per_partner:
                content = {"truncated": True, "text": text[:per_partner]}
            if result.is_error:
                return {"partner": route.partner, "error": content}
            return {"partner": route.partner, "result": content}

        results = await asyncio.gather(*(call(r) for r in routes))
        failed = sum(1 for r in results if "error" in r)
        output = {"partners_asked": len(routes), "partners_failed": failed, "results": list(results)}
        value = (output, failed == len(results))
        if cache_key and failed == 0:
            self._cache.put(cache_key, value)
        return value
