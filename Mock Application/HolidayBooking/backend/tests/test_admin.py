"""Staff login, hotel / room type / room administration and user management."""

import pytest

from app import accounts, db
from app.seed import seed_superadmin

from .conftest import SUPER_EMAIL, SUPER_PASSWORD, day, login
from .test_api import book

NEW_HOTEL = {
    "name": "Holiday Paris Louvre", "city": "Paris", "country": "France",
    "address": "3 Rue de Rivoli", "description": "Steps from the Louvre.", "stars": 4,
}


def add_hotel(client, headers, **overrides):
    return client.post("/api/admin/hotels", json={**NEW_HOTEL, **overrides}, headers=headers)


def add_type(client, headers, hotel, name="Standard", price=150, guests=2, **extra):
    return client.post(
        f"/api/admin/hotels/{hotel}/room-types",
        json={"name": name, "price_per_night": price, "max_guests": guests, **extra},
        headers=headers,
    )


# ---------- login ----------
def test_superadmin_is_seeded_once_and_can_log_in(client):
    users = accounts.list_users(db.get_engine().connect())
    assert [(u["email"], u["role"], u["active"]) for u in users] == [(SUPER_EMAIL, "superadmin", True)]
    assert "password_hash" not in users[0]
    seed_superadmin()  # restarting does not add or reset anything
    assert len(accounts.list_users(db.get_engine().connect())) == 1
    resp = client.post("/api/auth/login", json={"email": " Root@Example.com ", "password": SUPER_PASSWORD})
    assert resp.status_code == 200 and resp.json()["user"]["role"] == "superadmin"
    assert "password" not in resp.text


