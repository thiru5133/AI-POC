import pytest

import server

HOTELS = [
    {"code": "holiday-singapore", "name": "Holiday Singapore Bay"},
    {"code": "holiday-colombo", "name": "Holiday Colombo Grand"},
    {"code": "holiday-kandy", "name": "Holiday Kandy Hills"},
]


@pytest.fixture(autouse=True)
def hotels(monkeypatch):
    monkeypatch.setattr(server, "_call", lambda method, path, **kw: HOTELS)


@pytest.mark.parametrize(
    "said",
    ["holiday-singapore", "Holiday Singapore Bay", "Holiday Sing Bay", "holiday sing bay", "holiday-sing-bay", "holiday singapor", "Kandy"],
)
def test_resolves_to_the_real_code(said):
    code, error = server._resolve_hotel(said)
    assert error is None
    assert code in {"holiday-singapore", "holiday-kandy"}


def test_unknown_hotel_lists_the_valid_ones():
    code, error = server._resolve_hotel("Paris Palace")
    assert error["error"]["code"] == "unknown_hotel"
    assert "holiday-singapore" in error["error"]["message"]
