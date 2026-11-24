# API Key Gateway â€” Engineering RFC

**Status:** Implemented baseline design; deployment-specific decisions are recorded in Limitations
**Scope:** Phase 1 design for a production-grade gateway to a read-only Quotes API
**Runtime baseline:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 15, Redis, Docker Compose, pytest, Ruff, and mypy

## 1. Executive Summary

This RFC defines a horizontally scalable API Key Gateway that authenticates organization-owned keys and serves a read-only Quotes API. It covers organization and plan records, key issuance, rotation and revocation, monthly quota enforcement, short-term rate limiting, and usage reporting through the required endpoints: `GET /v1/quote`, `POST /admin/keys`, and `GET /usage`.

PostgreSQL is the authoritative store for organizations, plans, API key metadata, monthly quota accounting, and durable usage records. Redis is shared by all FastAPI instances and holds short-lived rate-limit counters. API key material is shown only at creation and is stored as a one-way keyed digest; authentication never requires storing the original key. FastAPI routes remain thin and delegate policy and persistence work to services.

The specification does not define quote data source, pricing values, quota sizes, rate-limit values, or administrative identity. This RFC defines interfaces and policy boundaries for those decisions and records them as open questions rather than assigning unsupported product values.

## 2. Functional Requirements

1. Serve a read-only quote using `GET /v1/quote`. A successful request returns a quote selected by the configured quote provider. The gateway does not expose quote mutation operations.
2. Create API keys for an organization using `POST /admin/keys`, subject to an authenticated administrative principal and the organization's plan and state.
3. Support key rotation: issue a replacement key and allow the old key to remain valid during a bounded overlap window, then revoke it. The overlap duration is policy configuration and must be decided before launch.
4. Revoke a key so subsequent authenticated requests are rejected.
5. Enforce each organization's plan-defined monthly request quota and short-term request rate limit.
6. Report usage using `GET /usage`, scoped to the caller's authorized organization or organizations and a defined time range.
7. Record durable usage data sufficient to support monthly quota decisions and usage reports.
8. Run multiple FastAPI instances without relying on instance-local limiter or quota state.

## 3. Non-Functional Requirements

- **Security:** never persist or log plaintext API keys; protect administrative routes; validate organization scope; use TLS at ingress and secret-managed credentials in deployments.
- **Consistency:** PostgreSQL is the source of truth for key status, plan assignment, and monthly quota. Redis is the shared short-window limiter.
- **Availability:** individual application instances are replaceable. Database, Redis, and quote-provider failures have explicit behavior and observability.
- **Scalability:** request handling is stateless across FastAPI instances; shared policy state is externalized to PostgreSQL and Redis.
- **Maintainability:** separate HTTP, application service, domain policy, and infrastructure layers; schema changes are versioned with Alembic.
- **Quality:** pytest covers policy and API behavior; Ruff enforces lint/format rules; mypy checks typed application boundaries.
- **Privacy:** usage records contain identifiers and request metadata needed for operations and reporting, not credentials or unnecessary payload data.

## 4. Assumptions

- An organization has one active plan assignment at a time. Plan changes take effect at an explicitly recorded boundary; exact proration policy is a product decision.
- A request that passes authentication and reaches quote execution counts toward usage, including quote-provider failures unless product policy specifies otherwise. Authentication failures do not count against the organization's quota.
- A calendar month in UTC defines a quota period. This avoids instance-local timezone differences; billing timezone and plan-specific reset behavior remain product decisions.
- API keys are bearer credentials sent in the `Authorization: Bearer` header.
- Administrative identity is provided by an upstream trusted identity mechanism or a separately configured admin credential mechanism. `POST /admin/keys` must not be exposed without one; its final identity provider is an open question.
- The quote provider is an abstract dependency because its implementation and data contract were not supplied.
- The plan contains at least a monthly request allowance and short-term rate policy. Actual values are configured as plan data and are not invented here.
- PostgreSQL and Redis are deployed as shared services accessible to all application instances. Docker Compose is the local integration environment, not the production availability topology.

