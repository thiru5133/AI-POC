import server


def test_gives_the_number_the_backend_reports(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "_call", lambda method, path, **kw: seen.append((method, path)) or {"reservations_phone": "+17692630020"})
    assert server.get_contact_info() == {"reservations_phone": "+17692630020"}
    assert seen == [("GET", "/api/contact")]


def test_says_so_when_no_number_is_configured(monkeypatch):
    monkeypatch.setattr(server, "_call", lambda *a, **k: {"reservations_phone": None})
    assert server.get_contact_info()["error"]["code"] == "not_configured"


def test_passes_a_backend_error_through(monkeypatch):
    error = {"error": {"code": "backend_unreachable", "message": "down"}}
    monkeypatch.setattr(server, "_call", lambda *a, **k: error)
    assert server.get_contact_info() == error
