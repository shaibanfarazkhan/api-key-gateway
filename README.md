# API Key Gateway

FastAPI service foundation for organization-scoped API keys, plan administration,
API key authentication, and monthly quota reservation. PostgreSQL is the source of
persisted application data. Docker Compose also provides a Redis service for local
development; Redis-backed rate limiting is not implemented yet.

## Current implementation

- Administrative endpoints create and read organizations, create plans, assign a
  plan to an organization, and create, rotate, and revoke API keys.
- API keys are generated and returned at creation time. The database stores a
  SHA-256 digest and a display prefix, not the plaintext key.
- A reusable Bearer authentication dependency validates the stored digest, key
  status and expiration, and organization status. It returns the authenticated
  `Organization` and `APIKey` objects to dependent routes.
- Monthly quota policy reads the organization's single active plan and reserves
  usage in the existing monthly `UsageRecord` table. Quota is aggregated across
  the organization's keys. The service returns `429` when the monthly allowance
  is exhausted.
- Pytest covers administrative routes, API key authentication, and monthly quota
  reservation.

`GET /v1/quote` uses the authentication dependency and monthly quota service and
returns a clearly marked dummy quote. A real quote provider is not connected yet.
There is no `GET /usage` endpoint. Redis is configured in the application and
Compose, but no application code currently uses it for rate limiting or caching.
The admin endpoints do not yet require an administrative identity.

## Architecture

```text
HTTP routes (app/api)
        |
        +--> shared dependencies (app/core)
        |       +--> API key authentication service
        |       +--> SQLAlchemy session
        |
        +--> application services (app/services)
                +--> repositories (app/repositories)
                +--> SQLAlchemy models (app/models)
                         |
                    PostgreSQL
```

The admin router delegates organization, plan, and key operations to
`app/services/admin.py`. API key authentication uses
`app/services/authentication.py` and `app/repositories/api_keys.py`. Monthly
quota policy is in `app/services/quota.py`, with persistence operations in
`app/repositories/usage.py`. Request and response schemas are in `app/schemas`.
The protected quote route is in `app/api/quotes.py` and uses
`app/schemas/quotes.py` for its response model. Alembic manages database schema
revisions under `migrations/`.

## API endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/admin/organizations` | Create an organization. |
| `GET` | `/admin/organizations` | List organizations. |
| `GET` | `/admin/organizations/{organization_id}` | Retrieve an organization. |
| `POST` | `/admin/plans` | Create a plan with request and monthly quota limits. |
| `PATCH` | `/admin/organizations/{organization_id}/plan` | Assign a plan to an organization. |
| `POST` | `/admin/api-keys` | Create an API key and return its plaintext once. |
| `POST` | `/admin/api-keys/{key_id}/rotate` | Create a replacement key; the existing key remains active. |
| `POST` | `/admin/api-keys/{key_id}/revoke` | Revoke an API key. |
| `GET` | `/v1/quote` | Authenticate the API key, reserve monthly quota, and return a dummy quote. |

FastAPI's interactive API documentation is available at `/docs` when the local
application is running.

## Development status

The repository includes the Phase 1 design, a working admin and persistence
foundation, API key authentication, monthly quota reservation, and a protected
dummy quote endpoint. The quote provider is still a placeholder.

Remaining implementation includes an agreed administrative authentication
mechanism, an approved quote provider contract and implementation, Redis-backed
rate limiting, and organization-scoped usage reporting. See [docs/DESIGN.md](docs/DESIGN.md)
for the proposed design and its open product decisions, and
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) for known limitations.

## Requirements

- Python 3.11
- [uv](https://docs.astral.sh/uv/) for dependency and virtual environment management
- Docker and Docker Compose for local PostgreSQL and Redis

## Local setup

1. Copy `.env.example` to `.env` and replace `SECRET_KEY` with a generated secret.
2. Start PostgreSQL and Redis: `docker compose up -d postgres redis`.
3. Install application and development dependencies: `uv sync --all-groups`.
4. Apply the checked-in database migration: `uv run alembic upgrade head`.
5. Start the ASGI application: `uv run uvicorn app.main:app --reload`.

PostgreSQL is available at `localhost:5432` and Redis at `localhost:6379` with
the local development credentials configured in Compose. Those credentials are
for local development only.

## Docker Compose

`docker compose up --build` starts the API container, PostgreSQL, and Redis. The
API container runs as a non-root user and uses a read-only root filesystem. For
host-based development, start only the dependencies with
`docker compose up -d postgres redis`.

## Development commands

Use `make install-dev` to install dependencies. Run `make lint`, `make format`,
`make typecheck`, and `make test` for local checks; `make ci` runs the complete
local CI command set. The GitHub Actions workflow runs Ruff, Black, mypy, and
pytest on pushes and pull requests.

Create an Alembic revision with `make revision message="describe schema change"`
and apply it with `make migrate`. Review generated migrations before committing.

## Project layout

```text
app/
  api/          FastAPI routers
  core/         Settings, database session, and shared dependencies
  models/       Organization, plan, API key, and usage ORM models
  repositories/ Persistence queries for API keys and usage
  schemas/      Administrative request and response schemas
  services/     Admin operations, authentication, and quota policy
  main.py       FastAPI application entry point
migrations/     Alembic environment and schema revisions
tests/          Administrative API, authentication, quota, and quote tests
docs/           Design RFC and limitations
scripts/        Operational and developer script placeholders
.github/        GitHub Actions workflows
```

## Configuration

Settings are loaded from environment variables, with `.env` supported for local
development. See `.env.example` for application, database, Redis, and secret
settings. Never commit production secrets or credentials.
