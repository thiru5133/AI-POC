"""Checks that real phone calls can reach this server, and (with --apply) points a Twilio number at it.

    docker compose exec backend python -m app.voice.phone_setup --number +14155550100
    docker compose exec backend python -m app.voice.phone_setup --number +14155550100 --apply

Without --apply nothing is changed on Twilio: every step is a read.
"""

import argparse
import sys

import httpx

from app.core.config import Settings, get_settings
from app.voice.phone import normalize_phone

TWILIO = "https://api.twilio.com/2010-04-01"
INCOMING_PATH = "/api/phone/incoming"

Result = tuple[bool, str]


def check_settings(s: Settings) -> list[Result]:
    results = [
        (s.public_base_url.startswith("https://"), "PUBLIC_BASE_URL is an https URL (Twilio only calls https; in development use ngrok)"),
        (bool(s.twilio_account_sid and s.twilio_auth_token), "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are set"),
        (bool(s.deepgram_api_key), "DEEPGRAM_API_KEY is set (speech-to-text and text-to-speech)"),
        (s.llm_provider == "fake" or bool(s.groq_api_key or s.anthropic_api_key or s.llm_api_key), "an LLM key is set"),
        (s.jwt_secret != "dev-insecure-change-me", "JWT_SECRET is not the default (it signs the call's audio-stream token)"),
    ]
    return results


def check_server_reachable(s: Settings, http: httpx.Client) -> Result:
    url = s.public_base_url.rstrip("/") + "/health"
    try:
        resp = http.get(url)
    except httpx.HTTPError as exc:
        return False, f"{url} is not reachable from the internet ({type(exc).__name__}): is the tunnel running?"
    ok = resp.status_code == 200
    return ok, f"{url} answers" if ok else f"{url} answered {resp.status_code}: the tunnel is up but not pointing at this backend"


def check_twilio(s: Settings, http: httpx.Client, number: str, apply: bool) -> list[Result]:
    auth = (s.twilio_account_sid, s.twilio_auth_token)
    account = http.get(f"{TWILIO}/Accounts/{s.twilio_account_sid}.json", auth=auth)
    if account.status_code != 200:
        return [(False, f"Twilio rejected the credentials ({account.status_code}): check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")]
    info = account.json()
    results: list[Result] = [(True, f"Twilio account is {info.get('status')} ({info.get('type')})")]
    if info.get("type") == "Trial":
        results.append((True, "Trial account: it can only call numbers you verified in Twilio, and callers hear a trial message first"))

    found = http.get(f"{TWILIO}/Accounts/{s.twilio_account_sid}/IncomingPhoneNumbers.json", params={"PhoneNumber": number}, auth=auth)
    numbers = found.json().get("incoming_phone_numbers", []) if found.status_code == 200 else []
    if not numbers:
        return results + [(False, f"{number} is not a number on this Twilio account")]
    entry = numbers[0]
    results.append((bool(entry.get("capabilities", {}).get("voice")), f"{number} can take voice calls"))

    expected = s.public_base_url.rstrip("/") + INCOMING_PATH
    current = entry.get("voice_url") or ""
    if current == expected and (entry.get("voice_method") or "").upper() == "POST":
        return results + [(True, f"{number} sends calls to {expected}")]
    if not apply:
        return results + [(False, f"{number} sends calls to {current or 'nothing'}, not {expected} (run again with --apply to fix it)")]
    update = http.post(
        f"{TWILIO}/Accounts/{s.twilio_account_sid}/IncomingPhoneNumbers/{entry['sid']}.json",
        data={"VoiceUrl": expected, "VoiceMethod": "POST"},
        auth=auth,
    )
    ok = update.status_code == 200
    return results + [(ok, f"{number} now sends calls to {expected}" if ok else f"Twilio would not update the number ({update.status_code})")]


def check_sms_sender(s: Settings, http: httpx.Client) -> Result | None:
    """Alerts and confirmations are texted from TWILIO_SMS_FROM, which must be a number on this Twilio account.
    None when no sender is set (texts are then only logged)."""
    sender = normalize_phone(s.twilio_sms_from)
    if sender is None:
        return None
    auth = (s.twilio_account_sid, s.twilio_auth_token)
    found = http.get(f"{TWILIO}/Accounts/{s.twilio_account_sid}/IncomingPhoneNumbers.json", params={"PhoneNumber": sender}, auth=auth)
    numbers = found.json().get("incoming_phone_numbers", []) if found.status_code == 200 else []
    if not numbers:
        return False, f"TWILIO_SMS_FROM {sender} is not a number on this Twilio account: texts to the business (and callers) will fail"
    if not numbers[0].get("capabilities", {}).get("sms", True):
        return False, f"TWILIO_SMS_FROM {sender} cannot send SMS"
    return True, f"TWILIO_SMS_FROM {sender} can send texts"


def check_business(number: str) -> Result:
    """Whether a business has saved this number on the Phone page (otherwise callers hear 'not in service')."""
    from app.database.session import get_session_factory
    from app.models import PhoneNumber
    from sqlalchemy import select

    try:
        with get_session_factory()() as session:
            taken = session.scalars(select(PhoneNumber).where(PhoneNumber.number == number)).first() is not None
    except Exception as exc:
        return False, f"could not read the database ({type(exc).__name__})"
    return taken, "a business has saved this number on its Phone page" if taken else "no business has saved this number yet: add it on the Phone page"


def run(argv: list[str] | None = None, settings: Settings | None = None, http: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--number", required=True, help="the Twilio number in E.164 form, e.g. +14155550100")
    parser.add_argument("--apply", action="store_true", help="point the number's voice webhook at this server")
    parser.add_argument("--skip-business", action="store_true", help="do not look for the number in the database")
    args = parser.parse_args(argv)
    number = normalize_phone(args.number)
    if number is None:
        print("The number must include its country code, for example +14155550100")
        return 2

    s = settings or get_settings()
    client = http or httpx.Client(timeout=15)
    results = check_settings(s)
    if all(ok for ok, _ in results[:2]):
        results.append(check_server_reachable(s, client))
        results += check_twilio(s, client, number, args.apply)
        sender = check_sms_sender(s, client)
        if sender is not None:
            results.append(sender)
    if not args.skip_business:
        results.append(check_business(number))
    for ok, message in results:
        print(f"[{'ok' if ok else 'FAIL'}] {message}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(run())