def test_no_superadmin_is_created_without_credentials(client, monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    db.reset_engine()
    from app import migrate

    migrate.upgrade()
    monkeypatch.delenv("HB_SUPERADMIN_EMAIL")
    monkeypatch.delenv("HB_SUPERADMIN_PASSWORD")
    seed_superadmin()
    assert accounts.list_users(db.get_engine().connect()) == []


def test_wrong_password_and_unknown_user_look_identical(client):
    wrong = client.post("/api/auth/login", json={"email": SUPER_EMAIL, "password": "nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_is_throttled_after_repeated_failures(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": SUPER_EMAIL, "password": "bad-password"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "too_many_attempts"


def test_session_cookie_works_and_logout_ends_it(client):
    resp = client.post("/api/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD})
    cookie = resp.headers["set-cookie"].lower()
    assert "hb_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["email"] == SUPER_EMAIL  # the cookie alone authenticates
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_the_token_server_side(client, root):
    assert client.get("/api/auth/me", headers=root).status_code == 200
    client.post("/api/auth/logout", headers=root)
    assert client.get("/api/auth/me", headers=root).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer made-up"}).status_code == 401


# ---------- access control ----------
def test_admin_endpoints_need_a_login_and_users_need_a_superadmin(client, root, staff):
    for method, path in (("get", "/api/admin/hotels"), ("get", "/api/admin/bookings"), ("get", "/api/admin/users")):
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/api/admin/hotels", headers=staff).status_code == 200  # admins manage hotels...
    for method, path, body in (
        ("get", "/api/admin/users", None),
        ("post", "/api/admin/users", {"email": "x@example.com", "name": "X", "password": "password-123"}),
        ("patch", "/api/admin/users/1", {"active": False}),
        ("post", "/api/admin/users/1/reset-password", {"password": "password-123"}),
    ):
        resp = getattr(client, method)(path, headers=staff, **({"json": body} if body else {}))
        assert resp.status_code == 403, (path, resp.text)  # ...but not users
    assert client.get("/api/admin/users", headers=root).status_code == 200


# ---------- hotels ----------
def test_admin_adds_a_hotel_with_room_types_and_rooms_that_guests_can_then_book(client, root):
    created = add_hotel(client, root)
    assert created.status_code == 201
    hotel = created.json()
    assert hotel["code"] == "holiday-paris-louvre" and hotel["active"] is True and hotel["room_count"] == 0

    standard = add_type(client, root, hotel["code"], "Standard", 150, 2).json()
    suite = add_type(client, root, hotel["code"], "Suite", 400, 4, description="Corner suite").json()
    assert standard["code"] == "standard" and suite["description"] == "Corner suite"

    rooms = client.post(
        f"/api/admin/hotels/{hotel['code']}/rooms", json={"room_type_id": standard["id"], "start": 101, "count": 3}, headers=root
    )
    assert rooms.status_code == 201 and [r["number"] for r in rooms.json()] == ["101", "102", "103"]
    client.post(f"/api/admin/hotels/{hotel['code']}/rooms", json={"room_type_id": suite["id"], "numbers": ["S1"]}, headers=root)

    public = client.get("/api/hotels", params={"city": "paris"}).json()
    assert [(h["code"], h["room_count"], h["from_price"]) for h in public] == [("holiday-paris-louvre", 4, 150)]
    available = client.get("/api/availability", params={"check_in": day(5), "check_out": day(6), "hotel": hotel["code"]}).json()
    assert [(t["code"], t["available_rooms"]) for t in available["results"][0]["room_types"]] == [("standard", 3), ("suite", 1)]
    booked = book(client, hotel["code"], "standard", 5, 7)
    assert booked.status_code == 201 and booked.json()["total_price"] == 300 and booked.json()["room_number"] == "101"


def test_hotel_codes_are_unique_and_names_get_a_suffix(client, root):
    assert add_hotel(client, root).json()["code"] == "holiday-paris-louvre"
    assert add_hotel(client, root).json()["code"] == "holiday-paris-louvre-2"
    assert add_hotel(client, root, code="my-code").json()["code"] == "my-code"
    assert add_hotel(client, root, code="my-code").status_code == 409  # an explicit code must be free
    assert add_hotel(client, root, stars=9).status_code == 422
    assert add_hotel(client, root, name="   ").status_code == 422


def test_hotels_can_be_edited_and_deactivated(client, root):
    code = add_hotel(client, root).json()["code"]
    edited = client.patch(f"/api/admin/hotels/{code}", json={"city": "Lyon", "stars": 5}, headers=root).json()
    assert (edited["city"], edited["stars"], edited["name"]) == ("Lyon", 5, NEW_HOTEL["name"])
    t = add_type(client, root, code).json()
    client.post(f"/api/admin/hotels/{code}/rooms", json={"room_type_id": t["id"], "numbers": ["1"]}, headers=root)

    client.patch(f"/api/admin/hotels/{code}", json={"active": False}, headers=root)
    assert code not in [h["code"] for h in client.get("/api/hotels").json()]  # hidden from guests
    assert code in [h["code"] for h in client.get("/api/admin/hotels", headers=root).json()]  # still manageable
    assert client.get(f"/api/hotels/{code}").status_code == 404
    assert book(client, code, "standard").json()["error"]["code"] == "unknown_hotel"
    client.patch(f"/api/admin/hotels/{code}", json={"active": True}, headers=root)
    assert book(client, code, "standard").status_code == 201


def test_hotels_with_upcoming_bookings_cannot_be_deactivated_and_history_blocks_deleting(client, root):
    ref = book(client, "holiday-kandy", "suite").json()["reference"]
    blocked = client.patch("/api/admin/hotels/holiday-kandy", json={"active": False}, headers=root)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "has_upcoming_bookings"
    assert client.delete("/api/admin/hotels/holiday-kandy", headers=root).json()["error"]["code"] == "has_bookings"

    client.post(f"/api/admin/bookings/{ref}/cancel", headers=root)  # cancelled bookings are not "upcoming"...
    assert client.patch("/api/admin/hotels/holiday-kandy", json={"active": False}, headers=root).status_code == 200
    assert client.delete("/api/admin/hotels/holiday-kandy", headers=root).status_code == 409  # ...but are history

    fresh = add_hotel(client, root).json()["code"]  # no bookings ever: deleting is fine
    assert client.delete(f"/api/admin/hotels/{fresh}", headers=root).status_code == 204
    assert client.get(f"/api/admin/hotels/{fresh}/rooms", headers=root).status_code == 404


# ---------- room types ----------
def test_room_type_price_changes_apply_to_new_bookings_only(client, root):
    ref = book(client, "holiday-kandy", "deluxe", 5, 7).json()  # 2 nights x 140
    type_id = next(t["id"] for t in client.get("/api/hotels/holiday-kandy").json()["room_types"] if t["code"] == "deluxe")
    client.patch(f"/api/admin/room-types/{type_id}", json={"price_per_night": 200}, headers=root)
    assert client.get(f"/api/bookings/{ref['reference']}").json()["total_price"] == 280  # unchanged
    assert book(client, "holiday-kandy", "deluxe", 10, 12).json()["total_price"] == 400  # new price


def test_room_types_are_validated_and_guarded(client, root):
    code = add_hotel(client, root).json()["code"]
    first = add_type(client, root, code, "Deluxe King").json()
    assert first["code"] == "deluxe-king"
    assert add_type(client, root, code, "Deluxe King").status_code == 409
    assert add_type(client, root, code, "Free", price=0).status_code == 422
    assert add_type(client, root, "nowhere").status_code == 404
    client.post(f"/api/admin/hotels/{code}/rooms", json={"room_type_id": first["id"], "numbers": ["1"]}, headers=root)
    assert client.delete(f"/api/admin/room-types/{first['id']}", headers=root).json()["error"]["code"] == "has_rooms"
    empty = add_type(client, root, code, "Empty").json()
    assert client.delete(f"/api/admin/room-types/{empty['id']}", headers=root).status_code == 204

    ref = book(client, code, "deluxe-king", 5, 6)
    assert ref.status_code == 201
    blocked = client.patch(f"/api/admin/room-types/{first['id']}", json={"active": False}, headers=root)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "has_upcoming_bookings"


# ---------- rooms ----------
def test_rooms_numbers_are_validated(client, root):
    code = add_hotel(client, root).json()["code"]
    t = add_type(client, root, code).json()
    url = f"/api/admin/hotels/{code}/rooms"
    assert client.post(url, json={"room_type_id": t["id"], "numbers": ["101", "101"]}, headers=root).status_code == 422
    assert client.post(url, json={"room_type_id": t["id"], "numbers": ["bad number!"]}, headers=root).status_code == 422
    assert client.post(url, json={"room_type_id": t["id"]}, headers=root).status_code == 422
    assert client.post(url, json={"room_type_id": t["id"], "start": 1, "count": 500}, headers=root).status_code == 422
    assert client.post(url, json={"room_type_id": 99999, "numbers": ["1"]}, headers=root).status_code == 404
    assert client.post(url, json={"room_type_id": t["id"], "numbers": ["1", "2"]}, headers=root).status_code == 201
    dup = client.post(url, json={"room_type_id": t["id"], "numbers": ["2", "3"]}, headers=root)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "room_exists"
    assert [r["number"] for r in client.get(url, headers=root).json()] == ["1", "2"]  # the failed batch added nothing

    # a type from a different hotel cannot be used
    other_type = next(t2["id"] for t2 in client.get("/api/hotels/holiday-kandy").json()["room_types"])
    assert client.post(url, json={"room_type_id": other_type, "numbers": ["9"]}, headers=root).status_code == 404


def test_rooms_can_be_deactivated_moved_and_deleted_safely(client, root):
    code = add_hotel(client, root).json()["code"]
    std, deluxe = add_type(client, root, code, "Standard").json(), add_type(client, root, code, "Deluxe", 300).json()
    rooms = client.post(f"/api/admin/hotels/{code}/rooms", json={"room_type_id": std["id"], "numbers": ["1", "2"]}, headers=root).json()
    r1, r2 = rooms[0]["id"], rooms[1]["id"]

    assert client.patch(f"/api/admin/rooms/{r2}", json={"room_type_id": deluxe["id"]}, headers=root).json()["room_type_code"] == "deluxe"
    hidden = client.patch(f"/api/admin/rooms/{r1}", json={"active": False}, headers=root).json()
    assert hidden["active"] is False
    result = client.get("/api/availability", params={"check_in": day(5), "check_out": day(6), "hotel": code}).json()
    assert {t["code"]: t["available_rooms"] for t in result["results"][0]["room_types"]} == {"standard": 0, "deluxe": 1}

    client.patch(f"/api/admin/rooms/{r1}", json={"active": True}, headers=root)
    assert book(client, code, "standard", 5, 6).status_code == 201  # takes room 1
    blocked = client.patch(f"/api/admin/rooms/{r1}", json={"active": False}, headers=root)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "has_upcoming_bookings"
    assert client.delete(f"/api/admin/rooms/{r1}", headers=root).json()["error"]["code"] == "has_bookings"
    assert client.delete(f"/api/admin/rooms/{r2}", headers=root).status_code == 204


def test_staff_see_and_cancel_any_booking(client, staff):
    ref = book(client, "holiday-dubai", "suite", email="a@example.com").json()["reference"]
    book(client, "holiday-london", "suite", email="b@example.com")
    assert len(client.get("/api/admin/bookings", headers=staff).json()) == 2
    only_dubai = client.get("/api/admin/bookings", params={"hotel": "holiday-dubai"}, headers=staff).json()
    assert [b["reference"] for b in only_dubai] == [ref]
    assert client.post(f"/api/admin/bookings/{ref}/cancel", headers=staff).json()["status"] == "cancelled"


# ---------- users ----------
def test_superadmin_manages_users(client, root):
    created = client.post(
        "/api/admin/users",
        json={"email": "New.Admin@Example.com", "name": "  New   Admin ", "password": "good-password-1", "role": "admin"},
        headers=root,
    )
    assert created.status_code == 201
    user = created.json()
    assert (user["email"], user["name"], user["role"], user["active"]) == ("new.admin@example.com", "New Admin", "admin", True)
    assert "password" not in created.text
    assert client.post("/api/admin/users", json={"email": "new.admin@example.com", "name": "x", "password": "good-password-1"}, headers=root).status_code == 409
    assert client.post("/api/admin/users", json={"email": "w@example.com", "name": "w", "password": "short"}, headers=root).json()["error"]["code"] == "weak_password"
    assert client.post("/api/admin/users", json={"email": "r@example.com", "name": "r", "password": "good-password-1", "role": "owner"}, headers=root).status_code == 422
    assert len(client.get("/api/admin/users", headers=root).json()) == 2

    promoted = client.patch(f"/api/admin/users/{user['id']}", json={"role": "superadmin", "name": "Boss"}, headers=root).json()
    assert (promoted["role"], promoted["name"]) == ("superadmin", "Boss")


def test_deactivated_users_are_signed_out_and_cannot_log_in(client, root, staff):
    staff_id = next(u["id"] for u in client.get("/api/admin/users", headers=root).json() if u["email"] == "staff@example.com")
    assert client.get("/api/auth/me", headers=staff).status_code == 200
    assert client.patch(f"/api/admin/users/{staff_id}", json={"active": False}, headers=root).json()["active"] is False
    assert client.get("/api/auth/me", headers=staff).status_code == 401  # signed out immediately
    assert client.post("/api/auth/login", json={"email": "staff@example.com", "password": "staff-password-1"}).status_code == 401
    client.patch(f"/api/admin/users/{staff_id}", json={"active": True}, headers=root)
    login(client, "staff@example.com", "staff-password-1")


def test_the_last_superadmin_and_your_own_account_are_protected(client, root):
    me = client.get("/api/auth/me", headers=root).json()
    own = client.patch(f"/api/admin/users/{me['id']}", json={"active": False}, headers=root)
    assert own.status_code == 409 and own.json()["error"]["code"] == "self_change"
    assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "admin"}, headers=root).status_code == 409
    assert client.patch(f"/api/admin/users/{me['id']}", json={"name": "Renamed"}, headers=root).status_code == 200

    # a second superadmin can demote the first, but then nobody may remove the last one
    second = client.post("/api/admin/users", json={"email": "s2@example.com", "name": "S2", "password": "second-pass-1", "role": "superadmin"}, headers=root).json()
    s2 = login(client, "s2@example.com", "second-pass-1")
    assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "admin"}, headers=s2).status_code == 200
    last = client.patch(f"/api/admin/users/{second['id']}", json={"active": False}, headers=s2)
    assert last.status_code == 409  # that is your own account
    assert client.patch("/api/admin/users/999", json={"active": False}, headers=s2).status_code == 404


