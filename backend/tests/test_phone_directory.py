"""Domain numbers (set by a superadmin) and the number lists customers see."""

import pytest
from sqlalchemy import select

from app.auth.ratelimit import public_limiter
from app.auth.security import create_access_token
from app.core.config import get_settings
from app.models import Domain, PhoneNumber, Tenant, User

from .conftest import make_admin, make_tenant

HOTEL_LINE = "+17692630020"
GYM_LINE = "+17372508034"
HUMAN = "+919876543210"
OWN = "+914412345678"


@pytest.fixture(autouse=True)
def _fresh_limiter():
    public_limiter.reset()


@pytest.fixture
def root(client, session_factory) -> dict:
    admin = make_admin(session_factory, None, "root@example.com")
    with session_factory() as session:
        session.get(User, admin["user_id"]).role = "superadmin"
        session.commit()
    token = create_access_token(get_settings(), admin["user_id"], "superadmin", None)
    return {"Authorization": f"Bearer {token}"}


def domain_id(session_factory, key: str) -> str:
    with session_factory() as session:
        return session.scalars(select(Domain).where(Domain.key == key)).one().id


def set_domain(client, root, session_factory, key, number, transfer=None):
    return client.put(
        f"/api/superadmin/domain-numbers/{domain_id(session_factory, key)}",
        json={"number": number, "transferNumber": transfer},
        headers=root,
    )


def two_hotels(session_factory):
    return make_tenant(session_factory, "Alpha Hotel", "hotel"), make_tenant(session_factory, "Beta Hotel", "hotel")


# ---------- the superadmin sets a domain's number ----------
def test_only_a_superadmin_manages_domain_numbers(client, session_factory):
    assert client.get("/api/superadmin/domain-numbers").status_code == 401
    admin = make_admin(session_factory)
    assert client.get("/api/superadmin/domain-numbers", headers=admin["headers"]).status_code == 403
    assert client.put(f"/api/superadmin/domain-numbers/{domain_id(session_factory, 'hotel')}", json={"number": HOTEL_LINE}, headers=admin["headers"]).status_code == 403


def test_a_domain_number_is_saved_listed_and_cleared(client, root, session_factory):
    rows = client.get("/api/superadmin/domain-numbers", headers=root).json()
    assert {r["key"] for r in rows} >= {"hotel", "fitness"} and all(r["number"] is None for r in rows)
    assert set_domain(client, root, session_factory, "hotel", HOTEL_LINE, HUMAN).json()["number"] == HOTEL_LINE
    by_key = {r["key"]: r for r in client.get("/api/superadmin/domain-numbers", headers=root).json()}
    assert by_key["hotel"]["number"] == HOTEL_LINE and by_key["hotel"]["transferNumber"] == HUMAN and by_key["fitness"]["number"] is None
    assert set_domain(client, root, session_factory, "hotel", None).json()["number"] is None
    assert {r["key"]: r for r in client.get("/api/superadmin/domain-numbers", headers=root).json()}["hotel"]["number"] is None


def test_the_number_belongs_to_the_domains_compare_all_assistant(client, root, session_factory):
    set_domain(client, root, session_factory, "hotel", HOTEL_LINE)
    with session_factory() as session:
        row = session.scalars(select(PhoneNumber).where(PhoneNumber.number == HOTEL_LINE)).one()
        tenant = session.get(Tenant, row.tenant_id)
        assert tenant.is_marketplace and tenant.domain_id == domain_id(session_factory, "hotel")


def test_domain_number_validation(client, root, session_factory):
    assert set_domain(client, root, session_factory, "hotel", "12345").status_code == 422
    assert set_domain(client, root, session_factory, "hotel", HOTEL_LINE, HOTEL_LINE).json()["error"]["code"] == "transfer_loop"
    assert client.put("/api/superadmin/domain-numbers/nope", json={"number": HOTEL_LINE}, headers=root).status_code == 404


def test_numbers_are_unique_across_businesses_and_domains(client, root, session_factory):
    tenant = make_tenant(session_factory, "Solo Gym", "fitness")
    admin = make_admin(session_factory, tenant, "solo@example.com")
    assert client.put("/api/org/phone", json={"number": OWN}, headers=admin["headers"]).status_code == 200
    assert set_domain(client, root, session_factory, "hotel", OWN).json()["error"]["code"] == "number_taken"  # a business has it
    assert set_domain(client, root, session_factory, "hotel", HOTEL_LINE).status_code == 200
    assert client.put("/api/org/phone", json={"number": HOTEL_LINE}, headers=admin["headers"]).json()["error"]["code"] == "number_taken"  # a domain has it
    assert set_domain(client, root, session_factory, "fitness", HOTEL_LINE).json()["error"]["code"] == "number_taken"


