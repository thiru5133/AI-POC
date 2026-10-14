import pytest

from app.auth.ratelimit import login_limiter
from app.auth.security import hash_password, utcnow
from app.models import DomainProfileRow, Tenant, User

from .conftest import login_headers, otp_from

PASSWORD = "correct-horse-1"
SUPER_EMAIL = "root@example.com"


@pytest.fixture(autouse=True)
def _reset_limiter():
    login_limiter.reset()


@pytest.fixture
def sa_headers(client, session_factory):
    with session_factory() as session:
        session.add(
            User(email=SUPER_EMAIL, name="Root", password_hash=hash_password(PASSWORD), role="superadmin", status="active", email_verified_at=utcnow())
        )
        session.commit()
    return headers_for(client, SUPER_EMAIL, PASSWORD)


def headers_for(client, email, password, outbox=None):
    if outbox is not None:
        return login_headers(client, outbox, email, password)
    resp = client.post("/api/auth/login", json={"identifier": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def domain_id(client, sa_headers, key="hotel"):
    return next(d["id"] for d in client.get("/api/businesses/domains", headers=sa_headers).json() if d["key"] == key)


def emailed_password(outbox, to) -> str:
    body = next(b for t, _, b in reversed(outbox.sent) if t == to)
    return next(line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("Password: "))


def create_business(client, sa_headers, name="Acme Hotel", admin_email="owner@acme.com", domain="hotel"):
    return client.post(
        "/api/superadmin/businesses",
        headers=sa_headers,
        json={"name": name, "adminName": "Owner", "adminEmail": admin_email, "domainId": domain_id(client, sa_headers, domain)},
    )


def signup(client, outbox, email="cust@example.com"):
    client.post("/api/auth/register", json={"name": "Cust", "email": email, "password": PASSWORD})
    return login_headers(client, outbox, email, PASSWORD)


def test_superadmin_creates_business_and_admin_logs_in(client, sa_headers, outbox, session_factory):
    created = create_business(client, sa_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Acme Hotel" and body["isActive"] and body["adminEmail"] == "owner@acme.com"

    password = emailed_password(outbox, "owner@acme.com")
    # First login: the password alone starts no session, an emailed code is needed too.
    first = client.post("/api/auth/login", json={"identifier": "owner@acme.com", "password": password})
    assert first.status_code == 200 and first.json()["otpRequired"] is True and first.json()["accessToken"] is None
    admin = client.post("/api/auth/verify-otp", json={"email": "owner@acme.com", "code": otp_from(outbox, "owner@acme.com")})
    assert admin.status_code == 200
    assert admin.json()["user"]["role"] == "admin" and admin.json()["user"]["tenantId"] == body["id"]
    assert body["domainName"] == "Hotels"
    with session_factory() as session:
        profile = session.query(DomainProfileRow).filter_by(tenant_id=body["id"]).one()
        assert profile.config["identity"]["organizationName"] == "Acme Hotel"

    listed = client.get("/api/superadmin/businesses", headers=sa_headers).json()
    assert {b["name"] for b in listed} == {"Demo Tenant", "Acme Hotel"}


def test_business_creation_conflicts_and_email_failure_rolls_back(client, sa_headers, outbox, session_factory):
    outbox.fail = True
    assert create_business(client, sa_headers).status_code >= 400
    with session_factory() as session:
        assert session.query(Tenant).count() == 1  # only the demo tenant: nothing half-created
        assert session.query(User).filter_by(email="owner@acme.com").count() == 0

    outbox.fail = False
    assert create_business(client, sa_headers).status_code == 201
    assert create_business(client, sa_headers, admin_email="x@acme.com").status_code == 409  # same name
    assert create_business(client, sa_headers, name="Other", admin_email="OWNER@acme.com").status_code == 409


def test_only_superadmin_manages_businesses(client, sa_headers, outbox):
    create_business(client, sa_headers)
    admin = headers_for(client, "owner@acme.com", emailed_password(outbox, "owner@acme.com"), outbox)
    assert client.get("/api/superadmin/businesses", headers=admin).status_code == 403
    assert client.post("/api/superadmin/businesses", headers=admin, json={}).status_code in (403, 422)
    assert client.get("/api/superadmin/businesses", headers=signup(client, outbox)).status_code == 403


def test_disabling_a_business_locks_out_admin_and_customers(client, sa_headers, outbox):
    biz = create_business(client, sa_headers).json()
    password = emailed_password(outbox, "owner@acme.com")
    customer = {**signup(client, outbox), "X-Business-Id": biz["id"]}
    assert client.post("/api/conversations", headers=customer).status_code == 200

    off = client.patch(f"/api/superadmin/businesses/{biz['id']}", headers=sa_headers, json={"isActive": False})
    assert off.status_code == 200 and off.json()["isActive"] is False
    assert client.post("/api/auth/login", json={"identifier": "owner@acme.com", "password": password}).status_code == 403
    assert client.post("/api/conversations", headers=customer).status_code == 403
    assert biz["id"] not in {b["id"] for b in client.get("/api/businesses", headers=customer).json()}

    client.patch(f"/api/superadmin/businesses/{biz['id']}", headers=sa_headers, json={"isActive": True})
    assert client.post("/api/auth/login", json={"identifier": "owner@acme.com", "password": password}).status_code == 200
    assert client.post("/api/conversations", headers=customer).status_code == 200
    assert client.patch("/api/superadmin/businesses/nope", headers=sa_headers, json={"isActive": True}).status_code == 404


def test_customer_chats_with_a_chosen_business(client, sa_headers, outbox):
    biz = create_business(client, sa_headers).json()
    auth = signup(client, outbox)
    businesses = client.get("/api/businesses", headers=auth).json()
    assert {b["name"] for b in businesses} == {"Demo Tenant", "Acme Hotel", "All Hotels (compare)"}

    assert client.post("/api/conversations", headers=auth).status_code == 403  # no business chosen
    assert client.post("/api/conversations", headers={**auth, "X-Business-Id": "nope"}).status_code == 403

    headers = {**auth, "X-Business-Id": biz["id"]}
    conv = client.post("/api/conversations", headers=headers).json()
    reply = client.post(f"/api/conversations/{conv['id']}/messages", headers=headers, json={"text": "Do you have rooms?"})
    assert reply.status_code == 200 and reply.json()["reply"]
    assert client.get("/api/conversations", headers=headers).json()["total"] == 1

    # The business admin sees the customer's conversation; the superadmin takes no part in conversations.
    admin = headers_for(client, "owner@acme.com", emailed_password(outbox, "owner@acme.com"), outbox)
    seen = client.get("/api/conversations", headers=admin).json()
    assert seen["total"] == 1
    assert client.get(f"/api/conversations/{conv['id']}", headers=admin).status_code == 200
    assert client.post("/api/conversations", headers=sa_headers).status_code == 403


def test_customers_cannot_see_each_others_conversations(client, sa_headers, outbox):
    biz = create_business(client, sa_headers).json()
    one = {**signup(client, outbox, "one@example.com"), "X-Business-Id": biz["id"]}
    two = {**signup(client, outbox, "two@example.com"), "X-Business-Id": biz["id"]}
    conv = client.post("/api/conversations", headers=one).json()
    client.post(f"/api/conversations/{conv['id']}/messages", headers=one, json={"text": "hello"})

    assert client.get(f"/api/conversations/{conv['id']}", headers=two).status_code == 404
    assert client.post(f"/api/conversations/{conv['id']}/messages", headers=two, json={"text": "hi"}).status_code == 404
    assert client.get("/api/conversations", headers=two).json()["total"] == 0
    assert client.get("/api/conversations", headers=one).json()["total"] == 1


def test_a_business_needs_a_real_domain_and_master_data_has_no_generic_one(client, sa_headers):
    domains = client.get("/api/businesses/domains", headers=sa_headers).json()
    keys = {d["key"] for d in domains}
    assert {"hotel", "school", "hospital"} <= keys and "generic" not in keys

    body = {"name": "X", "adminName": "O", "adminEmail": "o@x.com"}
    assert client.post("/api/superadmin/businesses", headers=sa_headers, json=body).status_code == 422  # no domain
    bad = client.post("/api/superadmin/businesses", headers=sa_headers, json={**body, "domainId": "nope"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_domain"


def test_each_domain_gets_its_own_profile_and_a_marketplace_once_two_partners_exist(client, sa_headers, outbox, session_factory):
    school = create_business(client, sa_headers, "Sunrise School", "head@school.com", "school").json()
    assert school["domainName"] == "Schools"
    with session_factory() as session:
        profile = session.query(DomainProfileRow).filter_by(tenant_id=school["id"]).one()
        assert profile.domain_type == "school" and "school" in profile.config["identity"]["persona"]
        assert profile.config["bookingWorkflow"]["resourceType"] == "admission_visit"

    auth = signup(client, outbox)
    names = lambda: {(b["name"], b["isMarketplace"]) for b in client.get("/api/businesses", headers=auth).json()}  # noqa: E731
    assert ("Sunrise School", False) in names() and not any(m for _, m in names())  # one partner: nothing to compare

    create_business(client, sa_headers, "Green Valley School", "head@gv.com", "school")
    assert ("All Schools (compare)", True) in names()
    # The shared assistants never appear in the superadmin's list of businesses.
    assert not any(b["name"].startswith("All ") for b in client.get("/api/superadmin/businesses", headers=sa_headers).json())
