# AI Universal Receptionist — Architecture (Phase 0)

One reusable **Conversation Engine** + configurable **Domain Profiles** + domain-specific **tools/APIs**. Hotel is only the first profile.

```
React + TS (Voice UI)  ──REST / WebSocket──>  FastAPI (api/)
                                                 │
                              ┌──────────────────┴─────────────────┐
                              ▼                                    ▼
                      ConversationService                  VoiceSession (voice/)
                  (tenant-scoped persistence)         STTProvider · TTSProvider · VoiceProvider
                              │
                              ▼
                      ConversationEngine  (pure: profile + history + user text -> streamed reply)
                    ┌─────────┼───────────────┐
                    ▼         ▼               ▼
              LLMProvider  DomainProfile   ToolRegistry ──> domain APIs (Hotel API in Phase 3)
              (anthropic|fake)  (config)     (profile.enabledTools)
                              │
              Repositories (always tenant-scoped) ──> SQL Server
```

## Rules enforced in code
- **Engine is domain-neutral**: prompt, context and tool loop read only the profile. `tests/test_domain_and_prompt.py::test_engine_code_has_no_hotel_terminology` fails the build if hotel words appear in `conversation/`, `ai/`, `tools/`.
- **LLM never touches the DB**: it can only request registered tools; handlers (backend code) do the work. Tool errors are returned to the LLM as `is_error` results.
- **Tenant isolation**: `TenantScopedRepository` cannot be built without a tenant and adds `tenant_id` to every query/insert. Every tenant table has an indexed `tenant_id`.
- **Replaceable providers**: `LLMProvider`, `STTProvider`, `TTSProvider`, `VoiceProvider` are interfaces; Deepgram/Anthropic are implementations.

## Layout
`backend/app/`: `api/` routes+schemas+deps · `conversation/` engine, context, prompt, chunker, service · `ai/` providers · `domain/` profile model + `profiles/hotel.json` · `tools/` registry · `workflows/` (booking state machine, Phase 4) · `voice/` interfaces, Deepgram, fakes, WS session · `models/`, `repositories/`, `database/` (SQLAlchemy + Alembic) · `core/` settings, JSON logging, error envelope · `auth/` security helpers (argon2, JWT, refresh tokens), login throttle and `AuthService` · `tenants/` (stub).
`frontend/src/`: `features/conversation/` UI · `voice/` `VoiceClient` interface, `BrowserDeepgramClient`, `useVoiceSession` · `services/` typed API client · `types/`.

Deviation from the suggested layout: no `agents/` (single engine), added `workflows/` and `core/`.

## Data model (SQL Server)
`tenants`, `domain_profiles(tenant_id, config JSON)`, `conversations(tenant_id, domain_profile_id, status, outcome, context JSON)`, `messages(tenant_id, conversation_id, role, content, intent)`, `tool_calls(tenant_id, …)` (populated in Phase 5). Bookings/users/usage land in their phases.

## ConversationContext
`session_id, tenant_id, domain_profile_id, intent, entities{} (generic slots keyed by profile requiredFields), caller{name,phone,email}, workflow_state, last_action`. Memory = persisted message history (last 40) + this context, reloaded each turn.

## API
| Method | Path | Notes |
|---|---|---|
| POST | `/api/conversations` | login required; starts a conversation on the caller's organization (tenant and profile come from the session, never the body) → `{id, greeting}` |
| GET | `/api/conversations?limit=&offset=&includeEmpty=` | the caller's organization's saved conversations, newest first: `{items[{id, startedAt, status, messageCount, lastMessageAt, preview}], total}`; conversations where nobody spoke are hidden unless `includeEmpty=true` |
| POST | `/api/conversations/{id}/messages` | `{text}` → `{reply, intent}` (text path) |
| GET | `/api/conversations/{id}` | `startedAt` + transcript (every message with its time) + context; 404 for another organization's id |
| POST | `/api/voice/session` | `{conversationId}` → `{transport, wsPath, audio.mimeType}` |
| GET | `/api/domain-profiles/{id}` | profile config |
| WS | `/ws/voice/{id}` | up: binary mic audio, `{"type":"interrupt"}`; down: `transcript.partial/final`, `assistant.text`, `assistant.audio_end`, `assistant.interrupt`, `error` + binary MP3 per sentence |

Errors: `{"error": {"code", "message", "requestId"}}`. The public voice/conversation endpoints still take the tenant from the `X-Tenant-Id` header (default demo tenant); moving them onto JWT claims is later work.

## Roles, auth and onboarding
Three roles:

- **Superadmin** (top of the platform, seeded from `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD`): creates *businesses* (tenants). Creating one also creates its admin account, generates a password and emails it (SendGrid, or logged when `SENDGRID_API_KEY` is empty; sent before the commit, so a delivery failure creates nothing). Can disable/enable a business, which locks out its admin and its customers.
- **Admin** (business admin, `users.tenant_id` set): logs in, sees the dashboard, MCP integration, all of their business's conversations, and can try the chat/voice assistant.
- **User** (customer): signs up with name, email and password (active immediately, no tenant), picks a business, and chats or talks to it for enquiries and bookings. Customers only see their own conversations (`conversations.user_id`).

- `users` (`role` superadmin|admin|user; names are not unique, login is by email) and `refresh_tokens` (sha256-hashed, rotated on every refresh).
- Access JWT (15 min, HS256) is sent as `Authorization: Bearer` and kept in memory by the SPA. The refresh token is an httpOnly, SameSite=Lax cookie scoped to `/api/auth`. Replaying an already-rotated refresh token revokes all of that user's tokens.
- Failed logins are throttled per email+IP (5 per 15 min, in-memory, so per-process only).
- Conversation endpoints resolve a `ChatScope`: an admin's tenant comes from their account; a customer names the business with the `X-Business-Id` header (`?business=` on the voice WebSocket), which must be an active tenant. Superadmins are refused.

