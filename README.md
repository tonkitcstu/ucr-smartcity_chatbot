# UCR Chatbot

A LINE bot for UCR / TONKIT Lab. People in a community tell it about their environment and the city around their home. Gemini chats with them, then turns each chat into reports with a location. The city design team reads the reports and uses them to choose what to improve first.

## What it does

- **Chat**: a reporter sends text, photos, location pins or stickers. The bot waits until they stop typing for 3 seconds, then Gemini answers with up to 5 messages and buttons: location, camera, camera roll, or answer words.
- **Reports**: a chat that is quiet for 2 hours closes. Gemini reads the whole chat and writes 0 to n reports. Each report has a description, tags, severity, who is affected, time of day, place, location and photos.
- **Dashboard API**: the design team reads reports, photos and chats with an API key.
- **PDPA**: a new reporter gets the PDPA card first. Nothing is saved until they tap accept.
- **Limits**: tokens per reporter per day, tokens for everyone per day, and messages waiting in one chat. A reporter who hits a limit gets a fixed text instead of Gemini.
- **Fallback**: Gemini fails or takes over 50 seconds. The reporter gets a fixed text, and their messages stay for the next answer.
- **Broadcast**: off by default. Every day the bot messages up to 10 random reporters first. Rain in the forecast from 08:00 to 20:00 gets a rain message, other days get a friendly hello. No message on the 31st.

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
| Gemini | through its OpenAI-compatible API · default model `gemini-3.5-flash-lite`, the real one is set in table `ai_configs` |
| LINE Messaging API | webhook in, reply and push out |

## Setup

Run the bot with Docker. Full steps: [`docs/setup.md`](docs/setup.md)

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

```bash
curl -i http://localhost:8000/health
```

## Develop

Work on the code with uv, PostgreSQL and Redis on your machine. Full steps: [`docs/develop.md`](docs/develop.md)

```bash
uv sync
```

```bash
uv run uvicorn app.main:app --reload
```

```bash
uv run pytest
```

Project rules: [`CLAUDE.md`](CLAUDE.md)

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

6 routes: the LINE webhook, a health check, and 4 dashboard routes for reports, photos and chats. Routes, API key, filters and response JSON: [`docs/api.md`](docs/api.md)

## Docs

- [`docs/setup.md`](docs/setup.md): run the bot with Docker, connect LINE, turn on broadcast, AI settings
- [`docs/develop.md`](docs/develop.md): run on your machine, tests, dependencies, code layout, workflow
- [`docs/diagrams/`](docs/diagrams/): how it works
- [`docs/api.md`](docs/api.md): all routes
