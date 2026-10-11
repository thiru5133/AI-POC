import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.fake import FakeLLMProvider
from app.api import deps
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.database.seed import seed
from app.database.session import Base
from app.main import app
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
