from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import accounts, db, migrate
from app.main import app
from app.seed import seed_superadmin

KEY = "test-backend-key"
SUPER_EMAIL = "root@example.com"
SUPER_PASSWORD = "root-password-1"


def day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client holding the API key, on a fresh migrated + seeded SQLite database (the same migrations as production)."""
    monkeypatch.setenv("HB_BACKEND_API_KEY", KEY)
    monkeypatch.setenv("HB_SUPERADMIN_EMAIL", SUPER_EMAIL)
    monkeypatch.setenv("HB_SUPERADMIN_PASSWORD", SUPER_PASSWORD)
    monkeypatch.setattr(db, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db.reset_engine()
    migrate.upgrade()
    seed_superadmin()
    accounts.login_limiter.reset()
    with TestClient(app, headers={"X-API-Key": KEY}) as c:
        yield c
    db.reset_engine()


def login(client, email=SUPER_EMAIL, password=SUPER_PASSWORD) -> dict:
    """Logs in and returns Authorization headers (the Bearer form of the session)."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    client.cookies.clear()  # the Bearer form only: a leftover cookie would authenticate "anonymous" calls too
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def root(client) -> dict:
    return login(client)


@pytest.fixture
def staff(client, root) -> dict:
    """A regular admin (not a superadmin)."""
    client.post(
        "/api/admin/users",
        json={"email": "staff@example.com", "name": "Staff", "password": "staff-password-1", "role": "admin"},
        headers=root,
    )
    return login(client, "staff@example.com", "staff-password-1")
