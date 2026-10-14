import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError
from app.notifications import email as mail
from app.notifications.email import ConsoleEmailSender, SendGridEmailSender, create_email_sender


def settings(**overrides) -> Settings:
    base = dict(sendgrid_api_key="SG.secret-key", email_from="no-reply@acme.com")
    return Settings(_env_file=None, **{**base, **overrides})


def test_sender_choice_depends_on_the_api_key():
    assert isinstance(create_email_sender(settings()), SendGridEmailSender)
    assert isinstance(create_email_sender(settings(sendgrid_api_key="")), ConsoleEmailSender)


def test_posts_the_expected_request(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(202)

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    SendGridEmailSender(settings()).send("to@example.com", "Hi", "Body")
    assert seen["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert seen["headers"]["Authorization"] == "Bearer SG.secret-key"
    assert seen["json"]["personalizations"] == [{"to": [{"email": "to@example.com"}]}]
    assert seen["json"]["from"] == {"email": "no-reply@acme.com"}
    assert seen["json"]["content"] == [{"type": "text/plain", "value": "Body"}]


@pytest.mark.parametrize(
    "status,text,expected",
    [
        (401, "unauthorized", "API key"),
        (403, "The from address does not match a verified Sender Identity", "Verify the EMAIL_FROM"),
        (400, "bad", "valid, verified address"),
        (429, "slow down", "rate limit"),
        (500, "oops", r"error \(500\)"),
    ],
)
def test_errors_are_explained_without_leaking_the_key(monkeypatch, status, text, expected):
    monkeypatch.setattr(mail.httpx, "post", lambda *a, **k: httpx.Response(status, text=text))
    with pytest.raises(UpstreamError, match=expected) as err:
        SendGridEmailSender(settings()).send("to@example.com", "Hi", "B")
    assert "SG.secret-key" not in err.value.message


def test_unreachable_and_missing_config(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(mail.httpx, "post", boom)
    with pytest.raises(UpstreamError, match="could not be reached"):
        SendGridEmailSender(settings()).send("to@example.com", "Hi", "B")
    with pytest.raises(ConfigurationError, match="SENDGRID_API_KEY"):
        SendGridEmailSender(settings(sendgrid_api_key="")).send("to@example.com", "Hi", "B")
    with pytest.raises(ConfigurationError, match="EMAIL_FROM"):
        SendGridEmailSender(settings(email_from="")).send("to@example.com", "Hi", "B")
