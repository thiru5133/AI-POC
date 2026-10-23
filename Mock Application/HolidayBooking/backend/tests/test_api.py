"""Guest-facing behaviour across several hotels, plus the API key gate."""

import pytest

from .conftest import day


def book(client, hotel="holiday-colombo", category="suite", start=10, end=12, email="guest@example.com", guests=2):
    return client.post(
        "/api/bookings",
        json={
            "hotel": hotel,
            "category": category,
            "guest_name": "Asha Rao",
            "guest_email": email,
            "check_in": day(start),
            "check_out": day(end),
            "guests": guests,
        },
    )


def stay(client, **params):
    return client.get("/api/availability", params={"check_in": day(10), "check_out": day(12), **params}).json()


# ---------- the seeded hotels ----------
def test_several_hotels_in_different_locations_are_seeded(client):
    hotels = client.get("/api/hotels").json()
    assert {h["code"] for h in hotels} == {
        "holiday-colombo", "holiday-kandy", "holiday-galle", "holiday-dubai", "holiday-singapore", "holiday-london",
    }
    by_code = {h["code"]: h for h in hotels}
    assert (by_code["holiday-dubai"]["city"], by_code["holiday-dubai"]["country"]) == ("Dubai", "United Arab Emirates")
    assert by_code["holiday-colombo"]["room_count"] == 22 and by_code["holiday-colombo"]["from_price"] == 120
    assert by_code["holiday-kandy"]["room_count"] == 12 and by_code["holiday-kandy"]["from_price"] == 85
    assert sum(h["room_count"] for h in hotels) == 22 + 12 + 17 + 29 + 19 + 26


def test_hotels_can_be_filtered_by_location(client):
    assert [h["code"] for h in client.get("/api/hotels", params={"country": "sri lanka"}).json()] == [
        "holiday-colombo", "holiday-galle", "holiday-kandy",
    ]
    assert [h["code"] for h in client.get("/api/hotels", params={"city": "LONDON"}).json()] == ["holiday-london"]
    assert client.get("/api/hotels", params={"city": "Paris"}).json() == []


def test_each_hotel_has_its_own_room_types_and_prices(client):
    kandy = client.get("/api/hotels/holiday-kandy").json()
    assert [(t["code"], t["price_per_night"], t["total_rooms"]) for t in kandy["room_types"]] == [
        ("standard", 85, 6), ("deluxe", 140, 4), ("suite", 260, 2),
    ]
    dubai = {t["code"]: t for t in client.get("/api/hotels/holiday-dubai").json()["room_types"]}
    assert dubai["royal"]["price_per_night"] == 1400 and dubai["royal"]["max_guests"] == 6
    colombo = {t["code"]: t for t in client.get("/api/hotels/holiday-colombo").json()["room_types"]}
    assert colombo["suite"]["price_per_night"] == 450  # the same type name costs differently elsewhere
    assert client.get("/api/hotels/nowhere").status_code == 404


# ---------- availability ----------
def test_availability_covers_all_hotels_or_a_filtered_set(client):
    everywhere = stay(client)
    assert len(everywhere["results"]) == 6 and everywhere["nights"] == 2
    kandy = stay(client, hotel="holiday-kandy")["results"]
    assert len(kandy) == 1 and kandy[0]["hotel"]["city"] == "Kandy"
    suite = kandy[0]["room_types"][-1]
    assert (suite["code"], suite["available_rooms"], suite["total_for_stay"]) == ("suite", 2, 520)
    suites_in_sl = stay(client, country="Sri Lanka", category="suite")["results"]
    assert {r["hotel"]["code"] for r in suites_in_sl} == {"holiday-colombo", "holiday-kandy"}  # Galle has no 'suite'
    assert client.get("/api/availability", params={"check_in": day(1), "check_out": day(2), "hotel": "x"}).status_code == 404


def test_availability_drops_after_a_booking_and_recovers_on_cancel(client):
    def suites():
        result = stay(client, hotel="holiday-colombo", category="suite")["results"][0]["room_types"][0]
        return result["available_rooms"], result["total_for_stay"]

    assert suites() == (3, 900)
    ref = book(client).json()["reference"]
    assert suites() == (2, 900)
    assert client.post(f"/api/bookings/{ref}/cancel").json()["status"] == "cancelled"
    assert suites() == (3, 900)