## 5. Open Questions

1. What quote source is authoritative, what fields constitute a quote, and what freshness/cache policy is allowed?
2. Which identity provider or credential model authorizes `POST /admin/keys`? Can organization administrators manage only their own organization's keys?
3. What are the plan names, monthly quotas, short-term rate windows/limits, and overage behavior?
4. Should a quota-exhausted request return `429` or a distinct quota error/status, and should quota reset be calendar-month or subscription-anniversary based?
5. What is the key rotation overlap duration, and can a customer trigger rotation themselves?
6. Which usage report dimensions and retention duration are required? Should reporting be per-key, per-day, and/or per-endpoint?
7. Are key creation idempotent, and what is the required audit retention for admin actions?
8. What production deployment, backup, recovery-time, and recovery-point objectives apply?

## 6. High-Level Architecture

```text
Client â”€â”€ HTTPS â”€â”€> Load balancer / ingress â”€â”€> FastAPI instance(s)
                                                â”‚
                  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                  â”‚                             â”‚                           â”‚
           Auth/key service             Redis shared limiter         Quote provider
                  â”‚                             â”‚                           â”‚
                  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ PostgreSQL â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         organizations, plans, keys,
                         quota periods, usage, audit
```

Each FastAPI instance validates the bearer key by deriving its digest and looking up key metadata in PostgreSQL. It checks organization/key state and plan policy, obtains a shared Redis rate-limit decision, and makes an atomic PostgreSQL quota reservation before quote execution. The request outcome and usage event are persisted. The response is returned only after the selected accounting policy has been applied. Exact transaction boundaries and failure behavior are described below.

## 7. Component Responsibilities

- **API routers:** define paths, HTTP methods, status codes, request/response schemas, and dependency wiring. They do not implement policy or issue SQL directly.
- **Schemas:** validate external payloads and serialize stable response contracts. Secrets are write-only and excluded from logs and repr output.
- **Authentication service:** parses bearer credentials, computes the configured keyed digest, loads key/organization status, and returns an authenticated principal with organization and key identifiers.
- **Key management service:** creates, rotates, and revokes key records; applies organization scope and state rules; emits audit records.
- **Plan/policy service:** resolves quota and rate policy from the active plan. It is the single place that interprets plan entitlements.
- **Rate limiter adapter:** applies a Redis-backed atomic fixed-window decision shared across instances and returns the remaining/reset metadata required for headers. The selected window and boundary behavior are configuration/policy.
- **Quota/usage service:** reserves quota, persists outcome and aggregates/report data. PostgreSQL transactions protect quota decisions from concurrent requests.
- **Quote provider adapter:** isolates the external or internal quote source and maps its response into the public quote schema.
- **Persistence layer:** SQLAlchemy 2 models and repositories encapsulate PostgreSQL access. Alembic owns schema evolution.
- **Observability:** structured logs, metrics, and traces record request outcomes, dependency health, latency, and policy decisions without credential values.

## 8. Database Design

Use PostgreSQL 15 with SQLAlchemy 2 typed mappings. Names below are logical; physical naming conventions should be consistent and migrations must preserve constraints.

### `organizations`

- `id`: primary key (UUID recommended).
- `name`: required display name.
- `status`: active or suspended state.
- `created_at`, `updated_at`: UTC timestamps.

### `plans`

- `id`: primary key.
- `name`: unique plan identifier.
- `monthly_quota`: non-negative request allowance.
- `rate_limit_count`, `rate_limit_window_seconds`: short-term policy values.
- `active`: whether the plan can be assigned.
- timestamps.

### `organization_plan_assignments`

- `id`, `organization_id`, `plan_id` foreign keys.
- `effective_from`, nullable `effective_until` timestamps.
- `created_at`.
- Enforce at most one assignment effective at a given time for an organization through transactional service logic and an appropriate database constraint/index where supported.

