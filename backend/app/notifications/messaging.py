"""Outgoing SMS / WhatsApp / email confirmations. `MessageSender` is the seam: Twilio in real deployments, a logging
sender for dev (same pattern as email.py)."""

import logging
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError
from app.notifications.email import EmailSender

log = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
REQUEST_TIMEOUT_SECONDS = 15


class MessageSender(ABC):
    @abstractmethod
    def send(self, to: str, body: str) -> None:
        """Blocking send; raises UpstreamError if the message could not be delivered."""


class TwilioMessageSender(MessageSender):
    """SMS, or WhatsApp when `whatsapp` is true, over Twilio's REST API (Basic auth with the account SID and token)."""

    def __init__(self, settings: Settings, whatsapp: bool = False):
        self._s = settings
        self._whatsapp = whatsapp

    def send(self, to: str, body: str) -> None:
        sender = self._s.twilio_whatsapp_from if self._whatsapp else self._s.twilio_sms_from
        if not (self._s.twilio_account_sid and self._s.twilio_auth_token):
            raise ConfigurationError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are not set")
        if not sender:
            raise ConfigurationError(f"Set TWILIO_{'WHATSAPP' if self._whatsapp else 'SMS'}_FROM to a Twilio sender")
        prefix = "whatsapp:" if self._whatsapp else ""
        try:
            resp = httpx.post(
                TWILIO_URL.format(sid=self._s.twilio_account_sid),
                data={"To": prefix + to, "From": prefix + sender, "Body": body},
                auth=(self._s.twilio_account_sid, self._s.twilio_auth_token),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.error("twilio request failed: %s", type(exc).__name__)
            raise UpstreamError("Could not send the message: Twilio could not be reached.") from exc
        if resp.status_code not in (200, 201):
            log.error("twilio rejected message: %s %s", resp.status_code, resp.text[:300])
            raise UpstreamError(f"Could not send the message: Twilio returned an error ({resp.status_code}).")
        log.info("%s sent via Twilio", "whatsapp message" if self._whatsapp else "sms")


class ConsoleMessageSender(MessageSender):
    """Dev fallback when Twilio is not configured: writes the message to the log instead of sending it."""

    def __init__(self, channel: str):
        self._channel = channel

    def send(self, to: str, body: str) -> None:
        log.warning("Twilio is not configured; %s NOT sent. To: %s\n%s", self._channel, to, body)


class EmailMessageSender(MessageSender):
    def __init__(self, email: EmailSender, subject: str = "Your booking confirmation"):
        self._email = email
        self._subject = subject

    def send(self, to: str, body: str) -> None:
        self._email.send(to, self._subject, body)


def create_message_senders(settings: Settings, email: EmailSender) -> dict[str, MessageSender]:
    """One sender per channel the `send_confirmation` tool offers: sms, whatsapp, email."""
    twilio = bool(settings.twilio_account_sid)
    return {
        "sms": TwilioMessageSender(settings) if twilio else ConsoleMessageSender("sms"),
        "whatsapp": TwilioMessageSender(settings, whatsapp=True) if twilio else ConsoleMessageSender("whatsapp"),
        "email": EmailMessageSender(email),
    }
