"""Outgoing email. `EmailSender` is the seam: Twilio SendGrid in real deployments, a logging sender for dev."""

import logging
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError

log = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
REQUEST_TIMEOUT_SECONDS = 15


class EmailSender(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Blocking send; raises UpstreamError if the message could not be delivered."""


class SendGridEmailSender(EmailSender):
    """Twilio SendGrid over its HTTPS API: only an API key and a verified sender address are needed."""

    def __init__(self, settings: Settings):
        self._s = settings

    def send(self, to: str, subject: str, body: str) -> None:
        if not self._s.sendgrid_api_key:
            raise ConfigurationError("SENDGRID_API_KEY is not set")
        if not self._s.email_from:
            raise ConfigurationError("Set EMAIL_FROM to a sender address verified in SendGrid")
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self._s.email_from},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        try:
            resp = httpx.post(
                SENDGRID_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._s.sendgrid_api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.error("sendgrid request to %s failed: %s: %s", to, type(exc).__name__, exc)
            raise UpstreamError("Could not send the email: SendGrid could not be reached.") from exc
        if resp.status_code != 202:
            log.error("sendgrid rejected email to %s: %s %s", to, resp.status_code, resp.text[:300])
            raise UpstreamError(f"Could not send the email: {explain_sendgrid_error(resp.status_code, resp.text)}")
        log.info("email sent to %s via SendGrid (%s)", to, subject)


def explain_sendgrid_error(status: int, text: str) -> str:
    if status in (401, 403):
        if "verified" in text.lower() or "from address" in text.lower():
            return "SendGrid does not accept this sender. Verify the EMAIL_FROM address (Settings -> Sender Authentication)."
        return "SendGrid rejected the API key. Check SENDGRID_API_KEY has 'Mail Send' permission."
    if status == 400:
        return "SendGrid rejected the message. Check EMAIL_FROM is a valid, verified address."
    if status == 429:
        return "SendGrid rate limit reached. Try again shortly."
    return f"SendGrid returned an error ({status}). See the backend log for details."


class ConsoleEmailSender(EmailSender):
    """Dev fallback when no API key is set: writes the message to the log instead of sending it."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.warning("SENDGRID_API_KEY is not set; email NOT sent. To: %s | Subject: %s\n%s", to, subject, body)


def create_email_sender(settings: Settings) -> EmailSender:
    return SendGridEmailSender(settings) if settings.sendgrid_api_key else ConsoleEmailSender()


def credentials_email(name: str, organization: str, email: str, password: str, login_url: str) -> tuple[str, str]:
    """(subject, body) sent to a business admin when a superadmin creates their business."""
    subject = f"Your {organization} account is ready"
    body = (
        f"Hello {name},\n\n"
        f"Your request for admin access for {organization} has been approved.\n\n"
        f"Log in at: {login_url}\n"
        f"Email: {email}\n"
        f"Password: {password}\n\n"
        "Keep this password private.\n"
    )
    return subject, body


def otp_email(name: str, code: str, minutes: int) -> tuple[str, str]:
    """(subject, body) with the one-time code that confirms a new account's email address."""
    body = (
        f"Hello {name},\n\n"
        f"Your verification code is: {code}\n\n"
        f"It expires in {minutes} minutes. If you did not try to log in, you can ignore this email.\n"
    )
    return "Your verification code", body