### `api_keys`

- `id`: primary key.
- `organization_id`: required foreign key.
- `key_digest`: unique, non-null keyed digest; never plaintext.
- `key_prefix`: non-secret display/lookup aid, not sufficient to authenticate.
- `label`: customer-provided descriptive label.
- `status`: active, revoked, or expired.
- `created_at`, nullable `expires_at`, nullable `revoked_at`.
- `rotated_from_key_id`: nullable self-reference for rotation auditability.
- Index organization/status and enforce uniqueness of digest.

### `usage_periods`

- `organization_id`, `period_start`: composite key or unique pair defining the UTC calendar month.
- `request_count`: non-negative reserved/consumed request count.
- `updated_at`.
- The quota reservation operation must atomically create/increment only while below the applicable quota. Plan changes during a period require a product-defined rule.

### `usage_events`

- `id`: primary key (monotonic or UUID).
- `organization_id`, `api_key_id` foreign keys; retain key identifier after revocation as needed for reports, with deletion restricted or retention managed explicitly.
- `occurred_at`: UTC timestamp.
- `endpoint`, `outcome`, and optional bounded `http_status`/provider outcome fields.
- `request_id`: correlation identifier; unique only if an idempotency contract is introduced.
- Do not store bearer values, full authorization headers, or quote payloads unless explicitly justified.
- Index `(organization_id, occurred_at)` and `(api_key_id, occurred_at)` for reporting. Retention/partitioning is driven by measured volume and approved retention policy.

### `admin_audit_events`

- `id`, actor identifier, organization identifier, action, target identifier, timestamp, and sanitized metadata.
- Record key creation, rotation, revocation, plan assignment changes, and administrative failures where appropriate. Never include the secret key.

Foreign keys and check constraints should enforce non-negative counters and valid references. Database timestamps are stored consistently in UTC. Alembic migrations are the only supported schema change path.

## 9. API Design

All endpoints use JSON. TLS is mandatory outside local development. Error responses use a consistent object with a stable machine-readable `code`, human-readable `message`, and `request_id`; never expose stack traces or secrets.

### `GET /v1/quote`

- **Auth:** required bearer API key.
- **Success:** `200 OK`, quote object supplied by the quote provider. The exact fields depend on the unresolved provider contract.
- **Headers:** include request correlation and rate-limit status where available; do not disclose sensitive policy internals.
- **Errors:** `401` missing/invalid/revoked key; `403` inactive organization or disallowed access; `429` short-term rate or monthly quota exhausted; `503` unavailable required dependency/provider according to failure policy.
- Read-only: no request body and no mutating operation.

### `POST /admin/keys`

- **Auth:** required administrative identity, separate from customer API key authentication.
- **Request:** organization identifier, descriptive label, and optional expiry if the product permits it. Rotation can reference the old key identifier; whether this uses the same endpoint or a dedicated action is an API contract decision. This RFC recommends explicit `rotation_of_key_id` in the request to make intent auditable.
- **Success:** `201 Created`; return key identifier, prefix, metadata, and the plaintext key exactly once. Do not include it in subsequent reads or logs.
- **Errors:** `400` invalid input; `401` unauthenticated admin; `403` unauthorized organization scope; `404` unknown organization/key; `409` invalid state transition.
- Revoke behavior must be exposed through an administrative operation. The required endpoint list does not specify its path, so a path and method must be agreed before implementation; a conventional design is `DELETE /admin/keys/{key_id}`. It is listed here as a contract gap, not a required endpoint already present in the specification.

### `GET /usage`

- **Auth:** authenticated customer or administrative principal, scoped to authorized organization(s).
- **Query:** `from` and `to` UTC timestamps; optional key identifier if role permits. Validate range ordering and maximum range according to reporting policy.
- **Success:** `200 OK`; return organization identifier, requested interval, request count, and supported breakdowns (at minimum aggregate usage). Response granularity and retention depend on product decisions.
- **Errors:** `401`, `403`, `400` for invalid ranges, and `503` if the authoritative report store is unavailable.