# ---------- booking ----------
def test_booking_is_priced_by_the_hotel_and_names_its_location(client):
    b = book(client, hotel="holiday-kandy", category="deluxe", start=5, end=8).json()
    assert (b["total_price"], b["nights"], b["status"]) == (420, 3, "confirmed")
    assert (b["hotel_code"], b["hotel_name"], b["hotel_city"], b["hotel_country"]) == (
        "holiday-kandy", "Holiday Kandy Hills", "Kandy", "Sri Lanka",
    )
    assert b["room_number"] == "201" and b["reference"].startswith("HB-")


def test_sold_out_is_per_hotel_and_dates_can_be_reused_after_checkout(client):
    assert book(client, "holiday-colombo", "presidential").status_code == 201
    again = book(client, "holiday-colombo", "presidential")
    assert again.status_code == 409 and again.json()["error"]["code"] == "sold_out"
    assert book(client, "holiday-dubai", "royal").status_code == 201  # another hotel is unaffected
    assert book(client, "holiday-colombo", "presidential", start=12, end=14).status_code == 201  # check-out day is free


def test_overlapping_dates_are_blocked_per_room(client):
    book(client, "holiday-colombo", "presidential", start=10, end=14)
    assert book(client, "holiday-colombo", "presidential", start=12, end=16).status_code == 409
    assert book(client, "holiday-colombo", "presidential", start=8, end=11).status_code == 409


def test_validation(client):
    assert book(client, start=12, end=10).status_code == 422
    assert book(client, start=-3, end=2).status_code == 422
    assert book(client, start=1, end=60).status_code == 422
    assert book(client, hotel="holiday-paris").json()["error"]["code"] == "unknown_hotel"
    assert book(client, hotel="holiday-galle", category="suite").json()["error"]["code"] == "unknown_category"
    assert book(client, category="standard", guests=3).json()["error"]["code"] == "too_many_guests"
    assert book(client, email="not-an-email").status_code == 422
    assert client.post("/api/bookings", json={"category": "suite"}).status_code == 422  # hotel is required


def test_cancel_twice_unknown_reference_and_lookup(client):
    ref = book(client, email="Guest@Example.com").json()["reference"]
    assert client.get(f"/api/bookings/{ref.lower()}").status_code == 200
    assert [b["reference"] for b in client.get("/api/bookings", params={"email": "GUEST@example.com"}).json()] == [ref]
    assert client.get("/api/bookings", params={"email": "other@example.com"}).json() == []
    assert client.post(f"/api/bookings/{ref}/cancel").status_code == 200
    assert client.post(f"/api/bookings/{ref}/cancel").json()["error"]["code"] == "already_cancelled"
    assert client.get("/api/bookings/HB-NOPE").status_code == 404


# ---------- API key ----------
def test_api_requires_the_key_but_health_is_open(client):
    anonymous = {"X-API-Key": ""}
    assert client.get("/api/health", headers=anonymous).status_code == 200  # needed by the container healthcheck
    for path in ("/api/hotels", "/api/bookings", "/api/bookings/HB-X", "/api/admin/hotels", "/api/auth/me"):
        assert client.get(path, headers=anonymous).status_code == 401
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    created = client.post("/api/bookings", json={}, headers=anonymous)
    assert created.status_code == 401 and created.json()["error"]["code"] == "unauthorized"
    assert client.post("/api/auth/login", json={"email": "a", "password": "b"}, headers=anonymous).status_code == 401
    assert client.get("/api/hotels").status_code == 200  # the right key works


def test_api_fails_closed_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.delenv("HB_BACKEND_API_KEY")
    assert client.get("/api/hotels").status_code == 401
    assert client.get("/api/hotels", headers={"X-API-Key": ""}).status_code == 401


@pytest.mark.parametrize("path", ["/api/hotels", "/api/availability?check_in=2030-01-01&check_out=2030-01-02"])
def test_guest_endpoints_need_no_login(client, path):
    assert client.get(path).status_code == 200


# ---------- the reservations number ----------
def test_contact_gives_the_configured_number(client, monkeypatch):
    monkeypatch.setenv("HB_RESERVATIONS_PHONE", " +17692630020 ")
    assert client.get("/api/contact").json() == {"reservations_phone": "+17692630020"}


def test_contact_is_null_when_no_number_is_configured(client, monkeypatch):
    monkeypatch.delenv("HB_RESERVATIONS_PHONE", raising=False)
    assert client.get("/api/contact").json() == {"reservations_phone": None}
    monkeypatch.setenv("HB_RESERVATIONS_PHONE", "  ")
    assert client.get("/api/contact").json() == {"reservations_phone": None}


def test_contact_needs_the_api_key(client):
    assert client.get("/api/contact", headers={"X-API-Key": "wrong"}).status_code == 401
