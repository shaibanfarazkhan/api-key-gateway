# Limitations

The repository currently implements administrative organization and plan
management, API key creation/rotation/revocation, a reusable API key
authentication dependency, a monthly quota reservation service, and a
read-only current-month usage endpoint. Automated tests cover the administrative
API, authentication, quota, quote, rate limiting, and usage reporting.

The protected `GET /v1/quote` route currently returns a dummy quote after
authentication and quota reservation. A real quote provider is not connected.
The protected `GET /usage` route reports aggregate usage for the current UTC
month and authenticated organization. It does not yet support date-range or
per-key filters. The quote provider contract and administrative identity
mechanism are still open design decisions.

The quote route uses Redis for per-organization sliding-window rate limiting.
Redis-backed caching is not implemented. The current quota service uses the
existing monthly per-key usage records and aggregates them at the organization
level. It expects a single active plan per organization; assignment history and
effective dates are not modeled.

The admin endpoints currently have no administrative authentication. The
development credentials in `.env.example` and Docker Compose are for local use
only. Production secrets, database credentials, Redis access controls, TLS
termination, observability, and deployment infrastructure must be configured
for the target environment before deployment.