## 10. Authentication & Authorization

1. Extract exactly one bearer token from the Authorization header. Reject missing, malformed, or ambiguous credentials.
2. Validate length and accepted key format before digest computation to bound input work. Keys are generated from a cryptographically secure random source; the exact encoding and visible prefix are fixed as a versioned format.
3. Compute a keyed digest using a server-held secret (HMAC-SHA-256 is the proposed baseline) and compare/lookup without storing plaintext. Keep the digest secret outside the database and rotate it through a versioned key strategy; existing records must remain verifiable during migration.
4. Fetch key and organization state; reject revoked, expired, suspended, or otherwise inactive identities. Cache decisions only if revocation propagation is bounded and explicitly designed; baseline behavior uses the authoritative database lookup.
5. Authorize endpoint actions against the principal. A customer key may call only the Quotes API. Administrative key creation requires an admin principal and organization-level authorization. Usage reports must never allow cross-organization access without explicit administrative scope.
6. Use generic authentication errors so responses do not reveal whether a particular key exists.

## 11. Security Design

- Generate keys with a cryptographically secure random generator and sufficient entropy; return the secret once. Persist only a keyed one-way digest and non-sensitive prefix.
- Use a dedicated secret-management mechanism for the digest key, database credentials, and Redis credentials. Do not commit secrets or place them in container images.
- Enforce HTTPS at the ingress, restrict network access to PostgreSQL and Redis, and use least-privilege database roles. Application DB role should not perform schema migrations; migrations use a separate deployment role.
- Validate all input with Pydantic schemas, use SQLAlchemy bound parameters, and limit payload and query sizes.
- Redact Authorization headers, raw keys, and secret-bearing request bodies from logs, traces, exceptions, and metrics labels.
- Apply admin authorization, organization scoping, audit records, and rate protection to administrative operations.
- Keep dependency versions controlled and scan/update them through the project's normal maintenance process.
- Define backup encryption, access control, restoration checks, and retention before production launch.
- Revocation must take effect promptly. Because baseline authentication reads PostgreSQL, successful revocation is authoritative on the next request; any later cache must define and meet a revocation propagation bound.

## 12. Rate Limiting Strategy

Use Redis as a shared short-term limiter across all FastAPI instances. A fixed-window counter keyed by a non-secret stable API key identifier (or its digest-derived identifier) and policy window is the baseline because it is atomic and straightforward to operate. Use a Redis atomic operation/script so concurrent instances cannot exceed the configured counter through read-modify-write races. Set expiry aligned to the selected window. Return `429` with `Retry-After` and standard rate-limit headers where policy permits.

The plan supplies limit count and window. The exact algorithm, window alignment, and whether the limit is per key, organization, or both are open product decisions; baseline recommendation is per key with an additional organization-level ceiling only if plans require it. Do not use raw key material in Redis keys. Redis key construction must include environment and policy version to avoid collisions.

Monthly quota is separate from the Redis short-window limiter and is authoritative in PostgreSQL. Reserve quota atomically using a conditional update/insert within a transaction; if no capacity remains, reject with `429`. A request must not be admitted based on an eventually consistent local counter. Define whether failed quote-provider calls consume a reservation; the assumption in this RFC is yes once execution begins. Redis unavailability fails closed for the short-term limiter by returning `503`; an explicit product decision may choose a bounded fallback, but per-instance in-memory limiting would not provide the required shared enforcement.

## 13. Usage Tracking

For each authenticated request admitted for execution, create a durable usage event and update the corresponding organization/month counter. Ensure a consistent transaction boundary so usage reporting and quota accounting do not silently diverge. A practical baseline is: transactionally reserve quota and insert a pending usage record before provider execution; after execution, update outcome/status in a second transaction. If execution terminates before outcome update, a pending event remains observable and can be reconciled operationally. Whether quota reservation is refunded for failures is a product policy; this RFC assumes no refund after execution begins.

