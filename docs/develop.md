# Develop UCR Chatbot 2.0

Work on the code and run it on your machine. To run the bot with Docker, see [`setup.md`](setup.md).

## What you need

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/)
- PostgreSQL with PostGIS (macOS: `brew install postgis`)
- Redis
- A test LINE channel and a Gemini API key. Never use the real LINE channel while you develop.

## 1. Install

```bash
uv sync
```

```bash
cp .env.example .env
```

Fill in the keys from [`setup.md`](setup.md) step 1. These keys are only for running on your machine:

| Key | Default | What it does |
|---|---|---|
| `DATABASE_URL` | none | PostgreSQL to use |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis to use |
| `UPLOADS_DIR` | `uploads/` in the repo | folder for photo files |

## 2. Make the database

```bash
createdb ucr-chat-v2-alpha
```

```bash
psql ucr-chat-v2-alpha -f schema.sql
```

Set `DATABASE_URL` in `.env` to this database.

- `schema.sql` has no `IF NOT EXISTS`: running it on a database that has tables fails.
- There are no migrations. After a change to `schema.sql`, drop the database and make it again.

## 3. Run

```bash
uv run uvicorn app.main:app --reload
```

```bash
curl -i http://localhost:8000/health
```

Connect your test LINE channel with `ngrok http 8000`, then follow [`setup.md`](setup.md) step 4.

## 4. Tests

```bash
createdb ucr_nongmuang_test
```

```bash
uv run pytest
```

- Tests use database `ucr_nongmuang_test` and Redis db 15. Change them with `TEST_DATABASE_URL` and `TEST_REDIS_URL`.
- **Every run wipes all tables in that database and everything in Redis db 15.** Never point them at real data.
- Tests that call Gemini for real are skipped. Run them with `LIVE_AI=1 uv run pytest`.
- The Docker containers open no ports, so tests need PostgreSQL and Redis on your machine.

## 5. Dependencies

Add or remove a package with uv. `pyproject.toml` and `uv.lock` change together.

```bash
uv add <package>
```

The Docker image installs from `uv.lock`. `requirements.txt` is for people without uv. Make it again after a change:

```bash
uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
```

## 6. Code

Project rules: [`CLAUDE.md`](../CLAUDE.md). Comments in the code are in Thai.

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
docs/diagrams/   Mermaid diagrams of how it works
```

The usual direction of a call: from `api` to `controllers` or `workers`, then to `services`, then to `clients`. These imports skip a layer:

- `controllers/line.py`, `workers/worker.py` and `workers/broadcaster.py` use `clients/line.py`
- `controllers/health.py` uses `clients/database.py` and `clients/redis.py`
- `api/dashboard.py` uses `services/auth.py`

## 7. Workflow

- Base branch: `dev`. One issue, one branch.
- Commits in this order: design (Mermaid in `docs/diagrams/`), test (fails first), feat (test passes).
- Pull request into `dev`, rebase merge.

## Not in git

- `.env`: real values
- `uploads/`: photos from reporters
- `local/`: personal notes