# ---------- customers see the numbers ----------
def test_the_customer_list_carries_each_businesss_and_domains_number(client, root, session_factory):
    alpha, beta = two_hotels(session_factory)
    admin = make_admin(session_factory, alpha, "alpha@example.com")
    client.put("/api/org/phone", json={"number": OWN}, headers=admin["headers"])
    set_domain(client, root, session_factory, "hotel", HOTEL_LINE)
    rows = {b["name"]: b for b in client.get("/api/businesses", headers=admin["headers"]).json()}
    assert rows["Alpha Hotel"]["phone"] == OWN and rows["Beta Hotel"]["phone"] is None
    line = next(b for b in rows.values() if b["isMarketplace"])
    assert line["phone"] == HOTEL_LINE


# ---------- the public page needs no login ----------
def test_the_public_list_needs_no_login_and_shows_only_names_and_numbers(client, root, session_factory):
    alpha, _ = two_hotels(session_factory)
    admin = make_admin(session_factory, alpha, "alpha@example.com")
    client.put("/api/org/phone", json={"number": OWN, "transferNumber": HUMAN}, headers=admin["headers"])
    set_domain(client, root, session_factory, "hotel", HOTEL_LINE)
    rows = client.get("/api/public/businesses").json()  # no credentials at all
    assert {r["name"]: r["phone"] for r in rows if not r["isMarketplace"]} == {"Alpha Hotel": OWN}  # Beta has no number
    assert [r["phone"] for r in rows if r["isMarketplace"]] == [HOTEL_LINE]
    assert all(set(r) == {"id", "name", "domainName", "isMarketplace", "phone"} for r in rows)  # no transfer number, no admin
    assert HUMAN not in client.get("/api/public/businesses").text


def test_the_public_page_hides_inactive_businesses_and_thin_marketplaces(client, root, session_factory):
    solo = make_tenant(session_factory, "Solo Gym", "fitness")  # a domain with one partner: no compare-all is offered
    admin = make_admin(session_factory, solo, "solo@example.com")
    client.put("/api/org/phone", json={"number": OWN}, headers=admin["headers"])
    set_domain(client, root, session_factory, "fitness", GYM_LINE)
    names = [r["name"] for r in client.get("/api/public/businesses").json()]
    assert names == ["Solo Gym"]  # the gym line still works for callers, it is just not advertised yet
    with session_factory() as session:
        session.get(Tenant, solo).is_active = False
        session.commit()
    assert client.get("/api/public/businesses").json() == []


def test_one_business_by_id_and_a_missing_one(client, session_factory):
    alpha = make_tenant(session_factory, "Alpha Hotel", "hotel")
    admin = make_admin(session_factory, alpha, "alpha@example.com")
    assert client.get(f"/api/public/businesses/{alpha}").status_code == 404  # no number yet
    client.put("/api/org/phone", json={"number": OWN}, headers=admin["headers"])
    got = client.get(f"/api/public/businesses/{alpha}").json()
    assert (got["name"], got["phone"]) == ("Alpha Hotel", OWN)
    assert client.get("/api/public/businesses/unknown").status_code == 404


def test_the_public_list_is_rate_limited(client):
    for _ in range(60):
        assert client.get("/api/public/businesses").status_code == 200
    assert client.get("/api/public/businesses").status_code == 429


# ---------- a call to a domain's number ----------
def test_a_call_to_a_domain_number_reaches_its_compare_all_assistant(client, root, session_factory):
    from app.main import app
    from app.voice import vapi

    from . import test_vapi as tv

    app.dependency_overrides[get_settings] = lambda: tv.vapi_settings()
    set_domain(client, root, session_factory, "hotel", HOTEL_LINE)
    assistant = client.post("/api/vapi/webhook", json=tv.incoming(HOTEL_LINE), headers=tv.AUTH).json()["assistant"]
    claims = vapi.read_llm_token(tv.vapi_settings(), assistant["model"]["url"].rsplit("/", 1)[1])
    with session_factory() as session:
        tenant = session.get(Tenant, claims["tid"])
        assert tenant.is_marketplace and tenant.domain_id == domain_id(session_factory, "hotel")


# ---------- the business admin is told about the domain's line ----------
def test_a_business_admin_sees_the_shared_line_of_their_domain(client, root, session_factory):
    tenant = make_tenant(session_factory, "Alpha Hotel", "hotel")
    admin = make_admin(session_factory, tenant, "alpha@example.com")
    got = client.get("/api/org/phone", headers=admin["headers"]).json()
    assert (got["domainName"], got["domainNumber"]) == ("Hotels", None)  # no shared line yet
    set_domain(client, root, session_factory, "hotel", HOTEL_LINE)
    got = client.get("/api/org/phone", headers=admin["headers"]).json()
    assert got["domainNumber"] == HOTEL_LINE and got["number"] is None  # read-only context; their own number is separate
    other = make_admin(session_factory, make_tenant(session_factory, "Solo Gym", "fitness"), "gym@example.com")
    assert client.get("/api/org/phone", headers=other["headers"]).json()["domainNumber"] is None  # another domain's line is not shown
