# API Key Gateway

Production-oriented Phase 0 foundation for an API Key Gateway. This phase sets
up the project, tooling, and infrastructure integrations. It intentionally has
no endpoints or business logic yet.

## Requirements

- Python 3.11
- [uv](https://docs.astral.sh/uv/) for dependency and virtual environment management
- Docker and Docker Compose for local PostgreSQL and Redis

## Local setup

1. Copy `.env.example` to `.env` and change `SECRET_KEY` to a generated secret.
2. Start local dependencies: `docker compose up -d postgres redis`.
3. Install application and development dependencies: `uv sync --all-groups`.
4. Start the ASGI application: `uv run uvicorn app.main:app --reload`.
5. Apply database migrations when migration revisions are introduced: `uv run alembic upgrade head`.

The Phase 0 application currently registers no HTTP routes. PostgreSQL is
available at `localhost:5432` and Redis at `localhost:6379` using the local
development credentials in Compose.

## Docker Compose

`docker compose up --build` starts the API container, PostgreSQL, and Redis.
The API container runs as a non-root user and uses a read-only root filesystem.
For local host development, use `docker compose up -d postgres redis` instead.

## Development commands

Run `make install-dev` to install dependencies and `make lint`, `make format`,
`make typecheck`, and `make test` for quality checks. Run `pre-commit install`
once to enable the configured hooks. `make ci` runs the local CI checks.

Create an Alembic revision with `make revision message="describe schema change"`
and apply it with `make migrate`. Review generated migrations before committing.

## Project layout

```text
app/          FastAPI app, core configuration, and future domain layers
tests/        Pytest suite
migrations/   Alembic environment and revisions
docs/         Design and limitations notes
scripts/      Developer and operational scripts
.github/      GitHub Actions workflows
```

## Configuration

Settings are read from environment variables, with `.env` supported for local
development. See `.env.example` for the available Phase 0 settings. Never commit
real secrets or production credentials.
