"""Custom HTTP headers an admin attaches to requests to their MCP server.

Stored per server as a list of {"name", "value", "secret"}. Secret values are Fernet-encrypted at rest and are
never returned by the API (only whether one is saved); non-secret values are stored and shown as plain text.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError
from app.mcp.security import decrypt_secret, encrypt_secret

MAX_HEADERS = 10
MAX_VALUE_LENGTH = 2000
_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,60}$")  # RFC 9110 "token"
# Owned by the HTTP / MCP protocol layers: letting a tenant set these could break or smuggle requests.
_RESERVED = {
    "host", "content-length", "content-type", "accept", "transfer-encoding", "connection", "upgrade",
    "te", "trailer", "keep-alive", "proxy-authorization", "mcp-session-id", "mcp-protocol-version",
    "last-event-id",
}


class InvalidMcpConfigError(AppError):
    status_code = 422
    code = "invalid_mcp_config"


@dataclass
class HeaderInput:
    name: str
    value: str | None = None  # None / "" on a secret header that is already saved = keep the saved value
    secret: bool = False


def to_plain(settings: Settings, stored: list[dict[str, Any]] | None) -> dict[str, str]:
    """The headers to send: secrets decrypted."""
    return {h["name"]: decrypt_secret(settings, h["value"]) if h.get("secret") else h["value"] for h in stored or []}


def to_public(stored: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """What the API may show: names always, values only for non-secret headers."""
    return [
        {
            "name": h["name"],
            "secret": bool(h.get("secret")),
            "value": None if h.get("secret") else h["value"],
            "has_value": bool(h["value"]),
        }
        for h in stored or []
    ]


def build_stored(
    settings: Settings, incoming: list[HeaderInput], existing: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Validates `incoming` and returns the list to store, keeping saved secret values that were not re-sent."""
    if len(incoming) > MAX_HEADERS:
        raise InvalidMcpConfigError(f"At most {MAX_HEADERS} headers can be set")
    saved = {h["name"].lower(): h for h in existing or []}
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for header in incoming:
        name = header.name.strip()
        key = name.lower()
        if not _NAME_RE.match(name):
            raise InvalidMcpConfigError(f"'{name}' is not a valid header name")
        if key in _RESERVED:
            raise InvalidMcpConfigError(f"The '{name}' header is managed by the system and cannot be set")
        if key in seen:
            raise InvalidMcpConfigError(f"The '{name}' header is listed twice")
        seen.add(key)

        value = header.value
        if not value:
            previous = saved.get(key)
            if previous is None or not previous.get("value") or not header.secret:
                # nothing saved to keep (a saved secret is only ever kept as a secret: it cannot be un-hidden)
                raise InvalidMcpConfigError(f"Enter a value for the '{name}' header")
            kept = previous["value"] if previous.get("secret") else encrypt_secret(settings, previous["value"])
            result.append({"name": name, "value": kept, "secret": True})
            continue
        if len(value) > MAX_VALUE_LENGTH or any(c in value for c in "\r\n\x00"):
            raise InvalidMcpConfigError(f"The value of the '{name}' header is not valid")
        result.append({"name": name, "value": encrypt_secret(settings, value) if header.secret else value, "secret": header.secret})
    return result
