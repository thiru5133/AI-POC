import pytest

from app.auth.ratelimit import login_limiter
from app.auth.security import hash_password
from app.core.config import get_settings
from app.auth.security import utcnow
from app.models import User

PASSWORD = "correct-horse-1"
SUPER_EMAIL = "root@example.com"


@pytest.fixture(autouse=True)
def _reset_limiter():
    login_limiter.reset()


@pytest.fixture
def seeded(session_factory):
    """Superadmin (active) + admins in each status."""
    tenant = get_settings().default_tenant_id
    rows = [
        ("Root", SUPER_EMAIL, "superadmin", "active", None),
        ("Asha Rao", "asha@example.com", "admin", "active", tenant),
        ("Bala Kumar", "bala@example.com", "admin", "active", tenant),
        ("Chitra Devi", "chitra@example.com", "admin", "pending", None),
        ("Dev Patel", "dev@example.com", "admin", "rejected", None),
        ("100%_Sure", "sure@example.com", "admin", "disabled", None),
    ]
    with session_factory() as session:
        for name, email, role, status, tid in rows:
            session.add(
                User(
                    name=name,
                    email=email,
                    password_hash=hash_password(PASSWORD),
                    role=role,
                    status=status,
                    tenant_id=tid,
                    email_verified_at=utcnow(),
                    rejection_reason="Not a customer" if status == "rejected" else None,
                )
            )
        session.commit()


@pytest.fixture
def headers(client, seeded):
    token = client.post("/api/auth/login", json={"identifier": SUPER_EMAIL, "password": PASSWORD}).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def names(resp):
    return sorted(u["name"] for u in resp.json()["items"])


def test_lists_all_users_with_status_counts(client, headers):
    body = client.get("/api/superadmin/users", headers=headers).json()
    assert body["total"] == 6
    assert body["counts"] == {"active": 3, "pending": 1, "rejected": 1, "disabled": 1}


def test_filter_by_status(client, headers):
    active = client.get("/api/superadmin/users?status=active", headers=headers)
    assert names(active) == ["Asha Rao", "Bala Kumar", "Root"]
    assert active.json()["total"] == 3
    assert names(client.get("/api/superadmin/users?status=pending", headers=headers)) == ["Chitra Devi"]


def test_filter_by_role_and_counts_follow_role(client, headers):
    resp = client.get("/api/superadmin/users?role=admin", headers=headers)
    assert "Root" not in names(resp)
    assert resp.json()["counts"]["active"] == 2


def test_search_name_or_email_case_insensitive(client, headers):
    assert names(client.get("/api/superadmin/users?q=ASHA", headers=headers)) == ["Asha Rao"]
    assert names(client.get("/api/superadmin/users?q=bala@", headers=headers)) == ["Bala Kumar"]
    combined = client.get("/api/superadmin/users?q=example.com&status=active&role=admin", headers=headers)
    assert names(combined) == ["Asha Rao", "Bala Kumar"]


def test_search_treats_wildcards_literally(client, headers):
    assert names(client.get("/api/superadmin/users?q=%25", headers=headers)) == ["100%_Sure"]  # "%"
    assert names(client.get("/api/superadmin/users?q=_", headers=headers)) == ["100%_Sure"]


def test_pagination(client, headers):
    page1 = client.get("/api/superadmin/users?limit=4&offset=0", headers=headers).json()
    page2 = client.get("/api/superadmin/users?limit=4&offset=4", headers=headers).json()
    assert page1["total"] == page2["total"] == 6
    assert len(page1["items"]) == 4 and len(page2["items"]) == 2
    assert not {u["id"] for u in page1["items"]} & {u["id"] for u in page2["items"]}
    assert client.get("/api/superadmin/users?limit=0", headers=headers).status_code == 422


def test_user_detail_includes_tenant(client, headers):
    asha = next(u for u in client.get("/api/superadmin/users?q=asha", headers=headers).json()["items"])
    detail = client.get(f"/api/superadmin/users/{asha['id']}", headers=headers).json()
    assert detail["email"] == "asha@example.com" and detail["tenantName"] == "Demo Tenant"
    assert "passwordHash" not in detail and "password_hash" not in detail


def test_unknown_user_is_404(client, headers):
    assert client.get("/api/superadmin/users/nope", headers=headers).status_code == 404


def test_users_endpoints_are_superadmin_only(client, seeded):
    assert client.get("/api/superadmin/users").status_code == 401
    token = client.post("/api/auth/login", json={"identifier": "asha@example.com", "password": PASSWORD}).json()[
        "accessToken"
    ]
    admin = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/superadmin/users", headers=admin).status_code == 403
    assert client.get("/api/superadmin/users/anything", headers=admin).status_code == 403


def _user_id(client, headers, q):
    return client.get(f"/api/superadmin/users?q={q}", headers=headers).json()["items"][0]["id"]


def test_superadmin_edits_user_and_renames_business(client, headers):
    uid = _user_id(client, headers, "asha")
    resp = client.patch(
        f"/api/superadmin/users/{uid}",
        json={"name": "  Asha  R ", "email": "Asha.New@Example.com", "businessName": "Softsuave"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Asha R" and body["email"] == "asha.new@example.com" and body["tenantName"] == "Softsuave"
    assert client.get(f"/api/superadmin/users/{uid}", headers=headers).json()["tenantName"] == "Softsuave"


def test_edit_rejects_duplicate_email_and_unknown_user(client, headers):
    uid = _user_id(client, headers, "asha")
    assert client.patch(f"/api/superadmin/users/{uid}", json={"email": "bala@example.com"}, headers=headers).status_code == 409
    assert client.patch(f"/api/superadmin/users/{uid}", json={"name": "  "}, headers=headers).status_code == 422
    assert client.patch("/api/superadmin/users/nope", json={"name": "X"}, headers=headers).status_code == 404


def test_edit_is_superadmin_only(client, seeded):
    token = client.post("/api/auth/login", json={"identifier": "asha@example.com", "password": PASSWORD}).json()["accessToken"]
    assert client.patch("/api/superadmin/users/x", json={"name": "Y"}, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_renaming_a_business_updates_the_greeting(client, headers, session_factory):
    from sqlalchemy import select

    from app.models import DomainProfileRow

    uid = _user_id(client, headers, "asha")
    with session_factory() as session:
        tenant_id = get_settings().default_tenant_id
        row = session.scalars(select(DomainProfileRow).where(DomainProfileRow.tenant_id == tenant_id)).first()
        if row is None:
            return
        config = dict(row.config)
        config["identity"] = {"organizationName": "Demo Tenant", "greeting": "Welcome to Demo Tenant. How can I help?"}
        row.config = config
        session.commit()
    client.patch(f"/api/superadmin/users/{uid}", json={"businessName": "Softsuave hotel"}, headers=headers)
    with session_factory() as session:
        row = session.scalars(select(DomainProfileRow).where(DomainProfileRow.tenant_id == tenant_id)).first()
        assert row.config["identity"]["greeting"] == "Welcome to Softsuave hotel. How can I help?"
