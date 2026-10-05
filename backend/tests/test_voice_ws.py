def test_voice_ws_greets_and_answers(client, tts):
    cid = client.post("/api/conversations", json={}).json()["id"]

    with client.websocket_connect(f"/ws/voice/{cid}") as ws:
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


def test_voice_ws_unknown_conversation_sends_error(client):
    with client.websocket_connect("/ws/voice/does-not-exist") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "not_found"
