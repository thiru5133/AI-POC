"""Pings a business's own people when a caller needs a person: a text to the number a call is transferred to and an
email to the business's admins. Never raises: a failed ping must not break the call."""

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import PhoneNumber, User
from app.notifications.email import EmailSender
from app.notifications.messaging import MessageSender

log = logging.getLogger(__name__)


class StaffAlerts:
    def __init__(self, session_factory: Callable[[], Session], sms: MessageSender, email: EmailSender):
        self._sf = session_factory
        self._sms = sms
        self._email = email

    def _contacts(self, tenant_id: str) -> tuple[str | None, list[str]]:
        with self._sf() as session:
            number = session.scalars(select(PhoneNumber.transfer_number).where(PhoneNumber.tenant_id == tenant_id)).first()
            emails = session.scalars(
                select(User.email).where(User.tenant_id == tenant_id, User.role == "admin", User.status == "active")
            ).all()
            return number, list(emails)

    def send(self, tenant_id: str, organization: str, reason: str, caller_phone: str | None) -> None:
        """Blocking. `reason` says why the caller needs a person (for example a system problem)."""
        caller = caller_phone or "an unknown number"
        text = f"{organization}: a caller ({caller}) needs a person. {reason}"
        try:
            number, emails = self._contacts(tenant_id)
        except Exception:
            log.exception("could not look up staff contacts", extra={"tenant_id": tenant_id})
            return
        if number:
            self._try(lambda: self._sms.send(number, text[:480]), tenant_id, "sms")
        for email in emails:
            self._try(
                lambda email=email: self._email.send(email, f"A caller needs a person at {organization}", f"{text}\n"),
                tenant_id,
                "email",
            )
        if not number and not emails:
            log.warning("a caller needs a person but nobody can be notified", extra={"tenant_id": tenant_id})

    @staticmethod
    def _try(send: Callable[[], None], tenant_id: str, channel: str) -> None:
        try:
            send()
        except AppError as exc:
            log.warning("staff alert not delivered", extra={"tenant_id": tenant_id, "channel": channel, "error": exc.message})
        except Exception:
            log.exception("staff alert failed", extra={"tenant_id": tenant_id, "channel": channel})
