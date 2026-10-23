"""MCP server for HolidayBooking: lets an AI assistant check availability, book and cancel hotel rooms.

It holds no state of its own: every tool calls the HolidayBooking backend REST API, so the AI and the web UI
always see the same bookings.

Run:  python server.py                      (streamable HTTP on :8001, path /mcp; used by docker compose)
      MCP_TRANSPORT=stdio python server.py  (for clients that launch the server as a subprocess)

Access: HTTP clients must send an API key in the X-API-Key header (HB_MCP_API_KEYS, comma-separated); the server
refuses to start without one. It talks to the backend with its own, separate key (HB_BACKEND_API_KEY).
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE_URL = os.getenv("HB_API_URL", "http://localhost:8100").rstrip("/")
BACKEND_API_KEY = os.getenv("HB_BACKEND_API_KEY", "")
TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

mcp = FastMCP(
    "HolidayBooking",
    instructions=(
        "Tools for a group of hotels in different cities and countries, each with its own room types and prices. "
        "Dates are ISO (YYYY-MM-DD). Use list_hotels to find hotels by location, check availability before booking, "
        "and confirm the hotel, room type, guest's name, email, dates and number of guests before calling "
        "book_room. Prices are per night in USD."
    ),
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8001")),
)


def _call(method: str, path: str, **kwargs: Any) -> Any:
    """Calls the backend. Business errors (sold out, bad dates...) come back as {'error': ...} so the model can
    explain them to the guest instead of the tool call crashing."""
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
def list_hotels(city: str | None = None, country: str | None = None) -> Any:
    """List the hotels, optionally only those in a city or country. Each shows its location, star rating, number of
    rooms and the lowest nightly price (USD)."""
    params = {k: v for k, v in (("city", city), ("country", country)) if v}
    return _as_object(_call("GET", "/api/hotels", params=params), "hotels")


@mcp.tool()
def get_hotel(hotel: str) -> Any:
    """Details of one hotel: address, description and its room types with price per night and maximum guests.

    Args:
        hotel: Hotel code from list_hotels, e.g. holiday-colombo.
    """
    return _call("GET", f"/api/hotels/{hotel.strip().lower()}")


@mcp.tool()
def check_availability(
    check_in: str,
    check_out: str,
    hotel: str | None = None,
    city: str | None = None,
    country: str | None = None,
    category: str | None = None,
) -> Any:
    """Check which rooms are free for a stay, per hotel and room type, with the total price for the stay.
    Filter by hotel, or search a city or country to compare hotels.

    Args:
        check_in: Arrival date, YYYY-MM-DD.
        check_out: Departure date, YYYY-MM-DD (the guest leaves that morning).
        hotel: Optional hotel code, e.g. holiday-kandy.
        city: Optional city name, e.g. Dubai.
        country: Optional country name, e.g. Sri Lanka.
        category: Optional room type code, e.g. standard, deluxe, suite (types differ per hotel).
    """
    params = {"check_in": check_in, "check_out": check_out}
    for key, value in (("hotel", hotel), ("city", city), ("country", country), ("category", category)):
        if value:
            params[key] = value.strip().lower() if key in ("hotel", "category") else value.strip()
    return _call("GET", "/api/availability", params=params)


@mcp.tool()
def book_room(
    hotel: str, category: str, guest_name: str, guest_email: str, check_in: str, check_out: str, guests: int = 1
) -> Any:
    """Book a room at a hotel. A room of that type is assigned automatically. Returns the booking with its reference.

    Args:
        hotel: Hotel code, e.g. holiday-london.
        category: Room type code at that hotel, e.g. deluxe.
        guest_name: Full name of the guest.
        guest_email: Guest's email address (used to look bookings up later).
        check_in: Arrival date, YYYY-MM-DD.
        check_out: Departure date, YYYY-MM-DD.
        guests: Number of guests; must not exceed the room type's maximum.
    """
    return _call(
        "POST",
        "/api/bookings",
        json={
            "hotel": hotel.strip().lower(),
            "category": category.strip().lower(),
            "guest_name": guest_name,
            "guest_email": guest_email,
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
        },
    )


@mcp.tool()
def get_booking(reference: str) -> Any:
    """Look up one booking by its reference (e.g. HB-1A2B3C4D)."""
    return _call("GET", f"/api/bookings/{reference.strip()}")


@mcp.tool()
def list_bookings(guest_email: str, status: str | None = None) -> Any:
    """List a guest's bookings (at any hotel) by email, optionally filtered by status ('confirmed' or 'cancelled')."""
    params = {"email": guest_email}
    if status:
        params["status"] = status
    return _as_object(_call("GET", "/api/bookings", params=params), "bookings")


@mcp.tool()
def get_contact_info() -> Any:
    """The hotel group's reservations phone number, for a guest who wants to call or be called back. Use it when
    the guest asks how to phone the hotel, or when a booking cannot be completed here."""
    data = _call("GET", "/api/contact")
    if isinstance(data, dict) and "error" in data:
        return data
    phone = data.get("reservations_phone") if isinstance(data, dict) else None
    if not phone:
        return {"error": {"code": "not_configured", "message": "No reservations phone number is configured."}}
    return {"reservations_phone": phone}


@mcp.tool()
def cancel_booking(reference: str) -> Any:
    """Cancel a booking by reference. The room becomes available again. Confirm with the guest first."""
    return _call("POST", f"/api/bookings/{reference.strip()}/cancel")


def serve_http() -> None:
    import uvicorn

    from auth import ApiKeyMiddleware, configured_keys

    keys = configured_keys()
    if not keys:
        raise SystemExit("HB_MCP_API_KEYS is not set: refusing to start an unauthenticated MCP server")
    uvicorn.run(ApiKeyMiddleware(mcp.streamable_http_app(), keys), host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    if TRANSPORT == "stdio":
        mcp.run(transport="stdio")  # the client launches this process itself: no network exposure
    else:
        serve_http()
