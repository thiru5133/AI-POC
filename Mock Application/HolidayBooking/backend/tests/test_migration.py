"""The single-hotel -> multi-hotel migration keeps existing rooms and bookings."""

from datetime import date, datetime

from sqlalchemy import text

from app import db, migrate


def test_existing_single_hotel_data_becomes_the_first_hotel(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")
    db.reset_engine()
    migrate.upgrade("0002")  # the schema as it was before multiple hotels, seeded with the one hotel's 22 rooms

    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bookings (reference, room_number, category_code, guest_name, guest_email, guests, check_in, "
                "check_out, nights, total_price, status, created_at) VALUES "
                "('HB-LEGACY1', 401, 'suite', 'Old Guest', 'old@example.com', 2, :ci, :co, 2, 900, 'confirmed', :now), "
                "('HB-LEGACY2', 101, 'standard', 'Gone Guest', 'gone@example.com', 1, :ci, :co, 2, 240, 'cancelled', :now)"
            ),
            {"ci": date(2031, 1, 10), "co": date(2031, 1, 12), "now": datetime(2030, 1, 1)},
        )

    migrate.upgrade()  # head

    with engine.connect() as conn:
        hotels = [r[0] for r in conn.execute(text("SELECT code FROM hotels ORDER BY code"))]
        assert len(hotels) == 6 and "holiday-colombo" in hotels
        rooms = conn.execute(text("SELECT COUNT(*) FROM rooms WHERE hotel_code = 'holiday-colombo'")).scalar()
        assert rooms == 22  # nothing duplicated by the seeding that follows the conversion
        rows = conn.execute(
            text(
                "SELECT b.reference, b.hotel_code, b.room_number, b.category_code, b.total_price, b.status, r.number, t.price_per_night "
                "FROM bookings b JOIN rooms r ON r.id = b.room_id JOIN room_types t ON t.id = r.room_type_id ORDER BY b.reference"
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("HB-LEGACY1", "holiday-colombo", "401", "suite", 900, "confirmed", "401", 450),
        ("HB-LEGACY2", "holiday-colombo", "101", "standard", 240, "cancelled", "101", 120),
    ]
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert not {t for t in tables if t.endswith("_legacy")} and {"users", "sessions", "hotels", "room_types"} <= tables
