import httpx

from app.core.config import Settings
from app.voice import phone_setup

NUMBER = "+14155550100"
URL = "https://abc.example.app"


def settings(**over) -> Settings:
    base = dict(public_base_url=URL, twilio_account_sid="AC1", twilio_auth_token="tok", deepgram_api_key="dg",
                groq_api_key="g", jwt_secret="a-real-secret")
    return Settings(_env_file=None, **{**base, **over})


def twilio_http(voice_url="", account_type="Full", account_status=200, owns_number=True, health=200, voice=True):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content.decode()))
        path = request.url.path
        if path == "/health":
            return httpx.Response(health, json={"status": "ok"})
        if path.endswith("/Accounts/AC1.json"):
            return httpx.Response(account_status, json={"status": "active", "type": account_type})
        if path.endswith("/IncomingPhoneNumbers.json"):
            numbers = [{"sid": "PN1", "voice_url": voice_url, "voice_method": "POST", "capabilities": {"voice": voice}}] if owns_number else []
            return httpx.Response(200, json={"incoming_phone_numbers": numbers})
        if path.endswith("/IncomingPhoneNumbers/PN1.json"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def run(http, apply=False, **over):
    args = ["--number", NUMBER, "--skip-business"] + (["--apply"] if apply else [])
    return phone_setup.run(args, settings(**over), http)


def test_everything_in_place_passes_and_changes_nothing(capsys):
    http, calls = twilio_http(voice_url=URL + "/api/phone/incoming")
    assert run(http) == 0
    assert "FAIL" not in capsys.readouterr().out
    assert not [c for c in calls if c[0] == "POST"]


def test_wrong_webhook_is_reported_and_only_fixed_with_apply(capsys):
    http, calls = twilio_http(voice_url="https://old.example/voice")
    assert run(http) == 1
    out = capsys.readouterr().out
    assert "not https://abc.example.app/api/phone/incoming" in out and "--apply" in out
    assert not [c for c in calls if c[0] == "POST"]  # a plain check never changes Twilio

    http, calls = twilio_http(voice_url="https://old.example/voice")
    assert run(http, apply=True) == 0
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and "VoiceUrl=https%3A%2F%2Fabc.example.app%2Fapi%2Fphone%2Fincoming" in posts[0][2]
    assert "VoiceMethod=POST" in posts[0][2]


def test_bad_credentials_unknown_number_and_unreachable_server(capsys):
    assert run(twilio_http(account_status=401)[0]) == 1
    assert "rejected the credentials" in capsys.readouterr().out
    assert run(twilio_http(owns_number=False)[0]) == 1
    assert "not a number on this Twilio account" in capsys.readouterr().out
    assert run(twilio_http(health=502)[0]) == 1
    assert "tunnel is up but not pointing at this backend" in capsys.readouterr().out
    assert run(twilio_http(voice=False, voice_url=URL + "/api/phone/incoming")[0]) == 1
    assert "can take voice calls" in capsys.readouterr().out.split("[FAIL]")[1]


def test_missing_configuration_is_listed_before_anything_is_called(capsys):
    http, calls = twilio_http()
    assert run(http, public_base_url="http://localhost:8000", twilio_auth_token="", deepgram_api_key="") == 1
    out = capsys.readouterr().out
    assert out.count("[FAIL]") == 3 and calls == []  # nothing is contacted until the basics are set


def test_trial_accounts_get_a_heads_up(capsys):
    assert run(twilio_http(voice_url=URL + "/api/phone/incoming", account_type="Trial")[0]) == 0
    assert "Trial account" in capsys.readouterr().out


def test_number_must_have_a_country_code(capsys):
    assert phone_setup.run(["--number", "4155550100"], settings(), twilio_http()[0]) == 2
