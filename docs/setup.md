# Setup UCR Chatbot 2.0

Run the bot with Docker. To change the code or run without Docker, see [`develop.md`](develop.md).

## What you need

- Docker
- A LINE Messaging API channel, with its channel secret and channel access token
- A Gemini API key from Google AI Studio

## 1. Make `.env`

```bash
cp .env.example .env
```

`.env` is not in git. Put real values only in `.env`, never in `.env.example`.

`.env.example` has only the keys you usually set. Add any other key from this table to `.env` to change its default.

| Key | Needed | Default | What it does |
|---|---|---|---|
| `LINE_CHANNEL_SECRET` | yes | none | checks LINE's signature on the webhook |
| `LINE_CHANNEL_ACCESS_TOKEN` | yes | none | reply, push, loading dots, photo download, monthly message count |
| `GEMINI_API_KEY` | yes | none | Gemini key |
| `POSTGRES_PASSWORD` | yes | none | used once, when the database is first created · letters and numbers only |
| `DASHBOARD_API_KEY` | for the dashboard | none | key the dashboard sends · not set: every `/api/dashboard` route gives 503 |
| `API_ENDPOINT` | no | Gemini's OpenAI-compatible URL | must end with `/v1beta/openai/` |
| `APP_PORT` | no | `8000` | port on your machine for the app |
| `WORKER_ENABLED` | no | `true` | `false`: messages are saved, but nobody answers or closes chats · with Docker, the app shows `unhealthy` |
| `SILENCE_SECONDS` | no | `3` | seconds of no new message before the bot answers |
| `CLOSE_AFTER_MINUTES` | no | `120` | minutes of no new message before a chat closes and becomes reports |
| `SWEEP_EVERY_SECONDS` | no | `60` | how often the sweeper looks for quiet chats |
| `BROADCAST_ENABLED` | no | `false` | bot messages reporters first every day |
| `FORECAST_URL` | for broadcast | empty | daily forecast file, `{date}` becomes `YYYY-MM-DD` · empty: `app/clients/mock_forecast.json` |
| `BROADCAST_DAILY_LIMIT` | no | `10` | people a day, picked at random |
| `BROADCAST_WAIT_HOURS` | no | `24` | hours a broadcast chat waits for a reply before it closes |
| `BROADCAST_FETCH_AT` | no | `01:00` | reads the forecast from this time, Thai time |
| `BROADCAST_SEND_AT` | no | `08:00` | sends from this time |
| `BROADCAST_SEND_UNTIL` | no | `20:00` | not sent by this time: no message today |
| `BROADCAST_CHECK_SECONDS` | no | `60` | how often the broadcaster checks the time |

Make a `DASHBOARD_API_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Run with Docker

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

All 3 containers must show `healthy`.

| Container | What is in it | Data is kept in volume |
|---|---|---|
| `app` | FastAPI, worker, sweeper and broadcaster in one process | `uploads`: photos |
| `postgres` | PostgreSQL 18 + PostGIS · makes database `ucr-chat-v2-alpha` and runs `schema.sql` when the volume is empty | `pgdata` |
| `redis` | Redis 8, saves to disk every 60 seconds | `redisdata` |

`postgres` and `redis` open no ports outside Docker. The app finds them by service name.

| Command | What it does |
|---|---|
| `docker compose up -d --build` | after a code change: build the image again and start |
| `docker compose up -d --force-recreate app` | after a `.env` change: start the app again with the new values |
| `docker compose logs -f app` | follow the app log |
| `docker compose restart app` | restart the app |
| `docker compose exec postgres psql -U ucr -d ucr-chat-v2-alpha` | open psql |
| `docker compose down` | stop everything, data stays |
| `docker compose down -v` | stop everything and **delete the database, photos and Redis data** |

Good to know:

- `POSTGRES_PASSWORD` is used only when the database is first created. Changing it later breaks the app's connection.
- `schema.sql` runs only on an empty `pgdata` volume. After a change to `schema.sql`, run `docker compose down -v`, then `docker compose up -d --build`. This deletes all data.
- Redis or PostgreSQL goes down and comes back: the worker or the sweeper can stop, and `/health` gives 503. Run `docker compose restart app`.
- Port 8000 is in use: set `APP_PORT` in `.env`.
- Each container has its own compose file in `docker/`. Start one alone from the repo root, for example `docker compose --env-file .env -f docker/app/docker-compose.yml up -d --build`. The app then does not wait for the database. Compose warns about orphan containers. **Do not add `--remove-orphans`**: it deletes the other containers.

## 3. Check it is up

```bash
curl -i http://localhost:8000/health
```

All up gives 200. One part down gives 503, and the JSON shows which one:

```json
{"database": true, "redis": true, "worker": true, "sweeper": true}
```

`/health` does not show the broadcaster. Its errors are in the app log.

On the first start with an empty database, the app adds the first model, prompts and AI settings from `app/core/default_config.py`.

## 4. Connect LINE

1. Give the app a public HTTPS URL. On a dev machine: `ngrok http 8000`.
2. In LINE Developers Console, open your channel, then the Messaging API tab:
   - Webhook URL: `https://<public URL>/webhook/line`
   - Use webhook: on
   - Press Verify. It must show success.
3. In LINE Official Account Manager, turn off auto-reply messages and the greeting message. The bot sends its own PDPA card.
4. Add the bot as a friend. You get the PDPA card.

## 5. Turn on broadcast

1. In `.env`, set `BROADCAST_ENABLED=true` and `FORECAST_URL`. `WORKER_ENABLED` must stay `true`.
2. Start the app again:

```bash
docker compose up -d --force-recreate app
```

- Empty `FORECAST_URL` uses `app/clients/mock_forecast.json`. It has rain every day, so every message is about rain.
- Each push counts 1 of LINE's monthly messages for each person. The free plan has 300 a month. The bot sends to at most 10 people a day, and to nobody on the 31st.
- One row a day in table `broadcasts`. See the last days:

```bash
docker compose exec postgres psql -U ucr -d ucr-chat-v2-alpha -c "SELECT forecast_date, status, reason FROM broadcasts ORDER BY forecast_date DESC LIMIT 5;"
```

`status`: `scheduled` = waiting to send · `sent` = done · `expired` = not sent by 20:00.

## 6. AI settings

Models, prompts and limits are in the database, in table `ai_configs`, in the row with `is_active = true`. Only one row can be active. The app reads it again for every job, so a change works from the next message.

| Column | Default | What it limits |
|---|---|---|
| `user_daily_token_limit` | `500000` | tokens one reporter can use in a day, Thai time |
| `system_daily_token_limit` | `5000000` | tokens all reporters together can use in a day |
| `session_buffer_limit` | `30` | messages waiting for an answer in one chat · over it, the chat pauses for 24 hours |

Token limits count only the chat calls, not the analyser.

```bash
docker compose exec postgres psql -U ucr -d ucr-chat-v2-alpha -c "SELECT * FROM ai_configs WHERE is_active;"
```
