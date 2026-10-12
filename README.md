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
