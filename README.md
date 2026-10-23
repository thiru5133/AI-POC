# AI Universal Receptionist (POC)

Everything runs in Docker (SQL Server + FastAPI backend + React frontend). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run
```
cp .env.example .env        # set GROQ_API_KEY and DEEPGRAM_API_KEY
docker compose up --build
```
Open http://localhost:5173 in Chrome/Edge → **Start call** → allow the microphone.
Backend API docs: http://localhost:8000/docs

## Try it
- "What time is check-in?" → "Check-in starts at 2 PM."
- "Do you have a swimming pool?"
- Ask something not in the knowledge base → "I'm sorry, I don't have that information."
- No keys yet? Set `LLM_PROVIDER=fake` for a stub LLM; the text box also works without Deepgram.

## Tests (in containers)
```
docker compose run --rm --no-deps --entrypoint "" backend pytest
docker compose run --rm --no-deps frontend npm test
docker compose run --rm --no-deps frontend npx tsc --noEmit
```

## Admin login
Set `SUPERADMIN_EMAIL` and `SUPERADMIN_PASSWORD` (and a real `JWT_SECRET`) in `.env`; the superadmin is created on backend start. The superadmin adds businesses at `/superadmin/businesses` (each gets an admin whose password is emailed); customers sign up themselves at `/register` and choose a business to chat with.

## Config
Edit `backend/app/domain/profiles/hotel.json` (greeting, FAQs, style); it is re-seeded on backend start.

## Phone calls (Twilio)
Customers can call a business on a real phone number; the same assistant answers as in the browser.

1. Get a voice-capable Twilio number. Put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `DEEPGRAM_API_KEY` in `.env`. (The backend runs `alembic upgrade head` on start.)
2. Give the backend a public HTTPS URL. In development: install ngrok, run `ngrok config add-authtoken <token>` once, then
   `./scripts/phone-dev.ps1 -Number +<your twilio number>`. It opens the tunnel, writes `PUBLIC_BASE_URL` into `.env`, restarts the backend and checks everything. Add `-Apply` to also point the number's webhook at the tunnel. (A free ngrok URL changes whenever ngrok restarts: run it again then.)
   Without the script, set `PUBLIC_BASE_URL` yourself and run `docker compose exec backend python -m app.voice.phone_setup --number +<number> [--apply]`.
3. As the business admin, open **Phone**, enter the same Twilio number (and, optionally, a number to transfer callers to a person) and save. Until a business saves the number, callers hear "this number is not in service".
4. Call the number. Without `-Apply`, set the number's **A call comes in** webhook (HTTP POST) to the URL shown on the Phone page.

Twilio trial accounts can only call verified numbers and play a trial message first; some countries (India included) require a regulatory bundle before Twilio sells you a local number.

How it works: Twilio POSTs to `/api/phone/incoming` (checked against `X-Twilio-Signature`); the number picks the business; the reply opens a Twilio Media Stream to `/ws/phone`, which carries the call's audio (8 kHz mu-law) through Deepgram speech-to-text, the conversation engine and Deepgram text-to-speech. The stream is authorised by a 60-second signed token from the webhook. When the assistant flags that the caller needs a person (`request_human`, or an urgent/emergency `flag_urgency`) and the business is open, the call is handed to the transfer number once the assistant has finished speaking. Calls count in the dashboard's conversations and voice minutes.

Not covered yet: outbound calls, a hold queue, and per-business Twilio accounts (one platform account serves all numbers).
