# Limitations

The repository currently implements administrative organization and plan
management, API key creation/rotation/revocation, a reusable API key
authentication dependency, and a monthly quota reservation service. Automated
tests cover the administrative API, authentication behavior, and quota service.

The authentication dependency and quota service are not yet connected to a
customer-facing endpoint. In particular, the planned `GET /v1/quote` and
`GET /usage` routes are not implemented. The quote provider contract and the
administrative identity mechanism are still open design decisions.

Redis is configured as a dependency in the application and in Docker Compose,
but Redis-backed rate limiting and caching are not implemented. The current
quota service uses the existing monthly per-key usage records and aggregates
them at the organization level. It expects a single active plan per
organization; assignment history and effective dates are not modeled.

The admin endpoints currently have no administrative authentication. The
development credentials in `.env.example` and Docker Compose are for local use
only. Production secrets, database credentials, Redis access controls, TLS
termination, observability, and deployment infrastructure must be configured
for the target environment before deployment.
