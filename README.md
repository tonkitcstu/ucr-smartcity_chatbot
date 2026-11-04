# UCR Chatbot

A LINE bot for UCR / TONKIT Lab. People in a community tell it about their environment and the city around their home. Gemini chats with them, then turns each chat into reports with a location. The city design team reads the reports and uses them to choose what to improve first.

Setup and run: [`docs/setup.md`](docs/setup.md) · Code rules: [`CLAUDE.md`](CLAUDE.md)

## What it does

- **Chat** — a reporter sends text, photos, location pins or stickers. The bot waits until they stop typing for 3 seconds, then Gemini answers with up to 5 messages and buttons: location, camera, camera roll, or answer words.
- **Reports** — a chat that is quiet for 2 hours closes. Gemini reads the whole chat and writes 0 to n reports. Each report has a description, tags, severity, who is affected, time of day, place, location and photos.
- **Dashboard API** — the design team reads reports, photos and chats with an API key.
- **PDPA** — a new reporter gets the PDPA card first. Nothing is saved until they tap accept.
- **Limits** — tokens per reporter per day, tokens for everyone per day, and messages waiting in one chat. A reporter who hits a limit gets a fixed text instead of Gemini.
- **Fallback** — Gemini fails or takes over 50 seconds: the reporter gets a fixed text, and their messages stay for the next answer.
- **Broadcast** — off by default. Every day the bot messages up to 10 random reporters first. Rain in the forecast from 08:00 to 20:00 gets a rain message, other days get a friendly hello. No message on the 31st.

Gemini writes every message the bot sends. Fixed texts in code: the fallback text, the limit texts, and the PDPA card with its welcome text.

## How it runs

| Part | What it does |
|---|---|
| `app` container | FastAPI on port 8000, with 3 background loops in the same process: worker, sweeper, broadcaster |
| worker | answers chats with Gemini, turns closed chats into reports |
| sweeper | closes quiet chats every 60 seconds |
| broadcaster | messages reporters first, only when `BROADCAST_ENABLED=true` |
| `postgres` container | PostgreSQL 18 + PostGIS: users, sessions, messages, reports, AI settings and prompts |
| `redis` container | Redis 8: messages waiting for an answer, chat state, chat history, job queue |
| Gemini | `gemini-3.5-flash-lite` through its OpenAI-compatible API |
| LINE Messaging API | webhook in, reply and push out |

## Diagrams

Mermaid files in [`docs/diagrams/`](docs/diagrams/):

| File | Shows |
|---|---|
| [`overview-architecture.mmd`](docs/diagrams/overview-architecture.mmd) | all parts and what each one sends to the others |
| [`overview-placement.mmd`](docs/diagrams/overview-placement.mmd) | which container each part runs in |
| [`sequence-normal.mmd`](docs/diagrams/sequence-normal.mmd) | a message comes in, Gemini answers |
| [`sequence-leaving.mmd`](docs/diagrams/sequence-leaving.mmd) | the reporter goes quiet or blocks the bot, the chat becomes reports |
| [`sequence-push.mmd`](docs/diagrams/sequence-push.mmd) | the bot messages up to 10 people first |
| [`sequence-pdpa.mmd`](docs/diagrams/sequence-pdpa.mmd) | PDPA card and accept |
| [`sequence-hit-limit.mmd`](docs/diagrams/sequence-hit-limit.mmd) | token and message limits |
| [`sequence-fallback.mmd`](docs/diagrams/sequence-fallback.mmd) | Gemini fails or is too slow |
| [`broadcast-flow.mmd`](docs/diagrams/broadcast-flow.mmd) | broadcast as a flowchart |
| [`session-states.mmd`](docs/diagrams/session-states.mmd) | chat states in Redis and who changes them |

## API

| Route | What it does | Who can call it |
|---|---|---|
| `POST /webhook/line` | gets events from LINE | LINE only, checked by LINE's signature |
| `GET /health` | PostgreSQL, Redis, worker and sweeper are up | anyone |
| `GET /api/dashboard/reports` | reports, newest first, filter by `date`, `start_date`, `end_date`, `tag`, `severity`, `limit` | API key |
| `GET /api/dashboard/reports/{report_id}` | one report | API key |
| `GET /api/dashboard/attachments/{attachment_id}` | one photo file | API key |
| `GET /api/dashboard/transcripts/{session_id}` | the whole chat of one session | API key |

API key: header `Authorization: Bearer <key>`, the same value as `DASHBOARD_API_KEY` in `.env`. Wrong or missing key gives 401. `DASHBOARD_API_KEY` not set gives 503.

Full routes for Postman: [`docs/api.md`](docs/api.md) · JSON and curl for each route: [`docs/designs/09-modules/h7-dashboard-api.md`](docs/designs/09-modules/h7-dashboard-api.md)

## Code

```
app/
  main.py        starts the app and the 3 background loops
  api/           routes
  controllers/   LINE webhook, dashboard, health
  workers/       worker, sweeper, broadcaster
  services/      one file per thing: session, state, quota, pdpa, broadcast, prompt, report ...
  clients/       outside systems: database, redis, line, ai, weather
  models/        data shapes
  core/          config.py reads .env · default_config.py has the first model and prompts
schema.sql       all tables
tests/           pytest
docker/          Dockerfiles and compose files for each container
```

## Docs

- [`docs/setup.md`](docs/setup.md) — install, run, connect LINE, turn on broadcast, test
- [`docs/diagrams/`](docs/diagrams/) — how it works
- [`docs/api.md`](docs/api.md) — all routes
- [`docs/requirements/`](docs/requirements/) — needs, constraints, user stories
