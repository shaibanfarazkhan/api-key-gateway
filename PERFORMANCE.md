# Performance Benchmarking

## Test environment

| Component | Measured/configured environment |
| --- | --- |
| Benchmark date | 2026-11-24 |
| Host OS | Windows (Docker Desktop host); exact edition/build unavailable |
| Host CPU / RAM | Not captured; Windows hardware inventory access was denied |
| Benchmark client | Python 3.13.12, `httpx` 0.28.1 on the host |
| API runtime | `python:3.11-slim`, one Uvicorn worker |
| Database | PostgreSQL 16 Alpine container |
| Rate limiter | Redis 7 Alpine container |
| Service placement | API, PostgreSQL, and Redis in local Docker Compose; benchmark client on the host |

The stack was already running when the initial run began. The API image was
rebuilt from the same Dockerfile and restarted before the optimized run. At the
time of these benchmark runs, the Dockerfile installed ranged dependencies
without a committed runtime lock, so dependency-version drift across that
rebuild cannot be ruled out. The current Docker build installs dependencies
from `uv.lock` and uses the stable mypy pin documented in the CI setup. Host CPU
and memory are omitted because the environment did not permit querying them.

## Methodology

The benchmark is an external HTTP client calling `GET /v1/quote`. It reuses
one `httpx.AsyncClient` and its keep-alive connections, sends a fixed number of
requests with a bounded number in flight, times each request with a monotonic
clock, and counts non-2xx responses and transport errors as failures. Average
and nearest-rank p95 include failed attempts. Throughput is attempted requests
divided by total run time.

Both runs used 1,000 requests at concurrency 50. Each run had a dedicated,
fresh organization, API key, and active plan configured for 120,000 requests
per minute and a monthly quota of 5,000. This kept rate-limit and quota
rejections out of the results. The reported values are single runs, not
multi-trial medians; expect run-to-run variation.

## Before optimization

The baseline used the original quote request path, which fetched and validated
the active plan separately in the rate-limit service and quota service.

| Result | Baseline |
| --- | ---: |
| Average latency | 914.55 ms |
| P95 latency | 1,908.88 ms |
| Throughput | 53.71 requests/s |
| Successful / failed | 1,000 / 0 |
| Elapsed time | 18.62 s |

## Bottleneck identified

The benchmark exposed expensive tail latency under concurrency, and code-path
inspection found avoidable database reads on every quote. Authentication
already loaded the API key and organization, but then both the rate-limit and
quota services separately loaded the organization and its plans. That meant
re-fetching the same policy data twice for each request. The benchmark did not
include SQL tracing, so database time was not isolated from Redis, quota
reservation, or HTTP overhead; the plan lookups are a measured-workload
bottleneck candidate supported by the request path, not a separately timed
database profile.

## Optimization applied

Authentication now eagerly loads the organization's plans with the key and
organization. The quote route validates the single active plan once and passes
it to both the rate limiter and quota service. This removes the two repeated
organization-plus-plan reads from the quote path while retaining the service
fallback behavior for callers that do not pass a plan. Quota reservation and
the Redis sliding-window policy remain in place.

## After optimization

The optimized run used the same request count, concurrency, rate limit, quota,
host client, and dependency placement as the baseline, with a fresh organization
and counters.

| Result | Before | After | Change |
| --- | ---: | ---: | ---: |
| Average latency | 914.55 ms | 708.70 ms | 205.85 ms lower |
| P95 latency | 1,908.88 ms | 1,348.42 ms | 560.46 ms lower |
| Throughput | 53.71 requests/s | 69.08 requests/s | 15.37 requests/s higher |
| Successful / failed | 1,000 / 0 | 1,000 / 0 | — |
| Elapsed time | 18.62 s | 14.48 s | 4.14 s shorter |

The observed after run had lower average and p95 latency and higher throughput.
Because these are single trials and the host CPU/RAM could not be recorded, the
figures describe this local run and should not be treated as a capacity guarantee.
