"""Pings a business's own people when a caller needs a person: a text to the number a call is transferred to and an
email to the business's admins. Never raises: a failed ping must not break the call."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import PhoneNumber, User
from app.notifications.email import EmailSender
from app.notifications.messaging import MessageSender

log = logging.getLogger(__name__)


class StaffAlerts:
    def __init__(
        self, session_factory: Callable[[], Session], sms: MessageSender, email: EmailSender, app_base_url: str = ""
    ):
        self._sf = session_factory
        self._sms = sms
        self._email = email
        self._app_base_url = app_base_url.rstrip("/")

    def _contacts(self, tenant_id: str) -> tuple[str | None, list[str]]:
        with self._sf() as session:
            number = session.scalars(select(PhoneNumber.transfer_number).where(PhoneNumber.tenant_id == tenant_id)).first()
            emails = session.scalars(
                select(User.email).where(User.tenant_id == tenant_id, User.role == "admin", User.status == "active")
            ).all()
            return number, list(emails)

    def send(
        self,
        tenant_id: str,
        organization: str,
        reason: str,
        caller_phone: str | None,
        conversation_id: str | None = None,
        subject: str | None = None,
    ) -> bool:
        """Blocking. `reason` says why the caller needs a person (for example a system problem). True when at least one
        channel delivered; when none did the failure is logged as an error, because the caller is waiting for a call back."""
        caller = caller_phone or "an unknown number"
        text = f"{organization}: a caller ({caller}) needs a person. {reason}"
        try:
            number, emails = self._contacts(tenant_id)
        except Exception:
            log.exception("could not look up staff contacts", extra={"tenant_id": tenant_id})
            return False
        if not number and not emails:
            log.warning("a caller needs a person but nobody can be notified", extra={"tenant_id": tenant_id})
            return False
        details = [text, f"Caller's number: {caller}", f"Time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
        if conversation_id and self._app_base_url:
            details.append(f"Conversation: {self._app_base_url}/conversations/{conversation_id}")
        email_body = "\n".join(details) + "\n"
        email_subject = subject or f"A caller needs a person at {organization}"
        delivered = False
        if number:
            delivered |= self._try(lambda: self._sms.send(number, text[:480]), tenant_id, "sms")
        for email in emails:
            delivered |= self._try(lambda email=email: self._email.send(email, email_subject, email_body), tenant_id, "email")
        if not delivered:
            log.error(
                "staff alert NOT delivered on any channel: the caller is waiting for a call back",
                extra={"tenant_id": tenant_id, "caller": caller, "reason": reason},
            )
        return delivered

    @staticmethod
    def _try(send: Callable[[], None], tenant_id: str, channel: str) -> bool:
        try:
            send()
            return True
        except AppError as exc:
            log.warning("staff alert not delivered", extra={"tenant_id": tenant_id, "channel": channel, "error": exc.message})
        except Exception:
            log.exception("staff alert failed", extra={"tenant_id": tenant_id, "channel": channel})
        return False
