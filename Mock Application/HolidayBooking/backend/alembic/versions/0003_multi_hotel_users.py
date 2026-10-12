"""multiple hotels (with their own room types, prices and rooms), users and sessions; seeds the hotels

The single-hotel schema from 0001/0002 becomes the first hotel ("holiday-colombo"): its categories, rooms and any
bookings are carried over, then the other hotels are seeded. Users are NOT seeded here (passwords must not live in
source control): the superadmin is created from HB_SUPERADMIN_* by `python -m app.migrate` (see app/seed.py).

Revision ID: 0003
Revises: 0002
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"

# code, name, city, country, address, description, stars, room types
# room type: code, name, description, price per night (USD), max guests, first room number, how many rooms
HOTELS = [
    (
        "holiday-colombo", "Holiday Colombo Grand", "Colombo", "Sri Lanka", "1 Galle Face Green, Colombo 03",
        "Landmark seafront hotel in the heart of the capital.", 5,
        [
            ("standard", "Standard", "Cosy room with a queen bed and city view.", 120, 2, 101, 8),
            ("deluxe", "Deluxe", "Spacious room with a king bed and a balcony.", 200, 3, 201, 6),
            ("family", "Family", "Two bedrooms with a living area, ideal for families.", 280, 5, 301, 4),
            ("suite", "Suite", "Separate lounge, king bed and a panoramic view.", 450, 4, 401, 3),
            ("presidential", "Presidential", "Top-floor suite with private terrace and butler service.", 900, 6, 501, 1),
        ],
    ),
    (
        "holiday-kandy", "Holiday Kandy Hills", "Kandy", "Sri Lanka", "12 Lake Road, Kandy",
        "Hill-country retreat overlooking the lake and the Temple of the Tooth.", 4,
        [
            ("standard", "Standard", "Comfortable room with a garden view.", 85, 2, 101, 6),
            ("deluxe", "Deluxe", "Large room with a lake-view balcony.", 140, 3, 201, 4),
            ("suite", "Suite", "Two-room suite with a living area and lake view.", 260, 4, 301, 2),
        ],
    ),
    (
        "holiday-galle", "Holiday Galle Fort", "Galle", "Sri Lanka", "8 Church Street, Galle Fort",
        "Boutique hotel inside the historic Dutch fort, steps from the beach.", 4,
        [
            ("standard", "Standard", "Quiet room with a courtyard garden view.", 95, 2, 101, 8),
            ("ocean", "Ocean View", "Bright room facing the Indian Ocean.", 170, 3, 201, 6),
            ("villa", "Pool Villa", "Private villa with its own plunge pool.", 340, 5, 301, 3),
        ],
    ),
    (
        "holiday-dubai", "Holiday Dubai Marina", "Dubai", "United Arab Emirates", "Marina Walk, Dubai Marina",
        "Skyline hotel on the marina promenade with rooftop pool.", 5,
        [
            ("standard", "Standard", "Modern room with a city view.", 180, 2, 101, 10),
            ("deluxe", "Deluxe", "Marina-view room with a balcony.", 260, 3, 201, 8),
            ("family", "Family", "Connecting rooms with two bathrooms.", 380, 5, 301, 5),
            ("suite", "Suite", "Corner suite with a lounge and sea view.", 620, 4, 401, 4),
            ("royal", "Royal Suite", "Two-floor suite with private lift and majlis.", 1400, 6, 501, 2),
        ],
    ),
    (
        "holiday-singapore", "Holiday Singapore Bay", "Singapore", "Singapore", "10 Bayfront Avenue, Marina Bay",
        "Waterfront tower next to Gardens by the Bay.", 5,
        [
            ("standard", "Standard", "Compact, elegant room with a city view.", 210, 2, 101, 10),
            ("deluxe", "Deluxe", "Bay-view room with a work desk.", 310, 3, 201, 6),
            ("suite", "Suite", "Sky suite with a lounge and skyline view.", 560, 4, 301, 3),
        ],
    ),
    (
        "holiday-london", "Holiday London Kensington", "London", "United Kingdom", "25 Cromwell Road, Kensington",
        "Victorian townhouse hotel near the museums and Hyde Park.", 4,
        [
            ("standard", "Standard", "Classic room with a queen bed.", 190, 2, 101, 12),
            ("deluxe", "Deluxe", "Larger room overlooking the garden square.", 270, 3, 201, 8),
            ("family", "Family", "Two-room family apartment.", 360, 5, 301, 4),
            ("suite", "Suite", "Suite with a separate sitting room.", 540, 4, 401, 2),
        ],
    ),
]


def upgrade() -> None:
    # --- set the single-hotel tables aside (indexes first: SQLite index names are schema-global) ---
    op.drop_index("ix_bookings_guest_email", table_name="bookings")
    op.drop_index("ix_bookings_room_dates", table_name="bookings")
    op.rename_table("bookings", "bookings_legacy")
    op.rename_table("rooms", "rooms_legacy")
    op.rename_table("room_categories", "room_categories_legacy")

    # --- new schema ---
    op.create_table(
        "hotels",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("country", sa.String(80), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("stars", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "room_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hotel_code", sa.String(40), sa.ForeignKey("hotels.code"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("price_per_night", sa.Integer, nullable=False),
        sa.Column("max_guests", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.UniqueConstraint("hotel_code", "code", name="uq_room_types_hotel_code"),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hotel_code", sa.String(40), sa.ForeignKey("hotels.code"), nullable=False),
        sa.Column("room_type_id", sa.Integer, sa.ForeignKey("room_types.id"), nullable=False),
        sa.Column("number", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.UniqueConstraint("hotel_code", "number", name="uq_rooms_hotel_number"),
    )
    op.create_table(
        "bookings",
        sa.Column("reference", sa.String(20), primary_key=True),
        sa.Column("hotel_code", sa.String(40), sa.ForeignKey("hotels.code"), nullable=False),
        sa.Column("room_id", sa.Integer, sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("room_number", sa.String(10), nullable=False),
        sa.Column("category_code", sa.String(30), nullable=False),
        sa.Column("guest_name", sa.String(120), nullable=False),
        sa.Column("guest_email", sa.String(320), nullable=False),
        sa.Column("guests", sa.Integer, nullable=False),
        sa.Column("check_in", sa.Date, nullable=False),
        sa.Column("check_out", sa.Date, nullable=False),
        sa.Column("nights", sa.Integer, nullable=False),
        sa.Column("total_price", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("cancelled_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_bookings_guest_email", "bookings", ["guest_email"])
    op.create_index("ix_bookings_room_dates", "bookings", ["room_id", "check_in", "check_out"])
    op.create_index("ix_bookings_hotel", "bookings", ["hotel_code"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # --- the old single hotel becomes the first hotel, keeping its rooms and bookings ---
    first = HOTELS[0]
    now = datetime.utcnow().replace(microsecond=0)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO hotels (code, name, city, country, address, description, stars, active, created_at) "
            "VALUES (:c, :n, :ci, :co, :a, :d, :s, 1, :t)"
        ),
        {"c": first[0], "n": first[1], "ci": first[2], "co": first[3], "a": first[4], "d": first[5], "s": first[6], "t": now},
    )
    conn.execute(
        sa.text(
            "INSERT INTO room_types (hotel_code, code, name, description, price_per_night, max_guests, active) "
            "SELECT :h, code, name, description, price_per_night, max_guests, 1 FROM room_categories_legacy"
        ),
        {"h": first[0]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO rooms (hotel_code, room_type_id, number, active) "
            "SELECT :h, t.id, CAST(r.number AS VARCHAR(10)), 1 FROM rooms_legacy r "
            "JOIN room_types t ON t.hotel_code = :h AND t.code = r.category_code"
        ),
        {"h": first[0]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO bookings (reference, hotel_code, room_id, room_number, category_code, guest_name, guest_email, "
            "guests, check_in, check_out, nights, total_price, status, created_at, cancelled_at) "
            "SELECT b.reference, :h, r.id, r.number, b.category_code, b.guest_name, b.guest_email, b.guests, "
            "b.check_in, b.check_out, b.nights, b.total_price, b.status, b.created_at, b.cancelled_at "
            "FROM bookings_legacy b JOIN rooms r ON r.hotel_code = :h AND r.number = CAST(b.room_number AS VARCHAR(10))"
        ),
        {"h": first[0]},
    )
    op.drop_table("bookings_legacy")
    op.drop_table("rooms_legacy")
    op.drop_table("room_categories_legacy")

    # --- seed every hotel (idempotent: whatever the first hotel already has is left alone) ---
    for code, name, city, country, address, description, stars, types in HOTELS:
        if conn.execute(sa.text("SELECT 1 FROM hotels WHERE code = :c"), {"c": code}).first() is None:
            conn.execute(
                sa.text(
                    "INSERT INTO hotels (code, name, city, country, address, description, stars, active, created_at) "
                    "VALUES (:c, :n, :ci, :co, :a, :d, :s, 1, :t)"
                ),
                {"c": code, "n": name, "ci": city, "co": country, "a": address, "d": description, "s": stars, "t": now},
            )
        for type_code, type_name, type_desc, price, max_guests, first_number, count in types:
            row = conn.execute(
                sa.text("SELECT id FROM room_types WHERE hotel_code = :h AND code = :c"), {"h": code, "c": type_code}
            ).first()
            if row is None:
                conn.execute(
                    sa.text(
                        "INSERT INTO room_types (hotel_code, code, name, description, price_per_night, max_guests, active) "
                        "VALUES (:h, :c, :n, :d, :p, :g, 1)"
                    ),
                    {"h": code, "c": type_code, "n": type_name, "d": type_desc, "p": price, "g": max_guests},
                )
                row = conn.execute(
                    sa.text("SELECT id FROM room_types WHERE hotel_code = :h AND code = :c"), {"h": code, "c": type_code}
                ).first()
            for number in range(first_number, first_number + count):
                exists = conn.execute(
                    sa.text("SELECT 1 FROM rooms WHERE hotel_code = :h AND number = :n"), {"h": code, "n": str(number)}
                ).first()
                if exists is None:
                    conn.execute(
                        sa.text("INSERT INTO rooms (hotel_code, room_type_id, number, active) VALUES (:h, :t, :n, 1)"),
                        {"h": code, "t": row[0], "n": str(number)},
                    )


def downgrade() -> None:
    raise RuntimeError("0003 merges several hotels into one schema and cannot be reversed; restore a backup instead")
