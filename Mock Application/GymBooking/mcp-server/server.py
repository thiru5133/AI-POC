"""MCP server for GymBooking: lets an AI assistant browse gyms and classes, book and cancel class spots.

It holds no state of its own: every tool calls the GymBooking backend REST API, so the AI and the web UI
always see the same bookings.

Run:  python server.py                      (streamable HTTP on :8001, path /mcp; used by docker compose)
      MCP_TRANSPORT=stdio python server.py  (for clients that launch the server as a subprocess)

Access: HTTP clients must send an API key in the X-API-Key header (GB_MCP_API_KEYS, comma-separated); the server
refuses to start without one. It talks to the backend with its own, separate key (GB_BACKEND_API_KEY).
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE_URL = os.getenv("GB_API_URL", "http://localhost:8200").rstrip("/")
BACKEND_API_KEY = os.getenv("GB_BACKEND_API_KEY", "")
TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

mcp = FastMCP(
    "GymBooking",
    instructions=(
        "Tools for a group of gyms in different areas of Chennai, India, each with its own class types and prices. "
        "Class times are UTC (ISO 8601). Use list_gyms to find gyms by location and list_classes to see the "
        "upcoming class sessions with spots left; every session has a session_id. Confirm the session, the "
        "member's name and email before calling book_class. Prices are per class in INR (Indian rupees)."
    ),
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8001")),
)


def _call(method: str, path: str, **kwargs: Any) -> Any:
    """Calls the backend. Business errors (class full, bad dates...) come back as {'error': ...} so the model can
    explain them to the member instead of the tool call crashing."""
    try:
        resp = httpx.request(
            method, f"{API_BASE_URL}{path}", timeout=15, headers={"X-API-Key": BACKEND_API_KEY}, **kwargs
        )
    except httpx.HTTPError as exc:
        return {"error": {"code": "backend_unreachable", "message": f"Booking system unavailable: {exc}"}}
    try:
        data = resp.json()
    except ValueError:
        return {"error": {"code": "bad_response", "message": f"Unexpected response ({resp.status_code})"}}
    if resp.status_code == 422 and isinstance(data, dict) and "detail" in data:
        details = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in data["detail"])
        return {"error": {"code": "invalid_request", "message": details}}
    return data


def _as_object(data: Any, key: str) -> Any:
    """Tools should return one JSON object (a bare list is split into several content blocks by MCP)."""
    return {key: data} if isinstance(data, list) else data


@mcp.tool()
def list_gyms(city: str | None = None, country: str | None = None) -> Any:
    """List the gyms, optionally only those in a city or country. Each shows its location, number of class types
    and the lowest class price (INR)."""
    params = {k: v for k, v in (("city", city), ("country", country)) if v}
    return _as_object(_call("GET", "/api/gyms", params=params), "gyms")


@mcp.tool()
def get_gym(gym: str) -> Any:
    """Details of one gym: address, description and its class types with duration and price.

    Args:
        gym: Gym code from list_gyms, e.g. fitzone-anna-nagar.
    """
    return _call("GET", f"/api/gyms/{gym.strip().lower()}")


@mcp.tool()
def list_classes(
    date_from: str | None = None,
    date_to: str | None = None,
    gym: str | None = None,
    city: str | None = None,
    category: str | None = None,
) -> Any:
    """List upcoming class sessions with the spots still free. Defaults to the next 7 days. Filter by gym, or search a
    city to compare gyms. Every session has a session_id to use with book_class.

    Args:
        date_from: First day, YYYY-MM-DD (default today).
        date_to: Last day, YYYY-MM-DD (default 6 days after date_from).
        gym: Optional gym code, e.g. fitzone-velachery.
        city: Optional city name, e.g. Dubai.
        category: Optional class type code, e.g. yoga, hiit, spin (types differ per gym).
    """
    params = {}
    for key, value in (("date_from", date_from), ("date_to", date_to), ("gym", gym), ("city", city), ("category", category)):
        if value:
            params[key] = value.strip().lower() if key in ("gym", "category") else value.strip()
    return _call("GET", "/api/sessions", params=params)


@mcp.tool()
def book_class(session_id: int, member_name: str, member_email: str) -> Any:
    """Book one spot in a class session. Returns the booking with its reference.

    Args:
        session_id: The session_id from list_classes.
        member_name: Full name of the member.
        member_email: Member's email address (used to look bookings up later).
    """
    return _call(
        "POST", "/api/bookings", json={"session_id": session_id, "member_name": member_name, "member_email": member_email}
    )


@mcp.tool()
def get_booking(reference: str) -> Any:
    """Look up one booking by its reference (e.g. GB-1A2B3C4D)."""
    return _call("GET", f"/api/bookings/{reference.strip()}")


@mcp.tool()
def list_bookings(member_email: str, status: str | None = None) -> Any:
    """List a member's bookings (at any gym) by email, optionally filtered by status ('confirmed' or 'cancelled')."""
    params = {"email": member_email}
    if status:
        params["status"] = status
    return _as_object(_call("GET", "/api/bookings", params=params), "bookings")


@mcp.tool()
def cancel_booking(reference: str) -> Any:
    """Cancel a booking by reference. The spot becomes available again. Confirm with the member first."""
    return _call("POST", f"/api/bookings/{reference.strip()}/cancel")


def serve_http() -> None:
    import uvicorn

    from auth import ApiKeyMiddleware, configured_keys

    keys = configured_keys()
    if not keys:
        raise SystemExit("GB_MCP_API_KEYS is not set: refusing to start an unauthenticated MCP server")
    uvicorn.run(ApiKeyMiddleware(mcp.streamable_http_app(), keys), host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    if TRANSPORT == "stdio":
        mcp.run(transport="stdio")  # the client launches this process itself: no network exposure
    else:
        serve_http()
