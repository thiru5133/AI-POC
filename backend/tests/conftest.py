import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.fake import FakeLLMProvider
from app.api import deps
from app.auth.security import create_access_token, hash_password
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.database.seed import seed
from app.database.session import Base
from app.main import app
from sqlalchemy import select
from app.auth.security import utcnow
from app.models import Domain, User
from app.tenants.service import create_organization
from app.notifications.email import EmailSender
from app.voice.fakes import FakeSTT, FakeTTS
from app import models  # noqa: F401

TENANT = get_settings().default_tenant_id
PROFILE = get_settings().default_domain_profile_id


class RecordingEmailSender(EmailSender):
    """Keeps sent emails in memory; `fail` simulates a delivery error."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise UpstreamError("Could not send the email")
        self.sent.append((to, subject, body))


def make_admin(session_factory, tenant_id: str = TENANT, email: str = "demo-admin@example.com") -> dict:
    """An active admin of `tenant_id` and their auth: {"headers": ..., "token": ..., "user_id": ...}."""
    with session_factory() as session:
        user = User(
            email=email,
            name=email.split("@")[0],
            password_hash=hash_password("unused-password-1"),
            role="admin",
            status="active",
            tenant_id=tenant_id,
            email_verified_at=utcnow(),
        )
        session.add(user)
        session.commit()
        token = create_access_token(get_settings(), user.id, "admin", tenant_id)
        return {"headers": {"Authorization": f"Bearer {token}"}, "token": token, "user_id": user.id}


def make_tenant(session_factory, name: str, domain: str = "hotel") -> str:
    with session_factory() as session:
        tenant = create_organization(session, name, session.scalars(select(Domain).where(Domain.key == domain)).one())
        session.commit()
        return tenant.id


@pytest.fixture
def demo_admin(session_factory):
    return make_admin(session_factory)


@pytest.fixture
def outbox():
    return RecordingEmailSender()


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed(factory)
    return factory


@pytest.fixture
def llm():
    return FakeLLMProvider(lambda system, messages: "Check-in starts at 2 PM. Anything else?")


@pytest.fixture
def tts():
    return FakeTTS()


@pytest.fixture
def client(session_factory, llm, tts, outbox):
    app.dependency_overrides[deps.get_sessions] = lambda: session_factory
    app.dependency_overrides[deps.get_email_sender] = lambda: outbox
    app.dependency_overrides[deps.get_llm] = lambda: llm
    app.dependency_overrides[deps.get_stt] = lambda: FakeSTT()
    app.dependency_overrides[deps.get_tts] = lambda: tts
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def otp_from(outbox, to: str) -> str:
    """The latest verification code emailed to `to`."""
    body = next(b for t, _, b in reversed(outbox.sent) if t == to and "verification code" in b)
    return next(line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("Your verification code is: "))


def login_headers(client, outbox, email: str, password: str) -> dict:
    """Log in, completing the first-login OTP step when it is asked for; returns Authorization headers."""
    resp = client.post("/api/auth/login", json={"identifier": email, "password": password})
    assert resp.status_code == 200, resp.text
    if resp.json().get("otpRequired"):
        resp = client.post("/api/auth/verify-otp", json={"email": email, "code": otp_from(outbox, email)})
        assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}
