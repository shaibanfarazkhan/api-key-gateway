# API Key Gateway â€” Engineering RFC

**Status:** Design reference. The Task 2 checklist below reflects the current repository; target design details not implemented are marked as limitations or Future Work.
**Scope:** Phase 1 design for a production-grade gateway to a read-only Quotes API
**Runtime baseline:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, Docker Compose, pytest, Ruff, Black, and mypy

## 1. Executive Summary

This RFC describes an API Key Gateway that authenticates organization-owned keys and serves a read-only Quotes API. The implemented endpoints are `GET /v1/quote`, `/admin` operations including `POST /admin/api-keys`, and `GET /usage`. The checklist below distinguishes the delivered behavior from the broader design target.

PostgreSQL is the authoritative store for organizations, plans, API key metadata, monthly quota accounting, and durable usage records. Redis is shared by all FastAPI instances and holds short-lived rate-limit counters. API key material is shown only at creation and is stored as a SHA-256 digest; generated API keys contain 256 bits of random secret material, and authentication never requires storing the original key. FastAPI routes remain thin and delegate policy and persistence work to services.

The specification does not define quote data source, pricing values, quota sizes, rate-limit values, or administrative identity. Those remain product or deployment decisions; the application currently returns a dummy quote and uses a shared configured admin bearer credential.

## 2. Functional Requirements

1. **Partially completed:** `GET /v1/quote` serves a read-only deterministic placeholder. A provider integration is outside the delivered scope.
2. **Partially completed:** API keys are created at `POST /admin/api-keys` under the shared admin credential. The route checks that the organization exists; it does not require an active plan, check organization state, or enforce organization-scoped admin roles. This route name is the shipped API and is preserved for compatibility; `/admin/keys` is not implemented.
3. **Completed:** rotation issues a replacement key, keeps the old key valid for the configured overlap (`API_KEY_ROTATION_GRACE_SECONDS`), then rejects it.
4. **Completed:** admins can revoke keys and authentication rejects revoked keys.
5. **Completed:** an organization's active plan controls its monthly quota and per-minute sliding-window limit.
6. **Partially completed:** `GET /usage` is scoped to the authenticated organization and reports current-month totals with optional daily breakdown. Date-range and per-key filters are not implemented.
7. **Partially completed:** monthly and daily aggregate usage is durable and supports quota/reporting. Per-request usage events and provider outcomes are not stored.
8. **Completed:** Redis provides shared limiter state and PostgreSQL persists key and usage state across application instances.

## Task 2 submission checklist

| Requirement | Status | Delivered behavior / boundary |
| --- | --- | --- |
| Organization and plan administration | Completed | Admin operations create organizations/plans and assign a plan. |
| API key lifecycle mechanics | Completed | Keys are returned once; only SHA-256 digests are stored; rotation overlap is configurable. |
| Key issuance authorization and organization eligibility | Partially completed | Admin authentication and organization existence are checked; active-plan, organization-state, and per-organization admin-scope checks are not applied during creation. |
| Administrative authentication | Completed | Every `/admin` route requires the configured shared admin bearer key. |
| Monthly quota and shared rate limiting | Completed | PostgreSQL usage accounting and Redis organization sliding window. |
| Usage reporting | Partially completed | Current UTC month and optional daily breakdown; no arbitrary date range or per-key filter. |
| Audit logging | Partially completed | Successful key lifecycle and plan assignment events; generic `admin` actor, no failed-attempt events. |
| Redis limiter benchmark at 200 requests/second | Completed | Results, including the p95 threshold, are in `BENCHMARK.md`; EVALSHA did not outperform EVAL. |
| Full-request-path performance benchmark | Completed | Before/after results and the measured plan-query optimization are in `PERFORMANCE.md`. |
| External quote-provider integration | Out of scope | No provider contract or source was supplied; `/v1/quote` is a placeholder. |
| Production identity provider, TLS, managed secrets and operations | Out of scope | Deployment-specific controls; shared admin credential is the application baseline. |
| Per-request usage event store and historical reporting filters | Out of scope | The delivered accounting/reporting API uses monthly and daily aggregates. |

