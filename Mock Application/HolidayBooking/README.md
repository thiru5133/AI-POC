# HolidayBooking (mock application)

A small, self-contained booking system for a group of hotels in different cities and countries, used as a target for
the AI receptionist. It is independent of the main application: its own backend, frontend, MCP server and
`docker-compose.yml`.

| Part | Folder | Port | What it is |
|------|--------|------|-----------|
| Backend | `backend/` | 8100 | FastAPI + SQL Server REST API (hotels, availability, bookings, staff login) |
| Frontend | `frontend/` | 8180 | Plain HTML/JS served by nginx: guest site (`/`) and staff area (`/admin.html`) |
| MCP server | `mcp-server/` | 8101 | MCP tools for AI assistants; calls the backend API |

## Run

```
cd "Mock Application/HolidayBooking"
./start.sh        # Git Bash / Linux / macOS
./start.ps1       # PowerShell
```

The start script picks the SQL Server for you:

1. HolidayBooking's own SQL Server container already running: it is left alone and used.
2. Another SQL Server already listening on `localhost:1433` (for example the main application's `db`): it is reused.
3. Otherwise HolidayBooking starts its own SQL Server (service `sqlserver`, host port 1434, data in the
   `holidaybooking-sqlserver` volume).

Before the API starts, the backend container runs `python -m app.migrate`, which waits until SQL Server accepts
connections, checks that the `holidaybooking` database exists (creating it if not), applies the Alembic migrations
(schema and the seeded hotels, rooms) and seeds the first superadmin. The log shows each step. Data always lives in
SQL Server, so it survives restarts and rebuilds. Always start it with the script: a bare `docker compose up` uses the
`HB_DB_HOST` from `.env` instead of the detected server.

- Guest site: http://localhost:8180
- Staff area: http://localhost:8180/admin.html
- API docs: http://localhost:8100/docs
- MCP endpoint (streamable HTTP): http://localhost:8101/mcp

Reset: drop the `holidaybooking` database (or `docker compose --profile local-db down -v` for the own server).

## Hotels

Migration `0003` seeds six hotels, each with its own room types, prices and rooms (USD per night):

| Hotel (code) | Location | Rooms | From |
|--------------|----------|-------|------|
| Holiday Colombo Grand (`holiday-colombo`) | Colombo, Sri Lanka | 22 | $120 |
| Holiday Kandy Hills (`holiday-kandy`) | Kandy, Sri Lanka | 12 | $85 |
| Holiday Galle Fort (`holiday-galle`) | Galle, Sri Lanka | 17 | $95 |
| Holiday Dubai Marina (`holiday-dubai`) | Dubai, United Arab Emirates | 29 | $180 |
| Holiday Singapore Bay (`holiday-singapore`) | Singapore | 19 | $210 |
| Holiday London Kensington (`holiday-london`) | London, United Kingdom | 26 | $190 |

The same room type name can cost differently per hotel. The hotels, room types and prices are edited in the staff
area, not in code: staff can add hotels, room types and rooms, change prices, and close hotels or take rooms out of
service. Upgrading from the earlier single-hotel version keeps its rooms and bookings (they become Holiday Colombo
Grand).

Booking rules: stays are 1-`HB_MAX_NIGHTS` (30) nights, check-in cannot be in the past, the check-out day is free for
the next guest, a room of the chosen type is assigned automatically, and started stays cannot be cancelled. A price
change applies to future bookings only. A hotel, room type or room with upcoming bookings cannot be closed, moved or
removed (409), and anything with booking history can only be deactivated, never deleted.

## Staff login and users

Two roles: **admin** (hotels, room types, rooms, all bookings) and **superadmin** (the same, plus user management).

- **Seeding:** the first superadmin is created at startup from `HB_SUPERADMIN_EMAIL` / `HB_SUPERADMIN_PASSWORD` /
  `HB_SUPERADMIN_NAME` in `.env`, only when no superadmin exists yet (a restart never resets a password). Change that
  password after the first login (Staff area, "Change password"). Only this one account is seeded.
- **Sessions:** login sets an httpOnly, SameSite=Strict cookie (8 hours); API clients can use the returned token as
  `Authorization: Bearer`. Sessions are stored hashed and revoked on logout, password change/reset and deactivation.
- **Passwords:** 8-128 characters, scrypt-hashed. Logins are throttled (5 failures per 15 minutes per email and client).
- **Safeguards:** you cannot deactivate or change the role of your own account, and the last active superadmin cannot
  be removed or demoted.

## Security of the entry points

Every entry point is protected by an API key (fail closed: with no key configured, requests are refused and the MCP
server will not start). Generate keys with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

| Entry point | Protection |
|-------------|-----------|
| MCP endpoint (8101) | `X-API-Key` header must match one of `HB_MCP_API_KEYS` (comma-separated: rotate keys or issue one per client). This is the key an admin pastes into the main app's MCP page as an `X-API-Key` header. The MCP tools are guest-level only: no staff or user operations. |
| Backend API (8100) | `X-API-Key` must equal `HB_BACKEND_API_KEY`, a different, internal key used only by the MCP server and the UI proxy. `/api/admin/*` additionally needs a staff login. `/api/health` is open for the healthcheck. The port is published on 127.0.0.1 only. |
| UI (8180) | Public. nginx adds the internal key when proxying `/api`, so the browser never sees a key; guest endpoints need no login (anyone can book, and look up bookings by email). Staff pages need the staff login. Put it behind TLS and set `HB_COOKIE_SECURE=true` before exposing it beyond a demo. |

Not included: rate limiting of guest endpoints, TLS, per-key audit logging.

## Configuration

All settings live in this folder's own `.env` (copy `.env.example`; docker compose reads it automatically): host
ports, the database connection (`HB_DB_*`), API keys, the seeded superadmin, `HB_MAX_NIGHTS` and the MCP transport /
backend URL. It is separate from the main application's `.env`, and `.env` is git-ignored.

## REST API

Guest (API key only):
- `GET /api/hotels?city=&country=` and `GET /api/hotels/{code}` (with room types)
- `GET /api/availability?check_in=&check_out=[&hotel=&city=&country=&category=]` (per hotel and room type)
- `POST /api/bookings` `{hotel, category, guest_name, guest_email, check_in, check_out, guests}`
- `GET /api/bookings?email=&status=&hotel=`, `GET /api/bookings/{reference}`, `POST /api/bookings/{reference}/cancel`

Staff (API key + login):
- `POST /api/auth/login` `{email, password}`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`
- `GET/POST /api/admin/hotels`, `PATCH/DELETE /api/admin/hotels/{code}`
- `GET/POST /api/admin/hotels/{code}/room-types`, `PATCH/DELETE /api/admin/room-types/{id}`
- `GET/POST /api/admin/hotels/{code}/rooms` (`{room_type_id, numbers[]}` or `{room_type_id, start, count}`),
  `PATCH/DELETE /api/admin/rooms/{id}`
- `GET /api/admin/bookings?hotel=&status=&email=`, `POST /api/admin/bookings/{reference}/cancel`
- Superadmin only: `GET/POST /api/admin/users`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/reset-password`

Errors look like `{"error": {"code", "message"}}` (e.g. `sold_out`, `unknown_hotel`, `has_upcoming_bookings`).

## MCP tools

`list_hotels`, `get_hotel`, `check_availability`, `book_room`, `get_booking`, `list_bookings`, `cancel_booking`,
`get_contact_info` (the reservations phone number, set with `HB_RESERVATIONS_PHONE`; also shown in the guest page's header).
Hotels are addressed by code (see `list_hotels`); availability can be searched by hotel, city or country.

Connect an MCP client to `http://localhost:8101/mcp` with the `X-API-Key` header. For clients that launch servers as a
subprocess (stdio):

```
pip install -r mcp-server/requirements.txt
HB_API_URL=http://localhost:8100 HB_BACKEND_API_KEY=... MCP_TRANSPORT=stdio python mcp-server/server.py
```

## Tests

```
cd backend && pip install -r requirements.txt && python -m pytest
cd mcp-server && python -m pytest test_auth.py
```

New schema changes go in `backend/alembic/versions/` (they run automatically on the next start).
