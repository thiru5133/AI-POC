"""API key check for the MCP endpoint (ASGI middleware). Fails closed: with no keys configured nothing gets in."""

import hmac
import os

from starlette.responses import JSONResponse


def configured_keys() -> list[str]:
    """GB_MCP_API_KEYS is a comma-separated list, so a key can be rotated or issued per client."""
    return [k.strip() for k in os.getenv("GB_MCP_API_KEYS", "").split(",") if k.strip()]


class ApiKeyMiddleware:
    def __init__(self, app, keys: list[str]):
        self.app = app
        self._keys = [k.encode() for k in keys]

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self._allowed(scope):
            response = JSONResponse(
                {"error": {"code": "unauthorized", "message": "A valid API key is required (X-API-Key header)"}},
                status_code=401,
            )
            return await response(scope, receive, send)
        await self.app(scope, receive, send)

    def _allowed(self, scope) -> bool:
        given = dict(scope["headers"]).get(b"x-api-key", b"")
        # compare against every key without short-circuiting on the first match
        matches = [hmac.compare_digest(given, key) for key in self._keys]
        return bool(given) and any(matches)