`GET /usage` reads PostgreSQL, scopes every query by authorized organization, and supports UTC time filters. Aggregate queries should use the indexed event table or period counters according to requested detail. Do not calculate monthly quota solely from delayed asynchronous events. If reporting volume later makes direct queries too costly, introduce maintained rollups while preserving a defined source of truth and reconciliation process.

## 14. Scaling Strategy

- Run multiple stateless FastAPI instances behind a load balancer. No correctness-critical session or limiter state lives in process memory.
- Share PostgreSQL and Redis across instances. Use SQLAlchemy connection pooling sized to aggregate deployment capacity; account for total connections across all replicas and administrative jobs.
- Scale app instances horizontally based on observed load and latency. Scale PostgreSQL and Redis using operational capacity evidence; no benchmark figures are assumed by this RFC.
- Keep quote-provider calls behind timeouts and bounded concurrency. Connection and timeout settings are configuration, tuned from measurements.
- Add indexes for known lookup paths and use explain plans before adding speculative indexes.
- At higher usage-event volume, evaluate time partitioning and asynchronous rollups against actual storage and query patterns.
- Docker Compose provides reproducible local development with application, PostgreSQL, and Redis dependencies. Production requires managed or separately operated stateful services with backups, monitoring, and failover.

## 15. Failure Scenarios & Recovery

| Failure | Expected behavior | Recovery / operations |
|---|---|---|
| PostgreSQL unavailable | Do not authenticate or admit requests whose key/quota status cannot be established; return `503`. | Restore DB connectivity; health checks distinguish readiness from liveness; retry only bounded/idempotent operations. |
| Redis unavailable | Fail short-term limiter closed with `503`; do not silently switch to per-instance counters. | Restore Redis; inspect connectivity and limiter errors; shared counters resume according to their TTL. |
| Quote provider timeout/error | Return sanitized `503`/gateway error; record outcome under the usage policy. | Enforce client timeout, alert on sustained failures, restore provider; avoid unbounded retries. |
| Application instance crash | In-flight request may fail; other instances continue. | Load balancer removes unhealthy instance; pending usage records can be inspected/reconciled. |
| Revocation races with request | Requests authenticated before revocation may complete; later DB-backed checks reject the key. | Document this boundary; audit revocation timestamp and request IDs. |
| Duplicate key-creation submission | Do not issue duplicate secrets without an explicit idempotency contract. | Use request idempotency only after defining storage, expiry, and replay semantics. |
| Quota concurrency | Conditional DB update/transaction prevents concurrent over-admission. | Monitor rejected quota updates and transaction contention; adjust schema/query based on evidence. |
| Migration failure | Application deployment must not proceed on an incompatible schema. | Use reviewed forward migrations, backups, and a tested restore path; avoid automatic destructive migration at app startup. |

Liveness checks should report process health only. Readiness checks should include required dependencies so traffic is not routed to an instance that cannot enforce policy. Avoid health endpoints exposing secrets or infrastructure detail.

## 16. Alternatives Considered

- **Store plaintext API keys:** rejected because a database read or backup leak would immediately expose customer credentials.
- **Unsalted ordinary SHA-256 digest:** insufficient against offline guessing if key entropy is ever weaker than expected and does not support straightforward server-side digest-key rotation. A keyed HMAC digest is the baseline.
- **In-memory rate limiter:** rejected because counters diverge across instances and reset on process restart.
- **PostgreSQL-only short-term limiter:** possible, but adds write contention to the primary relational store for high-frequency counters; Redis is explicitly required for shared limiter state.
- **Redis-only monthly quota:** rejected because expiration, eviction, and loss can undermine durable entitlement accounting and usage reporting.
- **Asynchronous-only usage accounting:** rejected for quota enforcement because event lag can admit requests beyond the monthly allowance. Async aggregation may later supplement durable synchronous accounting.
- **Central gateway product/service:** not selected because no such product is specified and the required stack centers on FastAPI. It can be revisited if platform capabilities change.

