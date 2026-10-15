"""Staff login, gym / class type / session administration and user management."""

import pytest

from app import accounts, db
from app.seed import seed_superadmin

from .conftest import SUPER_EMAIL, SUPER_PASSWORD, future, login
from .test_api import book, first_session

NEW_GYM = {
    "name": "FitZone Paris", "city": "Paris", "country": "France",
    "address": "3 Rue de Rivoli", "description": "Steps from the Louvre.",
}


def add_gym(client, headers, **overrides):
    return client.post("/api/admin/gyms", json={**NEW_GYM, **overrides}, headers=headers)


def add_type(client, headers, gym, name="Pilates", price=12, duration=50, **extra):
    return client.post(
        f"/api/admin/gyms/{gym}/class-types",
        json={"name": name, "price": price, "duration_min": duration, **extra},
        headers=headers,
    )


def add_session(client, headers, gym, type_id, days=3, hour=9, capacity=2, **extra):
    return client.post(
        f"/api/admin/gyms/{gym}/sessions",
        json={"class_type_id": type_id, "starts_at": future(days, hour), "capacity": capacity, **extra},
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
    monkeypatch.delenv("GB_SUPERADMIN_EMAIL")
    monkeypatch.delenv("GB_SUPERADMIN_PASSWORD")
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
    assert "gb_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
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
    for method, path in (("get", "/api/admin/gyms"), ("get", "/api/admin/bookings"), ("get", "/api/admin/users")):
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/api/admin/gyms", headers=staff).status_code == 200  # admins manage gyms...
    for method, path, body in (
        ("get", "/api/admin/users", None),
        ("post", "/api/admin/users", {"email": "x@example.com", "name": "X", "password": "password-123"}),
        ("patch", "/api/admin/users/1", {"active": False}),
        ("post", "/api/admin/users/1/reset-password", {"password": "password-123"}),
    ):
        resp = getattr(client, method)(path, headers=staff, **({"json": body} if body else {}))
        assert resp.status_code == 403, (path, resp.text)  # ...but not users
    assert client.get("/api/admin/users", headers=root).status_code == 200



# ---------- gyms ----------
def test_admin_adds_a_gym_with_class_types_and_sessions_that_members_can_then_book(client, root):
    gym = add_gym(client, root)
    assert gym.status_code == 201 and gym.json()["code"] == "fitzone-paris"
    assert client.get("/api/gyms/fitzone-paris").json()["class_types"] == []
    ctype = add_type(client, root, "fitzone-paris", "Aqua Fit", 15, 45).json()
    assert ctype["code"] == "aqua-fit"
    session = add_session(client, root, "fitzone-paris", ctype["id"], capacity=1, trainer="Lea")
    assert session.status_code == 201 and session.json()["booked"] == 0
    listed = client.get("/api/sessions", params={"gym": "fitzone-paris", "date_to": future(10, 0)[:10]}).json()["sessions"]
    assert [(s["class"]["code"], s["spots_left"], s["trainer"]) for s in listed] == [("aqua-fit", 1, "Lea")]
    assert book(client, listed[0]["session_id"]).status_code == 201
    assert book(client, listed[0]["session_id"], email="b@example.com").json()["error"]["code"] == "class_full"


def test_gym_codes_are_unique_and_names_get_a_suffix(client, root):
    assert add_gym(client, root).json()["code"] == "fitzone-paris"
    assert add_gym(client, root).json()["code"] == "fitzone-paris-2"
    taken = add_gym(client, root, code="fitzone-paris")
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "code_taken"


def test_gyms_can_be_edited_and_deactivated(client, root):
    add_gym(client, root)
    edited = client.patch("/api/admin/gyms/fitzone-paris", json={"city": "Lyon", "description": "New"}, headers=root).json()
    assert (edited["city"], edited["description"]) == ("Lyon", "New")
    off = client.patch("/api/admin/gyms/fitzone-paris", json={"active": False}, headers=root).json()
    assert off["active"] is False
    assert client.get("/api/gyms/fitzone-paris").status_code == 404
    assert "fitzone-paris" not in [g["code"] for g in client.get("/api/gyms").json()]
    assert "fitzone-paris" in [g["code"] for g in client.get("/api/admin/gyms", headers=root).json()]
    assert client.delete("/api/admin/gyms/fitzone-paris", headers=root).status_code == 204
    assert client.delete("/api/admin/gyms/fitzone-paris", headers=root).status_code == 404


def test_gyms_with_upcoming_bookings_cannot_be_deactivated_and_history_blocks_deleting(client, root):
    sid = first_session(client)
    ref = book(client, sid).json()["reference"]
    blocked = client.patch("/api/admin/gyms/fitzone-anna-nagar", json={"active": False}, headers=root)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "has_upcoming_bookings"
    client.post(f"/api/bookings/{ref}/cancel")
    assert client.patch("/api/admin/gyms/fitzone-anna-nagar", json={"active": False}, headers=root).status_code == 200
    gone = client.delete("/api/admin/gyms/fitzone-anna-nagar", headers=root)
    assert gone.status_code == 409 and gone.json()["error"]["code"] == "has_bookings"


# ---------- class types ----------
def test_class_type_price_changes_apply_to_new_bookings_only(client, root):
    sid = first_session(client)
    old = book(client, sid).json()
    sessions = client.get("/api/admin/gyms/fitzone-anna-nagar/sessions", headers=root).json()
    type_id = next(s for s in sessions if s["id"] == sid)["class_type_id"]
    assert client.patch(f"/api/admin/class-types/{type_id}", json={"price": 99}, headers=root).json()["price"] == 99
    assert client.get(f"/api/bookings/{old['reference']}").json()["price"] == old["price"]
    assert book(client, sid, email="b@example.com").json()["price"] == 99


def test_class_types_are_validated_and_guarded(client, root):
    assert add_gym(client, root).status_code == 201
    assert add_type(client, root, "fitzone-paris", price=-1).status_code == 422
    assert add_type(client, root, "fitzone-paris", duration=1).status_code == 422
    assert add_type(client, root, "no-such-gym").status_code == 404
    first = add_type(client, root, "fitzone-paris").json()
    dup = add_type(client, root, "fitzone-paris")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "code_taken"
    add_session(client, root, "fitzone-paris", first["id"])
    blocked = client.delete(f"/api/admin/class-types/{first['id']}", headers=root)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "has_sessions"
    assert client.patch(f"/api/admin/class-types/{first['id']}", json={"active": False}, headers=root).status_code == 200
    assert client.get("/api/gyms/fitzone-paris").json()["class_types"] == []  # inactive types are hidden from members


# ---------- class sessions ----------
def test_sessions_are_validated(client, root):
    add_gym(client, root)
    add_gym(client, root, name="Other Gym")
    ctype = add_type(client, root, "fitzone-paris").json()
    assert add_session(client, root, "fitzone-paris", ctype["id"], capacity=0).status_code == 422
    assert add_session(client, root, "fitzone-paris", ctype["id"], days=-1).json()["error"]["code"] == "invalid_time"
    wrong_gym = add_session(client, root, "other-gym", ctype["id"])
    assert wrong_gym.status_code == 404 and wrong_gym.json()["error"]["code"] == "unknown_class_type"


def test_sessions_with_bookings_are_protected(client, root):
    sid = first_session(client)
    ref = book(client, sid).json()["reference"]
    url = f"/api/admin/sessions/{sid}"
    assert client.patch(url, json={"active": False}, headers=root).json()["error"]["code"] == "has_upcoming_bookings"
    assert client.patch(url, json={"starts_at": future(5, 8)}, headers=root).json()["error"]["code"] == "has_upcoming_bookings"
    assert client.delete(url, headers=root).json()["error"]["code"] == "has_bookings"
    assert client.patch(url, json={"capacity": 0}, headers=root).status_code == 422
    assert client.patch(url, json={"capacity": 30}, headers=root).json()["capacity"] == 30
    client.post(f"/api/bookings/{ref}/cancel")
    assert client.patch(url, json={"active": False}, headers=root).json()["active"] is False
    assert sid not in [s["session_id"] for s in client.get("/api/sessions", params={"gym": "fitzone-anna-nagar"}).json()["sessions"]]
    assert client.delete(url, headers=root).status_code == 409  # cancelled bookings are still history


def test_capacity_cannot_drop_below_the_booked_spots(client, root):
    sid = first_session(client)
    for i in range(3):
        book(client, sid, email=f"m{i}@example.com")
    low = client.patch(f"/api/admin/sessions/{sid}", json={"capacity": 2}, headers=root)
    assert low.status_code == 409 and low.json()["error"]["code"] == "capacity_too_low"
    assert client.patch(f"/api/admin/sessions/{sid}", json={"capacity": 3}, headers=root).status_code == 200


def test_unbooked_sessions_can_be_rescheduled_and_deleted(client, root):
    add_gym(client, root)
    ctype = add_type(client, root, "fitzone-paris").json()
    sid = add_session(client, root, "fitzone-paris", ctype["id"]).json()["id"]
    moved = client.patch(f"/api/admin/sessions/{sid}", json={"starts_at": future(4, 10), "trainer": "Lea"}, headers=root).json()
    assert moved["trainer"] == "Lea" and moved["starts_at"].startswith(future(4, 10)[:10])
    assert client.delete(f"/api/admin/sessions/{sid}", headers=root).status_code == 204


def test_staff_see_and_cancel_any_booking(client, staff):
    sessions = client.get("/api/sessions").json()["sessions"]
    first = sessions[0]
    other = next(s for s in sessions if s["gym"]["code"] != first["gym"]["code"])
    ref = book(client, first["session_id"], email="a@example.com").json()["reference"]
    book(client, other["session_id"], email="b@example.com")
    assert len(client.get("/api/admin/bookings", headers=staff).json()) == 2
    only_first = client.get("/api/admin/bookings", params={"gym": first["gym"]["code"]}, headers=staff).json()
    assert [b["reference"] for b in only_first] == [ref]
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
