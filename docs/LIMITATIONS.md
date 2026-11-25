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
- `GET /usage?include_daily=true` optionally includes UTC daily totals for the
  current month.
- Key rotation permits the old key until the configurable
  `API_KEY_ROTATION_GRACE_SECONDS` deadline. The default is five minutes.
- An organization has one active plan at a time. Assignment history and
  effective-dated plan changes are not represented.
- Redis-backed caching is not used. Redis is the shared sliding-window rate
  limiter; limiter failures return `503` rather than switching to local state.
- Usage is stored as per-key monthly and daily aggregates. There is no durable
  per-request usage event or provider outcome record.

## Administrative audit scope

- Successful API key creation, rotation, revocation, and plan assignment are
  recorded in the audit log without storing plaintext keys.
- The actor is recorded as the shared `admin` principal. The application does
  not provide individual admin identities, organization-scoped admin roles, or
  audit records for failed administrative attempts.

## Benchmark status

- The Redis-only benchmark results and p95 threshold are recorded in
  [BENCHMARK.md](../BENCHMARK.md). The measured EVALSHA run did not outperform
  EVAL; no Redis latency improvement is claimed.
- [PERFORMANCE.md](../PERFORMANCE.md) documents a separate full-request-path
  benchmark and optimization. These measurements use different workloads and
  should not be compared as if they were the same benchmark.

## Deployment requirements

- Administrative routes require the configured shared `ADMIN_API_KEY` bearer
  credential. Restrict access at the network or ingress boundary as an
  additional control.
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