## 17. Risks

- Unspecified admin authentication and quote-provider contracts block final API schemas and deployment boundaries.
- Redis outage policy trades availability for correct shared rate enforcement; fail-closed behavior can reduce service availability.
- Synchronous durable usage writes increase request-path database work and can create contention under high concurrency.
- HMAC digest-key rotation requires versioning and a migration path; losing the secret makes stored digests unusable for authentication.
- A rotation overlap period leaves two active credentials temporarily and requires precise lifecycle and audit rules.
- Plan changes and quota reservation semantics can create billing disputes if reset, overage, and failure-counting rules are left ambiguous.
- Usage retention and reporting granularity affect database size, privacy, and query performance.
- Revocation cannot cancel work already admitted and executing; clients and administrators need this behavior documented.

## 18. Limitations

- The RFC cannot define quote response fields or freshness without a provider contract.
- It specifies required capabilities but does not assign plan prices, quota amounts, or rate limits.
- It does not define a production cloud provider, deployment orchestrator, service-level objective, or recovery objective.
- It describes a database-backed usage path; high-volume reporting may need rollups or partitioning after measured growth.
- It does not include implementation code or benchmark claims.
- The required endpoint list omits an explicit revocation endpoint and rotation contract; these must be finalized before the API is considered complete.

## 19. Future Improvements

- Add customer self-service key listing with secrets always redacted.
- Add a dedicated rotation/revocation API contract, idempotency support, and optional scheduled expiry after product decisions.
- Add plan and quota administration with effective-dated audit history.
- Add per-key and per-organization usage rollups if query measurements justify them.
- Add configurable burst algorithms, such as token bucket, if fixed-window boundary bursts prove problematic.
- Add key anomaly detection, customer notifications, and automated abuse controls.
- Add a quote cache only when provider freshness and licensing rules are known.
- Add tenant export/deletion workflows aligned with retention and legal requirements.

## 20. Four-week Implementation Roadmap

### Week 1 â€” Service and persistence foundation

- Establish typed FastAPI application structure, configuration, dependency wiring, and structured request correlation.
- Configure SQLAlchemy 2 sessions and PostgreSQL connectivity; create initial Alembic schema for organizations, plans, assignments, keys, periods, usage, and audit events.
- Add Docker Compose local dependencies and health/readiness behavior.
- Define error envelope and external schema conventions.

### Week 2 â€” Identity, key lifecycle, and policy

- Implement key generation, one-time display, keyed digest persistence, authentication, organization authorization, creation, rotation semantics, and revocation contract.
- Implement plan lookup and transaction-safe monthly quota reservation.
- Add the administrative identity integration selected by product/security owners.
- Add audit records and ensure secrets are redacted throughout observability.

### Week 3 â€” Quote path, Redis limiter, and usage

- Implement quote-provider adapter and `GET /v1/quote` against the approved provider schema.
- Implement atomic shared Redis short-window limiting and documented dependency failure behavior.
- Persist request usage/outcome and implement organization-scoped `GET /usage` with UTC range validation.
- Add indexes and query review for the agreed reporting needs.

### Week 4 â€” Hardening and release readiness

- Complete pytest coverage for authentication, authorization, rotation/revocation, concurrency-sensitive quota behavior, limiter behavior, reporting scope, and dependency failures.
- Apply Ruff and mypy checks; review migration safety and startup/readiness behavior.
- Exercise multi-instance local deployment against shared Redis/PostgreSQL and verify policy state is not process-local.
- Complete security review, operational dashboards/alerts, backup/restore procedure, API documentation, and launch checklist based on measured behavior.

The roadmap order depends on timely decisions for the open questions, especially admin identity, quote contract, plan values, and revocation/rotation API shape.