The current repository implementation and its boundaries are authoritative for
submission status. Sections below describe the design model and operational
considerations; where they differ from the implementation, this checklist and
the explicit limitation notes take precedence.

## 3. Non-Functional Requirements

- **Security:** never persist or log plaintext API keys; protect administrative routes; validate organization scope; use TLS at ingress and secret-managed credentials in deployments.
- **Consistency:** PostgreSQL is the source of truth for key status, plan assignment, and monthly quota. Redis is the shared short-window limiter.
- **Availability:** individual application instances are replaceable. Redis failure returns `503`; a quote-provider integration and full dependency observability are not implemented.
- **Scalability:** request handling is stateless across FastAPI instances; shared policy state is externalized to PostgreSQL and Redis.
- **Maintainability:** separate HTTP, application service, domain policy, and infrastructure layers; schema changes are versioned with Alembic.
- **Quality:** pytest covers implemented policy and API behavior; Ruff, Black, and mypy checks are configured in CI.
- **Privacy:** usage records contain identifiers and request metadata needed for operations and reporting, not credentials or unnecessary payload data.

## 4. Assumptions

- An organization has one active plan assignment at a time. Plan changes take effect at an explicitly recorded boundary; exact proration policy is a product decision.
- A request that passes authentication and reaches quote execution counts toward usage, including quote-provider failures unless product policy specifies otherwise. Authentication failures do not count against the organization's quota.
- A calendar month in UTC defines a quota period. This avoids instance-local timezone differences; billing timezone and plan-specific reset behavior remain product decisions.
- API keys are bearer credentials sent in the `Authorization: Bearer` header.
- The current implementation protects every `/admin` route with a separately configured shared `ADMIN_API_KEY` bearer credential. This does not provide individual identity, role or organization scope, or actor attribution; a production identity provider remains an operational decision.
- The quote provider is an abstract dependency because its implementation and data contract were not supplied.
- The plan contains at least a monthly request allowance and short-term rate policy. Actual values are configured as plan data and are not invented here.
- PostgreSQL and Redis are deployed as shared services accessible to all application instances. Docker Compose is the local integration environment, not the production availability topology.

## 5. Open Questions

1. What quote source is authoritative, what fields constitute a quote, and what freshness/cache policy is allowed?
2. Is the shared `ADMIN_API_KEY` acceptable for production, or should an identity provider authorize administrators and scope them to organizations?
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

Each FastAPI instance validates the bearer key by deriving its digest and looking up key metadata in PostgreSQL. It checks organization/key state and plan policy, obtains a shared Redis rate-limit decision, and makes an atomic PostgreSQL quota reservation before returning the placeholder quote. Monthly and daily aggregates are persisted; the current implementation does not create per-request usage events.

## 7. Component Responsibilities

- **API routers:** define paths, HTTP methods, status codes, request/response schemas, and dependency wiring. They do not implement policy or issue SQL directly.
- **Schemas:** validate external payloads and serialize stable response contracts. Secrets are write-only and excluded from logs and repr output.
- **Authentication service:** parses bearer credentials, computes the SHA-256 digest, loads key/organization status, and returns an authenticated principal with organization and key identifiers.
- **Key management service:** creates, rotates, and revokes key records; applies organization scope and state rules; emits audit records.
- **Plan/policy service:** resolves quota and rate policy from the active plan. It is the single place that interprets plan entitlements.
- **Rate limiter adapter:** applies a Redis-backed atomic organization sliding-window decision shared across instances and returns `Retry-After` on rejection.
- **Quota/usage service:** reserves quota and persists monthly/daily aggregates. PostgreSQL transactions protect quota decisions from concurrent requests.
- **Quote provider adapter:** **Future Work.** The current route returns a deterministic placeholder because no provider contract was supplied.
- **Persistence layer:** SQLAlchemy 2 models and repositories encapsulate PostgreSQL access. Alembic owns schema evolution.
- **Observability:** **Future Work.** Metrics, traces, readiness checks, and operational dashboards are not implemented by this repository.

## 8. Database Design

