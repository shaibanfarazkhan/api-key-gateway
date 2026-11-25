# Redis Rate Limiter Benchmark

## Environment and method

The benchmark used the Redis 7 service from `docker-compose.yml` and the host
Python environment. It measures Redis command round-trip latency for the
production sliding-window Lua script; it excludes FastAPI, PostgreSQL,
authentication, and quota-accounting latency.

Each mode targeted 200 requests per second for 30 seconds (6,000 measured
requests), with 20 warm-up calls. The script reports nearest-rank p50, p95, and
p99 command latency and achieved throughput. The results below are the recorded
single-run measurements; they are not multi-trial averages.

## Commands

```powershell
docker compose up -d redis
uv run python -m scripts.benchmark_rate_limiter --redis-url redis://localhost:6379/0 --mode eval --rate 200 --duration 30
uv run python -m scripts.benchmark_rate_limiter --redis-url redis://localhost:6379/0 --mode evalsha --rate 200 --duration 30
```

## Results

| Measurement | EVAL | EVALSHA |
| --- | ---: | ---: |
| Target throughput | 200 requests/s | 200 requests/s |
| Achieved throughput | 200.00 requests/s | 199.97 requests/s |
| Successful script calls | 6,000 | 6,000 |
| p50 latency | 2.200 ms | 2.777 ms |
| p95 latency | 4.440 ms | 4.662 ms |
| p99 latency | 5.237 ms | 5.400 ms |
| p95 requirement (<10 ms) | Satisfied | Satisfied |

EVALSHA did **not** outperform EVAL in this run: its measured p50, p95, and p99
latencies were each slightly higher, and achieved throughput was marginally
lower. These measurements do not support claiming a Redis latency improvement
from script registration at this workload. The p95 latency requirement was
satisfied by both modes.

## Bottleneck and optimization assessment

The EVAL path transmits the Lua source on each command, while EVALSHA sends the
registered script digest. Although this reduces the command payload, the
measured Redis round-trip results above show no latency benefit here. Therefore,
EVALSHA is documented as an alternate call path, not as a proven performance
optimization. The separately measured full-request-path bottleneck and its
optimization are documented in [PERFORMANCE.md](PERFORMANCE.md); that result
must not be conflated with this Redis-only benchmark.

## Limitations

These are local single-run measurements. Host CPU and memory were not captured,
and the benchmark excludes application and database work. Treat the values as
observations for the recorded environment, not as a production capacity
guarantee. Re-run both modes with identical settings when comparing changes.