def test_resetting_or_changing_a_password_signs_everyone_out(client, root, staff):
    staff_id = next(u["id"] for u in client.get("/api/admin/users", headers=root).json() if u["email"] == "staff@example.com")
    assert client.post(f"/api/admin/users/{staff_id}/reset-password", json={"password": "reset-pass-123"}, headers=root).status_code == 204
    assert client.get("/api/auth/me", headers=staff).status_code == 401
    assert client.post("/api/auth/login", json={"email": "staff@example.com", "password": "staff-password-1"}).status_code == 401
    mine = login(client, "staff@example.com", "reset-pass-123")

    wrong = client.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "brand-new-pass-1"}, headers=mine)
    assert wrong.status_code == 401
    assert client.post("/api/auth/change-password", json={"current_password": "reset-pass-123", "new_password": "short"}, headers=mine).status_code == 422
    assert client.post("/api/auth/change-password", json={"current_password": "reset-pass-123", "new_password": "brand-new-pass-1"}, headers=mine).status_code == 204
    assert client.get("/api/auth/me", headers=mine).status_code == 401
    login(client, "staff@example.com", "brand-new-pass-1")


@pytest.mark.parametrize("password", ["", "a" * 129])
def test_password_length_limits(client, root, password):
    resp = client.post("/api/admin/users", json={"email": "p@example.com", "name": "P", "password": password}, headers=root)
    assert resp.status_code == 422


