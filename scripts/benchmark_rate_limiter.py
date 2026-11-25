"""Measure Redis sliding-window limiter latency at a controlled request rate."""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from uuid import uuid4

from app.core.rate_limit_script import SLIDING_WINDOW_SCRIPT, WINDOW_MILLISECONDS
from redis.asyncio import Redis


def percentile(values: list[float], percentile_value: float) -> float:
    """Return the nearest-rank percentile in milliseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value / 100 * len(ordered)))
    return ordered[rank - 1] * 1000


async def run_benchmark(
    redis_url: str,
    *,
    mode: str,
    rate: int,
    duration: int,
    max_connections: int,
) -> None:
    """Issue limiter script calls on a regular schedule and report latency."""
    client: Redis = Redis.from_url(
        redis_url, decode_responses=True, max_connections=max_connections
    )
    key = f"benchmark:rate-limit:{uuid4()}"
    script = client.register_script(SLIDING_WINDOW_SCRIPT)
    limit = rate * duration + 100

    async def request() -> tuple[float, int]:
        started = time.perf_counter()
        if mode == "evalsha":
            result = await script(
                keys=[key],
                args=[WINDOW_MILLISECONDS, limit, str(uuid4())],
            )
        else:
            result = await client.eval(
                SLIDING_WINDOW_SCRIPT,
                1,
                key,
                WINDOW_MILLISECONDS,
                limit,
                str(uuid4()),
            )
        return time.perf_counter() - started, int(result[0])

    try:
        await client.ping()
        for _ in range(20):
            await request()
        await client.delete(key)

        total_requests = rate * duration
        latencies: list[float] = []
        allowed = 0
        start = time.perf_counter()

        async def scheduled_request(index: int) -> tuple[float, int]:
            deadline = start + index / rate
            delay = deadline - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            return await request()

        results = await asyncio.gather(
            *(scheduled_request(index) for index in range(total_requests))
        )
        elapsed = time.perf_counter() - start
        for latency, was_allowed in results:
            latencies.append(latency)
            allowed += was_allowed

        print(f"Mode: {mode}")
        print(f"Target rate: {rate} requests/second")
        print(f"Achieved rate: {total_requests / elapsed:.2f} requests/second")
        print(f"Requests: {total_requests}; allowed: {allowed}")
        print(f"p50: {percentile(latencies, 50):.3f} ms")
        print(f"p95: {percentile(latencies, 95):.3f} ms")
        print(f"p99: {percentile(latencies, 99):.3f} ms")
    finally:
        await client.delete(key)
        await client.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--mode", choices=("eval", "evalsha"), default="evalsha")
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--max-connections", type=int, default=256)
    args = parser.parse_args()
    if min(args.rate, args.duration, args.max_connections) < 1:
        parser.error("rate, duration, and max-connections must be positive")
    return args


async def main() -> None:
    args = parse_args()
    await run_benchmark(
        args.redis_url,
        mode=args.mode,
        rate=args.rate,
        duration=args.duration,
        max_connections=args.max_connections,
    )


if __name__ == "__main__":
    asyncio.run(main())
