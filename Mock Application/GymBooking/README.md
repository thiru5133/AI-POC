# GymBooking (mock application)

A small, self-contained class-booking system for a group of gyms in different cities and countries, used as a target
for the AI receptionist. It is the gym counterpart of [HolidayBooking](../HolidayBooking) and is built the same way:
its own backend, frontend, MCP server and `docker-compose.yml`, independent of the main application and of HolidayBooking.

| Part | Folder | Port | What it is |
|------|--------|------|-----------|
| Backend | `backend/` | 8200 | FastAPI + SQL Server REST API (gyms, class sessions, bookings, staff login) |
| Frontend | `frontend/` | 8280 | Plain HTML/JS served by nginx: member site (`/`) and staff area (`/admin.html`) |
| MCP server | `mcp-server/` | 8201 | MCP tools for AI assistants; calls the backend API |

## Run

```
cd "Mock Application/GymBooking"
cp .env.example .env     # then fill in GB_DB_PASSWORD, the two API keys and GB_SUPERADMIN_PASSWORD
./start.sh               # Git Bash / Linux / macOS
./start.ps1              # PowerShell
```

The start script picks the SQL Server for you:

1. GymBooking's own SQL Server container already running: it is left alone and used.
2. Another SQL Server already listening on `localhost:1433` (for example the main application's `db`, or HolidayBooking's):
   it is reused. GymBooking still gets its own database (`gymbooking`).
3. Otherwise GymBooking starts its own SQL Server (service `sqlserver`, host port 1435, data in the
   `gymbooking-sqlserver` volume).

Before the API starts, the backend container runs `python -m app.migrate`: it waits for SQL Server, creates the
`gymbooking` database if missing, applies the Alembic migrations (schema, seeded gyms and class types), seeds the first
superadmin and tops up the demo timetable. Always start it with the script: a bare `docker compose up` uses the
`GB_DB_HOST` from `.env` instead of the detected server.

- Member site: http://localhost:8280
- Staff area: http://localhost:8280/admin.html
- API docs: http://localhost:8200/docs
- MCP endpoint (streamable HTTP): http://localhost:8201/mcp

Reset: drop the `gymbooking` database (or `docker compose --profile local-db down -v` for the own server).

## Gyms

Migration `0002` seeds four Chennai gyms with their class types (INR per class):

| Gym (code) | Location | Classes | From |
|------------|----------|---------|------|
| FitZone Anna Nagar (`fitzone-anna-nagar`) | Anna Nagar, Chennai | yoga, hiit, spin, zumba, strength | ₹300 |
| FitZone T Nagar (`fitzone-t-nagar`) | T Nagar, Chennai | yoga, zumba, hiit, strength | ₹300 |
| FitZone Adyar (`fitzone-adyar`) | Adyar, Chennai | yoga, pilates, hiit | ₹250 |
| FitZone Velachery (`fitzone-velachery`) | Velachery, Chennai | yoga, hiit, spin, boxing | ₹300 |

The same class can cost differently per gym. Sessions are dated, so they are not in a migration: at every start
`app/seed.py` adds one session per class type and day for the next 14 days (idempotent, with fixed times and trainers
per class), so the demo never runs out of upcoming classes. Gyms, class types and sessions are edited in the staff
area: staff can add gyms, class types and sessions, change prices and capacity, and close gyms or hide sessions.

Booking rules: all times are UTC; a class can be booked up to `GB_MAX_DAYS_AHEAD` (60) days ahead and until it starts;
one member (email) holds at most one confirmed spot per session; a full class cannot be booked until someone cancels
(concurrent requests for the last spot are serialised); classes that have started cannot be cancelled. A price change
applies to future bookings only. A gym, class type or session with upcoming bookings cannot be closed, rescheduled or
removed (409), a session's capacity cannot drop below its booked spots, and anything with booking history can only be
deactivated, never deleted.

## Staff login and users

