"""Member-facing behaviour across several gyms, plus the API key gate."""

import pytest

from .conftest import future


def first_session(client, gym="fitzone-anna-nagar", category=None) -> int:
    """The id of the earliest upcoming session (of a gym / class) with room left, from the seeded timetable."""
    params = {"gym": gym, **({"category": category} if category else {})}
    sessions = client.get("/api/sessions", params=params).json()["sessions"]
    return next(s["session_id"] for s in sessions if s["spots_left"] > 0)


def book(client, session_id, email="member@example.com", name="Asha Rao"):
    return client.post("/api/bookings", json={"session_id": session_id, "member_name": name, "member_email": email})


# ---------- the seeded gyms ----------
def test_several_gyms_in_different_locations_are_seeded(client):
    gyms = client.get("/api/gyms").json()
    assert {g["code"] for g in gyms} == {"fitzone-anna-nagar", "fitzone-t-nagar", "fitzone-adyar", "fitzone-velachery"}
    colombo = next(g for g in gyms if g["code"] == "fitzone-anna-nagar")
    assert colombo["class_type_count"] == 5 and colombo["from_price"] == 300
    assert len(client.get("/api/gyms", params={"city": "chennai"}).json()) == 4
    assert client.get("/api/gyms", params={"country": "Sri Lanka"}).json() == []


def test_gym_details_include_class_types(client):
    gym = client.get("/api/gyms/fitzone-adyar").json()
    assert {t["code"] for t in gym["class_types"]} == {"yoga", "hiit", "pilates"}
    assert client.get("/api/gyms/nowhere").status_code == 404


# ---------- sessions ----------
def test_sessions_default_to_the_coming_week_and_only_show_the_future(client):
    body = client.get("/api/sessions").json()
    assert body["sessions"] and len(body["sessions"]) == len({s["session_id"] for s in body["sessions"]})
    starts = [s["starts_at"] for s in body["sessions"]]
    assert starts == sorted(starts) and starts[0] > future(0, 0)  # nothing in the past: today's sessions are later than midnight
    assert starts[-1][:10] <= future(6)[:10]
    assert {"gym", "class", "trainer", "capacity", "spots_left"} <= set(body["sessions"][0])


def test_sessions_can_be_filtered_by_gym_city_and_class(client):
    colombo = client.get("/api/sessions", params={"gym": "fitzone-anna-nagar"}).json()["sessions"]
    assert {s["gym"]["code"] for s in colombo} == {"fitzone-anna-nagar"}
    assert {s["class"]["code"] for s in colombo} == {"yoga", "hiit", "spin", "zumba", "strength"}
    yoga = client.get("/api/sessions", params={"category": "yoga"}).json()["sessions"]
    assert {s["gym"]["code"] for s in yoga} == {"fitzone-anna-nagar", "fitzone-t-nagar", "fitzone-adyar", "fitzone-velachery"}
    chennai = client.get("/api/sessions", params={"city": "Chennai"}).json()["sessions"]
    assert {s["gym"]["code"] for s in chennai} == {"fitzone-anna-nagar", "fitzone-t-nagar", "fitzone-adyar", "fitzone-velachery"}
    assert client.get("/api/sessions", params={"gym": "nowhere"}).json()["error"]["code"] == "unknown_gym"


def test_session_date_range_is_validated(client):
    assert client.get("/api/sessions", params={"date_from": "2000-01-01"}).json()["error"]["code"] == "invalid_dates"
    start, end = future(3)[:10], future(2)[:10]
    assert client.get("/api/sessions", params={"date_from": start, "date_to": end}).status_code == 422
    assert client.get("/api/sessions", params={"date_from": future(0)[:10], "date_to": future(400)[:10]}).status_code == 422
    one_day = client.get("/api/sessions", params={"date_from": future(2)[:10], "date_to": future(2)[:10]}).json()
    assert {s["starts_at"][:10] for s in one_day["sessions"]} == {future(2)[:10]}


