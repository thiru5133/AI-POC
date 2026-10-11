"""Check the email settings without approving anyone:

    docker compose exec backend python -m app.notifications you@example.com
"""

import sys

from app.core.config import get_settings
from app.core.errors import AppError
from app.notifications.email import ConsoleEmailSender, create_email_sender


def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("usage: python -m app.notifications <recipient@example.com>")
        return 2
    settings = get_settings()
    sender = create_email_sender(settings)
    if isinstance(sender, ConsoleEmailSender):
        print("SENDGRID_API_KEY is empty: emails are only logged, not sent. Set SENDGRID_API_KEY and EMAIL_FROM in .env first.")
        return 1
    print(f"Sending a test email via {type(sender).__name__} ...")
    try:
        sender.send(sys.argv[1], "Test email from AI Receptionist", "If you can read this, email sending works.")
    except AppError as exc:
        print(f"FAILED: {exc.message}")
        return 1
    print(f"OK: test email sent to {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
