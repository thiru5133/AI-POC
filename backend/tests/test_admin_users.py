import pytest

from app.auth.ratelimit import login_limiter
from app.auth.security import hash_password
from app.core.config import get_settings
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
    body = client.get("/api/admin/users", headers=headers).json()
    assert body["total"] == 6
    assert body["counts"] == {"active": 3, "pending": 1, "rejected": 1, "disabled": 1}


def test_filter_by_status(client, headers):
    active = client.get("/api/admin/users?status=active", headers=headers)
    assert names(active) == ["Asha Rao", "Bala Kumar", "Root"]
    assert active.json()["total"] == 3
    assert names(client.get("/api/admin/users?status=pending", headers=headers)) == ["Chitra Devi"]


def test_filter_by_role_and_counts_follow_role(client, headers):
    resp = client.get("/api/admin/users?role=admin", headers=headers)
    assert "Root" not in names(resp)
    assert resp.json()["counts"]["active"] == 2


def test_search_name_or_email_case_insensitive(client, headers):
    assert names(client.get("/api/admin/users?q=ASHA", headers=headers)) == ["Asha Rao"]
    assert names(client.get("/api/admin/users?q=bala@", headers=headers)) == ["Bala Kumar"]
    combined = client.get("/api/admin/users?q=example.com&status=active&role=admin", headers=headers)
    assert names(combined) == ["Asha Rao", "Bala Kumar"]


def test_search_treats_wildcards_literally(client, headers):
    assert names(client.get("/api/admin/users?q=%25", headers=headers)) == ["100%_Sure"]  # "%"
    assert names(client.get("/api/admin/users?q=_", headers=headers)) == ["100%_Sure"]


def test_pagination(client, headers):
    page1 = client.get("/api/admin/users?limit=4&offset=0", headers=headers).json()
    page2 = client.get("/api/admin/users?limit=4&offset=4", headers=headers).json()
    assert page1["total"] == page2["total"] == 6
    assert len(page1["items"]) == 4 and len(page2["items"]) == 2
    assert not {u["id"] for u in page1["items"]} & {u["id"] for u in page2["items"]}
    assert client.get("/api/admin/users?limit=0", headers=headers).status_code == 422


def test_user_detail_includes_tenant_and_reviewer(client, headers):
    asha = next(u for u in client.get("/api/admin/users?q=asha", headers=headers).json()["items"])
    # approve a pending user so reviewer details are populated
    chitra = next(u for u in client.get("/api/admin/users?status=pending", headers=headers).json()["items"])
    assert client.post(f"/api/admin/onboarding-requests/{chitra['id']}/approve", headers=headers).status_code == 200

    detail = client.get(f"/api/admin/users/{chitra['id']}", headers=headers).json()
    assert detail["status"] == "active"
    assert detail["reviewedByName"] == "Root"
    assert detail["reviewedAt"]
    assert detail["tenantName"] == "Chitra Devi's Organization"

    plain = client.get(f"/api/admin/users/{asha['id']}", headers=headers).json()
    assert plain["email"] == "asha@example.com" and plain["reviewedByName"] is None
    assert "passwordHash" not in plain and "password_hash" not in plain


def test_rejected_user_detail_shows_reason(client, headers):
    dev = next(u for u in client.get("/api/admin/users?status=rejected", headers=headers).json()["items"])
    assert client.get(f"/api/admin/users/{dev['id']}", headers=headers).json()["rejectionReason"] == "Not a customer"


def test_unknown_user_is_404(client, headers):
    assert client.get("/api/admin/users/nope", headers=headers).status_code == 404


def test_users_endpoints_are_superadmin_only(client, seeded):
    assert client.get("/api/admin/users").status_code == 401
    token = client.post("/api/auth/login", json={"identifier": "asha@example.com", "password": PASSWORD}).json()[
        "accessToken"
    ]
    admin = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/users", headers=admin).status_code == 403
    assert client.get("/api/admin/users/anything", headers=admin).status_code == 403