The following is the broader target model. The delivered schema currently uses
the `organization_plans` association, per-key `usage_records` and
`daily_usage_records` aggregates, `audit_logs`, and `idempotency_records`; it
does not include effective-dated plan assignments or per-request usage events.
The database implementation uses PostgreSQL with SQLAlchemy 2 typed mappings
and Alembic migrations.

### `organizations`

- `id`: primary key (UUID recommended).
- `name`: required display name.
- `status`: active or suspended state.
- `created_at`, `updated_at`: UTC timestamps.

### `plans`

- `id`: primary key.
- `name`: unique plan identifier.
- `monthly_quota`: non-negative request allowance.
- `requests_per_minute`: non-negative organization-level sliding-window limit.
- `active`: whether the plan can be assigned.
- timestamps.

### `organization_plan_assignments`

**Future Work:** effective-dated plan assignment history is not represented in
the current schema; the current application keeps one assigned plan per
organization.

- `id`, `organization_id`, `plan_id` foreign keys.
- `effective_from`, nullable `effective_until` timestamps.
- `created_at`.
- Enforce at most one assignment effective at a given time for an organization through transactional service logic and an appropriate database constraint/index where supported.

### `api_keys`

- `id`: primary key.
- `organization_id`: required foreign key.
- `key_hash`: unique, non-null SHA-256 digest of the high-entropy generated key; never plaintext.
- `prefix`: non-secret display aid, not sufficient to authenticate.
- `status`: active or revoked; expiration is represented by `expires_at`.
- `created_at`, nullable `expires_at`, nullable `revoked_at`.
- `rotation_expires_at`: overlap deadline on the old key; `rotated_from_id` links a replacement to its predecessor.
- Index organization/status and enforce uniqueness of digest.

### `usage_periods`

- `organization_id`, `period_start`: composite key or unique pair defining the UTC calendar month.
- `request_count`: non-negative reserved/consumed request count.
- `updated_at`.
- The quota reservation operation must atomically create/increment only while below the applicable quota. Plan changes during a period require a product-defined rule.

### `usage_events`

**Future Work:** current usage is recorded in monthly and daily aggregate tables;
individual request events and outcomes are not persisted.

- `id`: primary key (monotonic or UUID).
- `organization_id`, `api_key_id` foreign keys; retain key identifier after revocation as needed for reports, with deletion restricted or retention managed explicitly.
- `occurred_at`: UTC timestamp.
- `endpoint`, `outcome`, and optional bounded `http_status`/provider outcome fields.
- `request_id`: correlation identifier; unique only if an idempotency contract is introduced.
- Do not store bearer values, full authorization headers, or quote payloads unless explicitly justified.
- Index `(organization_id, occurred_at)` and `(api_key_id, occurred_at)` for reporting. Retention/partitioning is driven by measured volume and approved retention policy.

### `audit_logs` (current implementation)

The current audit table records successful API key creation, rotation,
revocation, and plan assignment. Its fields are `id`, `event_type`, `actor`,
nullable `organization_id`, `resource_type`, `resource_id`, `details`, and
`created_at`. The actor is the shared `admin` principal; individual identities
and failed admin attempts are not recorded. Details are sanitized and never
include plaintext keys.

Foreign keys and check constraints should enforce non-negative counters and valid references. Database timestamps are stored consistently in UTC. Alembic migrations are the only supported schema change path.

## 9. API Design

Endpoints use JSON. TLS is required outside local development and must be configured at the deployment ingress. The current application returns FastAPI's standard error detail format; a shared error envelope with `code`, `message`, and `request_id` is not implemented. Responses do not intentionally expose stack traces or secrets.

### `GET /v1/quote`

- **Auth:** required bearer API key.
- **Success:** `200 OK`, quote object supplied by the quote provider. The exact fields depend on the unresolved provider contract.
- **Headers:** include request correlation and rate-limit status where available; do not disclose sensitive policy internals.
- **Errors:** `401` missing/invalid/revoked key; `403` inactive organization or disallowed access; `429` short-term rate or monthly quota exhausted; `503` unavailable required dependency/provider according to failure policy.
- Read-only: no request body and no mutating operation.

