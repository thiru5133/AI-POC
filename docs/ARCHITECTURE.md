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
`backend/app/`: `api/` routes+schemas+deps · `conversation/` engine, context, prompt, chunker, service · `ai/` providers · `domain/` profile model + `profiles/hotel.json` · `tools/` registry · `workflows/` (booking state machine, Phase 4) · `voice/` interfaces, Deepgram, fakes, WS session · `models/`, `repositories/`, `database/` (SQLAlchemy + Alembic) · `core/` settings, JSON logging, error envelope · `tenants/`, `auth/` (stubs for Phase 8).
`frontend/src/`: `features/conversation/` UI · `voice/` `VoiceClient` interface, `BrowserDeepgramClient`, `useVoiceSession` · `services/` typed API client · `types/`.

Deviation from the suggested layout: no `agents/` (single engine), added `workflows/` and `core/`.

## Data model (SQL Server)
`tenants`, `domain_profiles(tenant_id, config JSON)`, `conversations(tenant_id, domain_profile_id, status, outcome, context JSON)`, `messages(tenant_id, conversation_id, role, content, intent)`, `tool_calls(tenant_id, …)` (populated in Phase 5). Bookings/users/usage land in their phases.

## ConversationContext
`session_id, tenant_id, domain_profile_id, intent, entities{} (generic slots keyed by profile requiredFields), caller{name,phone,email}, workflow_state, last_action`. Memory = persisted message history (last 40) + this context, reloaded each turn.

## API
| Method | Path | Notes |
|---|---|---|
| POST | `/api/conversations` | `{tenantId?, domainProfileId?}` → `{id, greeting}` |
| POST | `/api/conversations/{id}/messages` | `{text}` → `{reply, intent}` (text path) |
| GET | `/api/conversations/{id}` | transcript + context |
| POST | `/api/voice/session` | `{conversationId}` → `{transport, wsPath, audio.mimeType}` |
| GET | `/api/domain-profiles/{id}` | profile config |
| WS | `/ws/voice/{id}` | up: binary mic audio, `{"type":"interrupt"}`; down: `transcript.partial/final`, `assistant.text`, `assistant.audio_end`, `assistant.interrupt`, `error` + binary MP3 per sentence |

Errors: `{"error": {"code", "message", "requestId"}}`. Phase 1 tenant = `X-Tenant-Id` header (default demo tenant); JWT in Phase 8.

## Hotel API tool interface (implemented Phase 3)
`GET /api/hotel`, `GET /api/rooms`, `POST /api/rooms/availability {checkIn, checkOut, guests, roomType?}`, `POST /api/bookings`, `GET|PUT|DELETE /api/bookings/{id}` — wrapped as tools `get_hotel_information`, `get_rooms`, `check_room_availability`, `create_booking` (only reachable through the booking state machine after explicit confirmation), `get_booking`, `modify_booking`, `cancel_booking`.

## Voice flow (Phase 1)
mic → MediaRecorder (250 ms chunks) → WS → backend → Deepgram live STT (endpointing) → `ConversationService.reply_stream` → Claude stream → sentence chunker → Deepgram TTS → MP3 frame per sentence → browser queue player. Barge-in: partial transcript while audio is playing stops playback client-side and cancels the server turn (partial reply is still persisted).

## Testing
pytest with `FakeLLMProvider`/`FakeSTT`/`FakeTTS` and in-memory SQLite (models are portable); Vitest + Testing Library with a fake `VoiceClient`. Real Anthropic/Deepgram are not called in tests.
