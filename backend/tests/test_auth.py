import pytest

from app.auth.ratelimit import login_limiter
from app.auth.security import hash_password
from app.core.config import get_settings
from app.auth.security import utcnow
from app.models import RefreshToken, User

from .conftest import otp_from

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
                email_verified_at=utcnow(),
            )
        )
        session.commit()


def register(client, email="customer@example.com", name="Asha", password=PASSWORD):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": password})


def login(client, email="customer@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"identifier": email, "password": password})


def bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def test_signup_requires_the_emailed_code_before_any_session(client, outbox):
    created = register(client)
    assert created.status_code == 201
    assert created.json()["role"] == "user" and created.json()["tenantId"] is None
    assert outbox.sent[-1][0] == "customer@example.com"

    # Even with the right password, an unverified account gets no session: a code is emailed instead.
    first = login(client)
    assert first.status_code == 200
    assert first.json() == {"accessToken": None, "user": None, "otpRequired": True, "email": "customer@example.com"}
    assert "refresh_token" not in client.cookies

    bad = client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": otp_from(outbox, "customer@example.com")})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "user"
    assert client.get("/api/auth/me", headers=bearer(ok)).json()["email"] == "customer@example.com"

    # Verified once: later logins go straight in, with no code.
    again = login(client)
    assert again.json()["otpRequired"] is False and again.json()["accessToken"]


def test_otp_cannot_be_reused_or_brute_forced(client, outbox):
    register(client)
    code = otp_from(outbox, "customer@example.com")
    assert client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": code}).status_code == 200
    assert client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": code}).status_code == 401

    register(client, email="b@example.com")
    good = otp_from(outbox, "b@example.com")
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/auth/verify-otp", json={"email": "b@example.com", "code": wrong}).status_code == 401
    # After too many wrong guesses even the right code is refused (it is throttled / burnt).
    assert client.post("/api/auth/verify-otp", json={"email": "b@example.com", "code": good}).status_code in (401, 429)


def test_expired_otp_is_rejected_and_resend_issues_a_new_one(client, outbox, session_factory):
    from datetime import timedelta

    from app.models import EmailOtp

    register(client)
    with session_factory() as session:
        for otp in session.query(EmailOtp).all():
            otp.expires_at = utcnow() - timedelta(minutes=1)
            otp.created_at = utcnow() - timedelta(minutes=5)
        session.commit()
    old = otp_from(outbox, "customer@example.com")
    assert client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": old}).status_code == 401

    assert client.post("/api/auth/resend-otp", json={"email": "customer@example.com"}).status_code == 202
    fresh = otp_from(outbox, "customer@example.com")
    assert client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": fresh}).status_code == 200
    # Unknown addresses look the same as known ones.
    assert client.post("/api/auth/resend-otp", json={"email": "ghost@example.com"}).status_code == 202


def test_signup_fails_cleanly_when_the_code_cannot_be_emailed(client, outbox, session_factory):
    outbox.fail = True
    assert register(client).status_code >= 400
    with session_factory() as session:
        assert session.query(User).filter_by(email="customer@example.com").count() == 0


def test_duplicate_email_is_409_and_case_insensitive(client):
    assert register(client).status_code == 201
    assert register(client, email="CUSTOMER@example.com").status_code == 409


def test_customers_may_share_a_name(client):
    assert register(client, name="Asha Rao").status_code == 201
    assert register(client, email="other@example.com", name="asha   RAO").status_code == 201


def test_login_is_by_email_only(client):
    register(client, name="Asha Rao")
    assert login(client, "Asha Rao").status_code == 401
    assert login(client, "  CUSTOMER@example.com ").json()["otpRequired"] is True


def test_register_validation(client):
    assert register(client, name="   ").status_code == 422
    assert register(client, password="short").status_code == 422
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


def test_superadmin_routes_require_superadmin(client, superadmin, outbox):
    assert client.get("/api/superadmin/businesses").status_code == 401
    register(client)
    verified = client.post("/api/auth/verify-otp", json={"email": "customer@example.com", "code": otp_from(outbox, "customer@example.com")})
    forbidden = client.get("/api/superadmin/businesses", headers=bearer(verified))
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "forbidden"
    assert client.get("/api/superadmin/businesses", headers=bearer(login(client, SUPER_EMAIL))).status_code == 200


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