### `POST /admin/api-keys`

- **Auth:** required administrative identity, separate from customer API key authentication.
- **Request:** organization identifier and optional expiry. The current API does not accept a label; rotation uses the dedicated `POST /admin/api-keys/{key_id}/rotate` operation.
- **Success:** `201 Created`; return key identifier, prefix, metadata, and the plaintext key exactly once. Do not include it in subsequent reads or logs.
- **Errors:** `400` invalid input; `401` unauthenticated admin; `403` unauthorized organization scope; `404` unknown organization/key; `409` invalid state transition.
- Revoke behavior is exposed as `POST /admin/api-keys/{key_id}/revoke`.

### `GET /usage`

- **Auth:** authenticated customer API key, scoped to its organization.
- **Query:** optional `include_daily` boolean. The current API reports the UTC current month; it does not accept arbitrary time ranges or key filters.
- **Success:** `200 OK`; return organization and plan metadata, current-month request count, monthly limit, remaining quota, percentage used, and optionally daily counts.
- **Errors:** authentication errors use `401`; an inactive organization returns `403`.

## 10. Authentication & Authorization

1. Extract exactly one bearer token from the Authorization header. Reject missing, malformed, or ambiguous credentials.
2. **Future Work:** validate accepted key format and maximum length before digest computation. Current authentication hashes the presented bearer value and compares against stored digests; generated keys use a cryptographically secure random source and an `ak_` prefix.
3. Compute a SHA-256 digest of the high-entropy generated key and look it up without storing plaintext. If key generation or entropy guarantees change, reassess a server-keyed HMAC digest and its versioned rotation strategy.
4. Fetch key and organization state; reject revoked, expired, suspended, or otherwise inactive identities. Cache decisions only if revocation propagation is bounded and explicitly designed; baseline behavior uses the authoritative database lookup.
5. Authorize endpoint actions against the principal. The current implementation restricts customer keys to customer routes and scopes usage to their organization. Admin access is a shared configured bearer credential; organization-scoped admin roles are not implemented.
6. Use generic authentication errors so responses do not reveal whether a particular key exists.

## 11. Security Design

- Generate keys with a cryptographically secure random generator and sufficient entropy; return the secret once. Persist only a SHA-256 digest and non-sensitive prefix. The digest is not keyed; generated keys have high entropy.
- Use a dedicated secret-management mechanism for the digest key, database credentials, and Redis credentials. Do not commit secrets or place them in container images.
- Enforce HTTPS at the ingress, restrict network access to PostgreSQL and Redis, and use least-privilege database roles. Application DB role should not perform schema migrations; migrations use a separate deployment role.
- Validate all input with Pydantic schemas, use SQLAlchemy bound parameters, and limit payload and query sizes.
- Redact Authorization headers, raw keys, and secret-bearing request bodies from logs, traces, exceptions, and metrics labels.
- Apply admin authorization, organization scoping, audit records, and rate protection to administrative operations.
- Keep dependency versions controlled and scan/update them through the project's normal maintenance process.
- Define backup encryption, access control, restoration checks, and retention before production launch.
- Revocation must take effect promptly. Because baseline authentication reads PostgreSQL, successful revocation is authoritative on the next request; any later cache must define and meet a revocation propagation bound.

## 12. Rate Limiting Strategy

The implementation uses Redis as a shared organization-level sliding-window limiter across FastAPI instances. An atomic Lua script prevents concurrent instances from exceeding the configured per-minute plan limit. Redis keys contain the environment and organization identifier, not raw key material. Excess requests receive `429` with `Retry-After`; standard rate-limit headers are not currently returned.

The plan supplies a per-minute request count. The current policy is organization-level; the limit is not per key. The Redis key includes the environment and organization identifier and never contains raw key material. Redis unavailability fails closed with `503`; the service does not switch to per-instance counters.

Monthly quota is separate from the Redis short-window limiter and is authoritative in PostgreSQL. Reserve quota atomically using a conditional update/insert within a transaction; if no capacity remains, reject with `429`. A request must not be admitted based on an eventually consistent local counter. Define whether failed quote-provider calls consume a reservation; the assumption in this RFC is yes once execution begins. Redis unavailability fails closed for the short-term limiter by returning `503`; an explicit product decision may choose a bounded fallback, but per-instance in-memory limiting would not provide the required shared enforcement.

