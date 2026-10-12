def test_voice_ws_greets_and_answers(client, tts, demo_admin):
    client.headers.update(demo_admin["headers"])
    cid = client.post("/api/conversations", json={}).json()["id"]

    with client.websocket_connect(f"/ws/voice/{cid}?token={demo_admin['token']}") as ws:
        # greeting: text event, audio frame, audio_end
        assert ws.receive_json() == {"type": "assistant.text", "text": "Welcome to Demo Hotel. How can I help you?"}
        assert ws.receive_bytes().startswith(b"AUDIO:Welcome")
        assert ws.receive_json()["type"] == "assistant.audio_end"

        ws.send_bytes(b"What time is check-in?")  # FakeSTT: bytes are the utterance text
        events = []
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                events.append(("audio", msg["bytes"]))
                continue
            import json

            payload = json.loads(msg["text"])
            events.append((payload["type"], payload))
            if payload["type"] == "assistant.audio_end":
                break

    kinds = [k for k, _ in events]
    assert "transcript.final" in kinds
    assert kinds.count("audio") == 2  # two sentences -> two TTS frames
    assert tts.spoken[-2:] == ["Check-in starts at 2 PM.", "Anything else?"]

    convo = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in convo["messages"]][-2:] == ["user", "assistant"]


def test_voice_ws_unknown_conversation_sends_error(client, demo_admin):
    with client.websocket_connect(f"/ws/voice/does-not-exist?token={demo_admin['token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "not_found"


def test_voice_ws_rejects_missing_or_foreign_credentials(client, session_factory, demo_admin):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    client.headers.update(demo_admin["headers"])
    cid = client.post("/api/conversations", json={}).json()["id"]

    for url in (f"/ws/voice/{cid}", f"/ws/voice/{cid}?token=garbage", f"/ws/voice/{cid}?tenantId=anything"):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(url):
            pass

    # another organization's admin cannot attach to this conversation: it is simply not found for them
    from .conftest import make_admin, make_tenant

    other = make_admin(session_factory, make_tenant(session_factory, "Other Org"), "o@example.com")
    with client.websocket_connect(f"/ws/voice/{cid}?token={other['token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "not_found"
