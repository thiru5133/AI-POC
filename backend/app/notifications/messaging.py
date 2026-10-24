"""Outgoing SMS / WhatsApp / email confirmations. `MessageSender` is the seam: Twilio in real deployments, a logging
sender for dev (same pattern as email.py)."""

import logging
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, UpstreamError
from app.notifications.email import EmailSender

log = logging.getLogger(__name__)

# A Trial Twilio account cannot send free text through the API: the body must name one of Twilio's own templates and
# Twilio supplies the wording. Upgrading the account removes this, and then the real message is sent.
TRIAL_TEMPLATE_ERROR = 572006
TRIAL_CONFIRMATION_TEMPLATE = "sms_order_confirmation"
TRIAL_ALERT_TEMPLATE = "sms_internal_alerts"

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
REQUEST_TIMEOUT_SECONDS = 15


class MessageSender(ABC):
    @abstractmethod
    def send(self, to: str, body: str) -> None:
        """Blocking send; raises UpstreamError if the message could not be delivered."""


class TwilioMessageSender(MessageSender):
    """SMS, or WhatsApp when `whatsapp` is true, over Twilio's REST API (Basic auth with the account SID and token)."""

    def __init__(self, settings: Settings, whatsapp: bool = False, trial_template: str = TRIAL_CONFIRMATION_TEMPLATE):
        self._s = settings
        self._whatsapp = whatsapp
        self._trial_template = trial_template

    def send(self, to: str, body: str) -> None:
        sender = self._s.twilio_whatsapp_from if self._whatsapp else self._s.twilio_sms_from
        if not (self._s.twilio_account_sid and self._s.twilio_auth_token):
            raise ConfigurationError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are not set")
        if not sender:
            raise ConfigurationError(f"Set TWILIO_{'WHATSAPP' if self._whatsapp else 'SMS'}_FROM to a Twilio sender")
        prefix = "whatsapp:" if self._whatsapp else ""
        resp = self._post(prefix + to, prefix + sender, body)
        if resp.status_code == 400 and not self._whatsapp and self._error_code(resp) == TRIAL_TEMPLATE_ERROR:
            log.warning("twilio trial account: sending the template %s instead of the message text", self._trial_template)
            resp = self._post(prefix + to, prefix + sender, self._trial_template)
        if resp.status_code not in (200, 201):
            log.error("twilio rejected message: %s %s", resp.status_code, resp.text[:300])
            raise UpstreamError(f"Could not send the message: Twilio returned an error ({resp.status_code}).")
        log.info("%s sent via Twilio", "whatsapp message" if self._whatsapp else "sms")

    def _post(self, to: str, sender: str, body: str) -> httpx.Response:
        try:
            return httpx.post(
                TWILIO_URL.format(sid=self._s.twilio_account_sid),
                data={"To": to, "From": sender, "Body": body},
                auth=(self._s.twilio_account_sid, self._s.twilio_auth_token),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.error("twilio request failed: %s", type(exc).__name__)
            raise UpstreamError("Could not send the message: Twilio could not be reached.") from exc

    @staticmethod
    def _error_code(resp: httpx.Response) -> int | None:
        try:
            return resp.json().get("code")
        except ValueError:
            return None


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


def create_alert_sms_sender(settings: Settings) -> MessageSender:
    """The SMS sender for texts to a business's own people (not offered to the assistant as a channel)."""
    if settings.twilio_account_sid:
        return TwilioMessageSender(settings, trial_template=TRIAL_ALERT_TEMPLATE)
    return ConsoleMessageSender("sms")
