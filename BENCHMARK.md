# Redis Rate Limiter Benchmark

## Environment

The benchmark targets the Redis 7 service defined in `docker-compose.yml` and
uses the host Python environment installed with `uv`. It times Redis command
round trips for the production sliding-window Lua script. It does not include
FastAPI, PostgreSQL, authentication, or quota-accounting latency.

The planned comparison offers 200 requests per second for 30 seconds (6,000
measured requests per mode), with 20 unmeasured warm-up calls. The benchmark
reports achieved throughput and nearest-rank p50, p95, and p99 latency.

## Commands

Start Redis and run the original full-script `EVAL` baseline and cached `EVALSHA`
implementation with the same settings:

```powershell
docker compose up -d redis
uv run python -m scripts.benchmark_rate_limiter --redis-url redis://localhost:6379/0 --mode eval --rate 200 --duration 30
uv run python -m scripts.benchmark_rate_limiter --redis-url redis://localhost:6379/0 --mode evalsha --rate 200 --duration 30
```

## Results

| Measurement | EVAL baseline | EVALSHA optimized |
| --- | ---: | ---: |
| Target rate | 200 requests/s | 200 requests/s |
| Achieved rate | Not measured | Not measured |
| p50 latency | Not measured | Not measured |
| p95 latency | Not measured | Not measured |
| p99 latency | Not measured | Not measured |
| Successful script calls | Not measured | Not measured |

Measurements could not be collected in the implementation environment because
no Redis server was listening on `localhost:6379`, and Docker Desktop's daemon
was unavailable. The commands above are ready to produce both measurements
when Redis is available. No latency values are inferred or fabricated.

## Bottleneck and optimization

The limiter sent the full Lua script body with every `EVAL` call even though
Redis caches compiled scripts. The service now registers the script and uses
Redis `EVALSHA` on subsequent calls, which sends the short script digest instead
of retransmitting the full source. The benchmark compares the two call paths;
the latency impact remains unverified until it can be run against Redis.

## Final measurements

Pending a run against a live Redis service. Use identical settings for both
commands, then record achieved rate and p50, p95, and p99 values in the results
table above.