Two roles: **admin** (gyms, class types, sessions, all bookings) and **superadmin** (the same, plus user management).
Identical to HolidayBooking: the first superadmin is seeded from `GB_SUPERADMIN_EMAIL` / `GB_SUPERADMIN_PASSWORD` /
`GB_SUPERADMIN_NAME` only when none exists; sessions are an httpOnly SameSite=Strict cookie (8 hours) or a Bearer token,
stored hashed; passwords are 8-128 characters, scrypt-hashed; logins are throttled; you cannot deactivate your own
account and the last active superadmin cannot be removed or demoted.

## Security of the entry points

Every entry point is protected by an API key (fail closed). Generate keys with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

| Entry point | Protection |
|-------------|-----------|
| MCP endpoint (8201) | `X-API-Key` header must match one of `GB_MCP_API_KEYS` (comma-separated). This is the key an admin pastes into the main app's MCP page. The MCP tools are member-level only: no staff or user operations. |
| Backend API (8200) | `X-API-Key` must equal `GB_BACKEND_API_KEY`, a different, internal key used only by the MCP server and the UI proxy. `/api/admin/*` additionally needs a staff login. `/api/health` is open. Published on 127.0.0.1 only. |
| UI (8280) | Public. nginx adds the internal key when proxying `/api`, so the browser never sees a key; anyone can book and look up bookings by email. Put it behind TLS and set `GB_COOKIE_SECURE=true` before exposing it beyond a demo. |

## Connecting it to the AI receptionist

In the main application's MCP page add a server with the URL `http://host.docker.internal:8201/mcp` and the header
`X-API-Key: <one of GB_MCP_API_KEYS>`. No change to the main application is needed; HolidayBooking can be connected at
the same time (URL `...:8101/mcp`) and the receptionist will see both sets of tools.

## REST API

Member (API key only):
- `GET /api/gyms?city=&country=` and `GET /api/gyms/{code}` (with class types)
- `GET /api/sessions?date_from=&date_to=[&gym=&city=&category=]`: upcoming sessions with `spots_left` (default: next 7 days)
- `POST /api/bookings` `{session_id, member_name, member_email}`
- `GET /api/bookings?email=&status=&gym=`, `GET /api/bookings/{reference}`, `POST /api/bookings/{reference}/cancel`

Staff (API key + login):
- `POST /api/auth/login` `{email, password}`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`
- `GET/POST /api/admin/gyms`, `PATCH/DELETE /api/admin/gyms/{code}`
- `GET/POST /api/admin/gyms/{code}/class-types`, `PATCH/DELETE /api/admin/class-types/{id}`
- `GET/POST /api/admin/gyms/{code}/sessions` (`{class_type_id, starts_at, capacity, trainer}`),
  `PATCH/DELETE /api/admin/sessions/{id}`
- `GET /api/admin/bookings?gym=&status=&email=`, `POST /api/admin/bookings/{reference}/cancel`
- Superadmin only: `GET/POST /api/admin/users`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/reset-password`

Errors look like `{"error": {"code", "message"}}` (e.g. `class_full`, `already_booked`, `unknown_gym`, `has_upcoming_bookings`).

## MCP tools

`list_gyms`, `get_gym`, `list_classes`, `book_class`, `get_booking`, `list_bookings`, `cancel_booking`.
Gyms are addressed by code (see `list_gyms`); classes are booked by the `session_id` that `list_classes` returns.

For clients that launch servers as a subprocess (stdio):

```
pip install -r mcp-server/requirements.txt
GB_API_URL=http://localhost:8200 GB_BACKEND_API_KEY=... MCP_TRANSPORT=stdio python mcp-server/server.py
```

## Tests

```
cd backend && pip install -r requirements.txt && python -m pytest
cd mcp-server && python -m pytest test_auth.py
```

New schema changes go in `backend/alembic/versions/` (they run automatically on the next start).