| Method | Path | Access |
|---|---|---|
| POST | `/api/auth/register` | public; `{name, email, password(>=8)}` → 201, creates an active customer; 409 if the email is taken |
| POST | `/api/auth/login` | public; `{identifier: email, password}`; 401 bad credentials, 403 `account_disabled`, 429 throttled |
| POST | `/api/auth/refresh` · `/api/auth/logout` | refresh cookie |
| GET | `/api/auth/me` | any active user |
| GET | `/api/businesses` | any logged-in user; active businesses (`id, name`) a customer can talk to |
| POST | `/api/superadmin/businesses` | superadmin; `{name, adminName, adminEmail}` → 201; 409 on duplicate name/email |
| GET | `/api/superadmin/businesses?q=` | superadmin; businesses with their admin |
| PATCH | `/api/superadmin/businesses/{id}` | superadmin; `{isActive}` |
| GET | `/api/superadmin/users?status=&role=&q=&limit=&offset=` | superadmin; paged list (`items, total, counts` per status); `q` matches name or email |
| GET | `/api/superadmin/users/{id}` | superadmin; adds the business name |

SPA routes: `/` redirects to the user's home (or `/login`). Logged-out layout: `/login`, `/register` (customer sign-up). Authenticated layout with sidebar (`layouts/AppShell`): superadmin → `/superadmin/businesses` (home) and `/superadmin/users`; admin → `/admin` (dashboard, home), `/mcp`, `/chat`, `/conversations/:id?`; customer → `/chat` (home; picks a business, text + voice) and `/conversations/:id?` (their own history).

## Tenant resolution
Conversation and voice endpoints never trust a client-supplied tenant. `get_tenant_id` takes it from the logged-in admin's access token (`Authorization: Bearer`); the voice WebSocket takes the same token from `?token=` and closes with 1008 if it is missing, invalid or belongs to a user without an organization. The conversation uses the tenant's active domain profile; ids for another tenant simply do not exist for the caller (404).

## MCP integration (per organization)
Each admin connects their own MCP servers on the `/mcp` page, fully configurable per server: URL, transport (Streamable HTTP or SSE), timeout (1-60 s) and any request headers; the AI on that organization's calls can use only those servers' tools.

| Method | Path | Notes |
|---|---|---|
| GET / POST | `/api/org/mcp-servers` | admin only; list / add `{name, url, headers[], transport, timeoutSeconds}` (max 5 per organization, names unique per organization). `headers` is a list of `{name, value?, secret}`: any header name (API key, `Authorization`, custom), at most 10; secret values are encrypted and returned only as `hasValue`; plain values are shown. Protocol headers (Host, Content-Length, Content-Type, Accept, Mcp-Session-Id...) and CR/LF in values are refused |
| PATCH / DELETE | `/api/org/mcp-servers/{id}` | same fields, all optional, plus `enabled`. `headers` is the complete new list (a secret re-sent without a value keeps its saved value; headers left out are removed); ids of other organizations are 404 |
| POST | `/api/org/mcp-servers/{id}/test` | connects with the saved config and lists the tools |

Isolation guarantees:
- `mcp_servers` rows are only reached through `McpServerRepository`, a `TenantScopedRepository`; the tenant is the authenticated admin's, never request input.
- `McpToolSource.for_tenant(ctx.tenant_id)` builds a tool set from that tenant's enabled servers only; tool calls are routed to the server and credentials captured in that set. The tool-list cache key includes tenant id, server id and config version.
- Secret header values are Fernet-encrypted at rest (`MCP_SECRET_KEY`, or derived from `JWT_SECRET`) and never returned by the API (`hasToken` only).
- SSRF guard (`app/mcp/security.py`): http(s) only, no embedded credentials, link-local/metadata/unspecified/multicast always refused, loopback/private hosts refused unless `MCP_ALLOW_PRIVATE_HOSTS=true` (local development). Checked on save and again before every use; the MCP client never follows HTTP redirects (a redirect could otherwise skip the check).
- A broken, slow or disabled server contributes no tools and never fails the conversation; tool errors go back to the LLM as error results. Tool results are capped at 8000 characters.
- Tools are exposed to the LLM as `<server-name>__<tool>`; the prompt adds today's date and tool-use rules only when the tenant has tools.

Not isolated by the platform: a backend system (for example HolidayBooking) that serves several organizations from one database. Separating that data is the MCP server's job (give each organization its own URL or token).

## Hotel API tool interface (implemented Phase 3)
`GET /api/hotel`, `GET /api/rooms`, `POST /api/rooms/availability {checkIn, checkOut, guests, roomType?}`, `POST /api/bookings`, `GET|PUT|DELETE /api/bookings/{id}` — wrapped as tools `get_hotel_information`, `get_rooms`, `check_room_availability`, `create_booking` (only reachable through the booking state machine after explicit confirmation), `get_booking`, `modify_booking`, `cancel_booking`.

## Voice flow (Phase 1)
mic → MediaRecorder (250 ms chunks) → WS → backend → Deepgram live STT (endpointing) → `ConversationService.reply_stream` → Claude stream → sentence chunker → Deepgram TTS → MP3 frame per sentence → browser queue player. Barge-in: partial transcript while audio is playing stops playback client-side and cancels the server turn (partial reply is still persisted).

## Testing
pytest with `FakeLLMProvider`/`FakeSTT`/`FakeTTS` and in-memory SQLite (models are portable); Vitest + Testing Library with a fake `VoiceClient`. Real Anthropic/Deepgram are not called in tests.
