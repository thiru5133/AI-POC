import server


def test_a_date_with_a_time_keeps_only_the_day():
    assert server._day("2026-10-24T20:00:00") == "2026-10-24"
    assert server._day(" 2026-10-25 12:00 ") == "2026-10-25"
    assert server._day("2026-10-24") == "2026-10-24"
    assert server._day("tomorrow") == "tomorrow"  # unknown text is left for the backend to reject


def test_availability_and_booking_send_plain_dates(monkeypatch):
    sent = []
    monkeypatch.setattr(server, "_resolve_hotel", lambda text: (text, None))
    monkeypatch.setattr(server, "_call", lambda method, path, **kw: sent.append(kw) or {})
    server.check_availability("2026-10-24T20:00:00", "2026-10-25T12:00:00")
    server.book_room("h", "standard", "Peter", "p@x.com", "2026-10-24T20:00:00", "2026-10-25T12:00:00", 2)
    assert sent[0]["params"] == {"check_in": "2026-10-24", "check_out": "2026-10-25"}
    assert sent[1]["json"]["check_in"] == "2026-10-24" and sent[1]["json"]["check_out"] == "2026-10-25"