def test_staff_filter_bookings_by_today(client, staff):
    from datetime import date

    today = date.today().isoformat()
    later = book(client, "holiday-dubai", "suite", email="a@example.com", start=10, end=12).json()["reference"]
    # a stay is only in the past/today for rows created directly, so use the filters on what the API can book
    params = {"on": today, "tz_offset": 0}
    booked = client.get("/api/admin/bookings", params={**params, "when": "booked"}, headers=staff).json()
    assert [b["reference"] for b in booked] == [later]  # made just now (UTC today may differ from local only near midnight)
    assert client.get("/api/admin/bookings", params={**params, "when": "check_in"}, headers=staff).json() == []
    assert client.get("/api/admin/bookings", params={**params, "when": "staying"}, headers=staff).json() == []
    on_check_in = {"on": day(10), "tz_offset": 0}
    assert len(client.get("/api/admin/bookings", params={**on_check_in, "when": "check_in"}, headers=staff).json()) == 1
    assert len(client.get("/api/admin/bookings", params={**on_check_in, "when": "staying"}, headers=staff).json()) == 1
    assert len(client.get("/api/admin/bookings", params={"on": day(12), "when": "check_out"}, headers=staff).json()) == 1
    assert client.get("/api/admin/bookings", params={"on": day(12), "when": "staying"}, headers=staff).json() == []
    assert client.get("/api/admin/bookings", params={"when": "nonsense", "on": today}, headers=staff).status_code == 422