## 13. Usage Tracking

The current implementation atomically reserves monthly quota and increments monthly and daily aggregates in PostgreSQL before returning the deterministic quote. Idempotent retries with the same API key and `Idempotency-Key` are counted once within 24 hours. It does not persist per-request events or outcome/status fields; those are a possible extension if the reporting contract requires them.

`GET /usage` reads PostgreSQL and scopes queries to the authenticated organization. It reports the current UTC month and optionally daily counts. Date-range and per-key filters are not part of the current API.

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
- **Unsalted ordinary SHA-256 digest:** acceptable for the current 256-bit randomly generated keys; reassess if externally chosen or lower-entropy keys are introduced. A keyed HMAC digest would add protection against weaker keys and support server-side digest-key rotation.
- **In-memory rate limiter:** rejected because counters diverge across instances and reset on process restart.
- **PostgreSQL-only short-term limiter:** possible, but adds write contention to the primary relational store for high-frequency counters; Redis is explicitly required for shared limiter state.
- **Redis-only monthly quota:** rejected because expiration, eviction, and loss can undermine durable entitlement accounting and usage reporting.
- **Asynchronous-only usage accounting:** rejected for quota enforcement because event lag can admit requests beyond the monthly allowance. Async aggregation may later supplement durable synchronous accounting.
- **Central gateway product/service:** not selected because no such product is specified and the required stack centers on FastAPI. It can be revisited if platform capabilities change.

## 17. Risks

- The shared admin credential does not provide individual attribution or organization-level authorization; a production identity policy remains to be selected. The quote-provider contract is also open.
- Redis outage policy trades availability for correct shared rate enforcement; fail-closed behavior can reduce service availability.
- Synchronous durable usage writes increase request-path database work and can create contention under high concurrency.
- If a server-keyed HMAC digest is adopted later, rotation requires versioning and a migration path; losing the secret would make stored digests unusable for authentication.
- A rotation overlap period leaves two active credentials temporarily and requires precise lifecycle and audit rules.
- Plan changes and quota reservation semantics can create billing disputes if reset, overage, and failure-counting rules are left ambiguous.
- Usage retention and reporting granularity affect database size, privacy, and query performance.
- Revocation cannot cancel work already admitted and executing; clients and administrators need this behavior documented.

## 18. Limitations

- The RFC cannot define quote response fields or freshness without a provider contract.
- It specifies required capabilities but does not assign plan prices, quota amounts, or rate limits.
- It does not define a production cloud provider, deployment orchestrator, service-level objective, or recovery objective.
- It describes a database-backed usage path; high-volume reporting may need rollups or partitioning after measured growth.
- It does not provide a production quote-provider integration, individual admin identities, historical usage filters, per-request usage events, or production deployment controls.
- The implemented admin key paths are `/admin/api-keys`, `/admin/api-keys/{key_id}/rotate`, and `/admin/api-keys/{key_id}/revoke`; they are listed in the README and are the compatibility contract for this repository.
- Redis limiter results are recorded in `BENCHMARK.md`; full-request-path measurements are recorded separately in `PERFORMANCE.md`.

## 19. Future Work

- Add customer self-service key listing with secrets always redacted.
- Add a dedicated rotation/revocation API contract, idempotency support, and optional scheduled expiry after product decisions.
- Add plan and quota administration with effective-dated audit history.
- Add per-key and per-organization usage rollups if query measurements justify them.
- Add configurable burst algorithms, such as token bucket, if fixed-window boundary bursts prove problematic.
- Add key anomaly detection, customer notifications, and automated abuse controls.
- Add a quote cache only when provider freshness and licensing rules are known.
- Add tenant export/deletion workflows aligned with retention and legal requirements.

## 20. Future Work Roadmap (Original plan; not implementation status)

The following roadmap is historical planning material. Its items are not claims
that those capabilities are present in the current repository.

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