# ---------- bookings ----------
def test_booking_a_class_reduces_the_spots_and_can_be_looked_up(client):
    sid = first_session(client, category="yoga")
    before = next(s for s in client.get("/api/sessions", params={"gym": "fitzone-anna-nagar"}).json()["sessions"] if s["session_id"] == sid)
    resp = book(client, sid, email="  Asha@Example.com ")
    assert resp.status_code == 201
    booking = resp.json()
    assert booking["reference"].startswith("GB-") and booking["status"] == "confirmed"
    assert (booking["member_email"], booking["class_code"], booking["price"], booking["gym_name"]) == ("asha@example.com", "yoga", 300, "FitZone Anna Nagar")
    after = next(s for s in client.get("/api/sessions", params={"gym": "fitzone-anna-nagar"}).json()["sessions"] if s["session_id"] == sid)
    assert after["spots_left"] == before["spots_left"] - 1
    assert client.get(f"/api/bookings/{booking['reference'].lower()}").json()["reference"] == booking["reference"]
    mine = client.get("/api/bookings", params={"email": "ASHA@example.com"}).json()
    assert [b["reference"] for b in mine] == [booking["reference"]]


def test_the_same_member_cannot_book_a_class_twice(client):
    sid = first_session(client)
    assert book(client, sid).status_code == 201
    dup = book(client, sid, email="MEMBER@example.com")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_booked"
    assert book(client, sid, email="other@example.com").status_code == 201


def test_a_full_class_cannot_be_booked_until_someone_cancels(client, root):
    sid = first_session(client)
    capacity = next(s for s in client.get("/api/sessions", params={"gym": "fitzone-anna-nagar"}).json()["sessions"] if s["session_id"] == sid)["capacity"]
    client.patch(f"/api/admin/sessions/{sid}", json={"capacity": 2}, headers=root)
    refs = [book(client, sid, email=f"m{i}@example.com").json()["reference"] for i in range(2)]
    full = book(client, sid, email="late@example.com")
    assert full.status_code == 409 and full.json()["error"]["code"] == "class_full"
    assert capacity >= 2
    client.post(f"/api/bookings/{refs[0]}/cancel")
    assert book(client, sid, email="late@example.com").status_code == 201


def test_cancelling_frees_the_spot_and_cannot_be_repeated(client):
    sid = first_session(client)
    ref = book(client, sid).json()["reference"]
    cancelled = client.post(f"/api/bookings/{ref}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"]
    again = client.post(f"/api/bookings/{ref}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_cancelled"
    assert book(client, sid).status_code == 201  # the same member can rebook after cancelling
    assert client.get("/api/bookings", params={"status": "cancelled"}).json()[0]["reference"] == ref


def test_unknown_inactive_and_started_sessions_are_rejected(client, root):
    unknown = book(client, 999999)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "unknown_session"
    sid = first_session(client)
    client.patch(f"/api/admin/sessions/{sid}", json={"active": False}, headers=root)
    assert book(client, sid).status_code == 404


def test_booking_input_is_validated(client):
    sid = first_session(client)
    assert client.post("/api/bookings", json={"session_id": sid, "member_name": "A", "member_email": "nope"}).status_code == 422
    assert client.post("/api/bookings", json={"session_id": sid, "member_name": "   ", "member_email": "a@example.com"}).status_code == 422
    assert client.post("/api/bookings", json={"session_id": 0, "member_name": "A", "member_email": "a@example.com"}).status_code == 422
    assert client.get("/api/bookings/GB-NOPE0000").status_code == 404


# ---------- API key ----------
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_the_api_key_is_required_everywhere_except_health(client, headers):
    client.headers.pop("X-API-Key")
    assert client.get("/api/health").status_code == 200
    for path in ("/api/gyms", "/api/sessions", "/api/bookings", "/api/admin/gyms"):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 401 and resp.json()["error"]["code"] == "unauthorized", path


def test_with_no_key_configured_every_request_is_refused(client, monkeypatch):
    monkeypatch.delenv("GB_BACKEND_API_KEY")
    assert client.get("/api/gyms").status_code == 401
