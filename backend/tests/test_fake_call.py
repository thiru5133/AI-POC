import struct
import wave

from app.core.config import Settings
from app.voice import fake_call, phone


def test_ulaw_decoding_matches_g711():
    pcm = fake_call.ulaw_to_pcm16(bytes([0xFF, 0x7F, 0x00, 0x80]))
    assert struct.unpack("<4h", pcm) == (0, 0, -32124, 32124)  # silence, silence (negative zero), loudest negative, loudest positive


def test_wav_is_8khz_mono_16bit(tmp_path):
    path = tmp_path / "a" / "x.wav"
    fake_call.save_wav(path, b"\xff" * 800)
    with wave.open(str(path)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 8000, 800)


def test_twiml_is_read_for_both_outcomes():
    stream = '<Response><Connect><Stream url="wss://x/ws/phone"><Parameter name="token" value="abc.def"/></Stream></Connect></Response>'
    assert fake_call.read_twiml(stream) == ("abc.def", None)
    assert fake_call.read_twiml("<Response><Say>Sorry.</Say><Hangup/></Response>") == (None, "Sorry.")


def test_the_simulated_webhook_is_signed_like_twilio_signs_it():
    s = Settings(_env_file=None, public_base_url="https://abc.example.app/", twilio_auth_token="tok")
    body, headers = fake_call.webhook_request(s, "+14155550100", "+916383135741", "CA1")
    form = dict(pair.split("=") for pair in body.split("&"))
    form = {k: v.replace("%2B", "+") for k, v in form.items()}
    assert phone.valid_twilio_signature("tok", "https://abc.example.app/api/phone/incoming", form, headers["X-Twilio-Signature"])
