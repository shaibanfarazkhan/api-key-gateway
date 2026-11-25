# Operational Scope and Limitations

The repository implements the documented API Key Gateway baseline, including
organization and plan administration, API key lifecycle operations, API key
authentication, monthly quota reservation, Redis-backed organization rate
limiting, a protected quote response, usage reporting, Alembic persistence, and
automated tests. These notes identify the behavior and deployment decisions
that operators must account for.

## Application behavior

- `GET /v1/quote` returns a deterministic placeholder quote. It exercises the
  complete authentication, rate-limit, and quota path without depending on an
  external quote vendor.
- `GET /usage` reports current UTC-month totals. It does not accept date-range
  or per-key filters.
- An organization has one active plan at a time. Assignment history and
  effective-dated plan changes are not represented.
- Redis-backed caching is not used. Redis is the shared sliding-window rate
  limiter; limiter failures return `503` rather than switching to local state.

## Deployment requirements

- Administrative routes require the configured shared `ADMIN_API_KEY` bearer
  credential. This baseline does not provide individual admin identities,
  role-based authorization, or admin-action audit records; restrict access at
  the network or ingress boundary as an additional control.
- The credentials in `.env.example` and Docker Compose are local-development
  values. Set strong secrets and managed database and Redis credentials for a
  deployed environment.
- Configure TLS termination, network policies, monitoring, backup and restore,
  log retention, and capacity limits in the target deployment environment.
- Docker Compose is intended for local integration and verification. Production
  deployments should use managed or separately operated PostgreSQL and Redis
  with operationally appropriate availability and recovery settings.

These constraints are explicit boundaries of the delivered repository and do
not affect the behavior covered by the automated suite.
