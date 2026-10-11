import pytest

from app.auth.ratelimit import login_limiter
from app.auth.security import hash_password
from app.core.config import get_settings
from app.models import DomainProfileRow, RefreshToken, Tenant, User

PASSWORD = "correct-horse-1"
SUPER_EMAIL = "root@example.com"


@pytest.fixture(autouse=True)
def _reset_limiter():
    login_limiter.reset()


@pytest.fixture
def superadmin(session_factory):
    with session_factory() as session:
        session.add(
            User(
                email=SUPER_EMAIL,
                name="Root",
                password_hash=hash_password(PASSWORD),
                role="superadmin",
                status="active",
            )
        )
        session.commit()


def register(client, email="admin@example.com", name="Asha", organization="Acme Hotel"):
    return client.post(
        "/api/auth/register", json={"name": name, "email": email, "organizationName": organization}
    )


def emailed_password(outbox, to="admin@example.com") -> str:
    body = next(b for t, _, b in reversed(outbox.sent) if t == to)
    return next(line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("Password: "))


def login(client, email="admin@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"identifier": email, "password": password})


def bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def pending_id(client, headers):
    return client.get("/api/admin/onboarding-requests", headers=headers).json()[0]["id"]


def test_register_then_blocked_until_approved(client, superadmin, outbox, session_factory):
    assert register(client).status_code == 202
    # No password exists until approval, so nothing can log in yet (and the failure leaks nothing).
    assert login(client).status_code == 401

    sa = login(client, SUPER_EMAIL)
    assert sa.status_code == 200
    headers = bearer(sa)
    requests = client.get("/api/admin/onboarding-requests", headers=headers).json()
    assert [r["email"] for r in requests] == ["admin@example.com"]

    approved = client.post(f"/api/admin/onboarding-requests/{requests[0]['id']}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "active"

    assert [t for t, _, _ in outbox.sent] == ["admin@example.com"]
    password = emailed_password(outbox)
    assert login(client, password=PASSWORD).status_code == 401  # the signup never had a usable password

    ok = login(client, password=password)
    assert ok.status_code == 200
    assert ok.json()["user"]["role"] == "admin"
    tenant_id = ok.json()["user"]["tenantId"]
    assert tenant_id != get_settings().default_tenant_id  # own organization, not the shared demo one
    with session_factory() as session:
        tenant = session.get(Tenant, tenant_id)
        assert tenant.name == "Acme Hotel"
        profile = session.query(DomainProfileRow).filter_by(tenant_id=tenant_id).one()
        assert profile.config["identity"]["organizationName"] == "Acme Hotel"
    me = client.get("/api/auth/me", headers=bearer(ok))
    assert me.json()["email"] == "admin@example.com"


def test_reject_path(client, superadmin, outbox):
    register(client)
    headers = bearer(login(client, SUPER_EMAIL))
    rid = pending_id(client, headers)
    rejected = client.post(
        f"/api/admin/onboarding-requests/{rid}/reject", headers=headers, json={"reason": "Not a customer"}
    )
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejectionReason"] == "Not a customer"
    assert login(client).status_code == 401
    assert outbox.sent == []  # rejected applicants get no credentials
    # already reviewed
    assert client.post(f"/api/admin/onboarding-requests/{rid}/approve", headers=headers).status_code == 409


def test_duplicate_email_is_409_and_case_insensitive(client):
    assert register(client).status_code == 202
    assert register(client, email="ADMIN@example.com").status_code == 409


def test_login_by_name_is_case_and_space_insensitive(client, superadmin):
    assert login(client, "  root ").status_code == 200  # seeded name is "Root"
    assert login(client, "root").status_code == 200
    assert login(client, "ROOT").json()["user"]["email"] == SUPER_EMAIL


def test_login_by_name_before_approval_is_rejected(client):
    register(client, name="Asha Rao")
    assert login(client, "asha  rao").status_code == 401


def test_duplicate_name_is_409_case_insensitive(client):
    assert register(client, name="Asha Rao").status_code == 202
    dup = register(client, email="other@example.com", name="asha   RAO")
    assert dup.status_code == 409
    assert dup.json()["error"]["message"] == "That name is already taken"


def test_name_cannot_contain_at_sign(client):
    assert register(client, name="a@b.com").status_code == 422


def test_register_validation(client):
    assert register(client, organization="   ").status_code == 422
    assert client.post("/api/auth/register", json={"name": "A", "email": "a@example.com"}).status_code == 422
    assert register(client, email="not-an-email").status_code == 422


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client)
    wrong = login(client, password="nope-nope-nope")
    unknown = login(client, email="ghost@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_rate_limited_after_repeated_failures(client):
    register(client)
    for _ in range(5):
        assert login(client, password="bad-password").status_code == 401
    assert login(client, password="bad-password").status_code == 429
    assert login(client).status_code == 429  # even the right password is throttled for now


def test_admin_routes_require_superadmin(client, superadmin, session_factory, outbox):
    assert client.get("/api/admin/onboarding-requests").status_code == 401
    register(client)
    sa_headers = bearer(login(client, SUPER_EMAIL))
    client.post(
        f"/api/admin/onboarding-requests/{pending_id(client, sa_headers)}/approve", headers=sa_headers
    )
    admin_headers = bearer(login(client, password=emailed_password(outbox)))
    forbidden = client.get("/api/admin/onboarding-requests", headers=admin_headers)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "forbidden"


def test_bad_token_rejected(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_refresh_rotates_and_replay_revokes_family(client, superadmin):
    first = login(client, SUPER_EMAIL)
    old_cookie = client.cookies.get("refresh_token")
    assert old_cookie

    rotated = client.post("/api/auth/refresh")
    assert rotated.status_code == 200 and rotated.json()["accessToken"]
    new_cookie = client.cookies.get("refresh_token")
    assert new_cookie and new_cookie != old_cookie

    # Replaying the already-rotated token fails and burns the whole family, including the new one.
    client.cookies.clear()
    client.cookies.set("refresh_token", old_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    client.cookies.clear()
    client.cookies.set("refresh_token", new_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    assert first.status_code == 200


def test_refresh_without_cookie_is_401(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token(client, superadmin, session_factory):
    login(client, SUPER_EMAIL)
    cookie = client.cookies.get("refresh_token")
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("refresh_token", cookie, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    with session_factory() as session:
        assert all(t.revoked_at for t in session.query(RefreshToken).all())


def test_seed_creates_superadmin_once(session_factory, monkeypatch):
    from app.database.seed import seed

    monkeypatch.setenv("SUPERADMIN_EMAIL", "Boss@Example.com")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "seeded-password-1")
    get_settings.cache_clear()
    try:
        seed(session_factory)
        seed(session_factory)
        with session_factory() as session:
            users = session.query(User).filter(User.role == "superadmin").all()
            assert [u.email for u in users] == ["boss@example.com"]
    finally:
        monkeypatch.delenv("SUPERADMIN_EMAIL")
        monkeypatch.delenv("SUPERADMIN_PASSWORD")
        get_settings.cache_clear()


def test_approval_is_rolled_back_when_the_email_cannot_be_sent(client, superadmin, outbox, session_factory):
    register(client)
    headers = bearer(login(client, SUPER_EMAIL))
    rid = pending_id(client, headers)
    outbox.fail = True
    failed = client.post(f"/api/admin/onboarding-requests/{rid}/approve", headers=headers)
    assert failed.status_code >= 400
    with session_factory() as session:
        assert session.query(Tenant).count() == 1  # only the demo tenant: nothing half-created
        assert session.get(User, rid).status == "pending"

    outbox.fail = False  # retry succeeds
    assert client.post(f"/api/admin/onboarding-requests/{rid}/approve", headers=headers).status_code == 200
    assert login(client, password=emailed_password(outbox)).status_code == 200


def test_credentials_email_contents(client, superadmin, outbox):
    register(client, organization="Acme Hotel")
    headers = bearer(login(client, SUPER_EMAIL))
    client.post(f"/api/admin/onboarding-requests/{pending_id(client, headers)}/approve", headers=headers)
    (to, subject, body) = outbox.sent[0]
    assert to == "admin@example.com" and "Acme Hotel" in subject
    assert "http://localhost:5173/login" in body and "Email: admin@example.com" in body
