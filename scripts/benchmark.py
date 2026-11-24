"""Concurrent benchmark client for the protected quote endpoint."""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class BenchmarkResult:
    """Aggregate results from one benchmark run."""

    average_latency_ms: float
    p95_latency_ms: float
    requests_per_second: float
    successful_requests: int
    failed_requests: int
    elapsed_seconds: float


def percentile_95(values: list[float]) -> float:
    """Return the nearest-rank 95th percentile for non-empty values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


async def run_benchmark(
    url: str,
    api_key: str,
    requests: int,
    concurrency: int,
    timeout: float,
) -> BenchmarkResult:
    """Send a fixed number of concurrent requests and summarize their latency."""
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    successful = 0
    failed = 0
    headers = {"Authorization": f"Bearer {api_key}"}
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )

    async with httpx.AsyncClient(
        headers=headers, limits=limits, timeout=timeout
    ) as client:
        async def send_request() -> None:
            nonlocal successful, failed
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    elapsed = time.perf_counter() - started
                    latencies.append(elapsed)
                    if response.is_success:
                        successful += 1
                    else:
                        failed += 1
                except httpx.HTTPError:
                    latencies.append(time.perf_counter() - started)
                    failed += 1

        started = time.perf_counter()
        await asyncio.gather(*(send_request() for _ in range(requests)))
        elapsed = time.perf_counter() - started

    return BenchmarkResult(
        average_latency_ms=(statistics.fmean(latencies) * 1000 if latencies else 0),
        p95_latency_ms=percentile_95(latencies) * 1000,
        requests_per_second=requests / elapsed if elapsed > 0 else 0,
        successful_requests=successful,
        failed_requests=failed,
        elapsed_seconds=elapsed,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line options for a benchmark run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/quote")
    parser.add_argument("--api-key", required=True, help="Bearer API key")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("requests, concurrency, and timeout must be positive")
    return args


async def main() -> None:
    """Run the benchmark and print a human-readable summary."""
    args = parse_args()
    result = await run_benchmark(
        url=args.url,
        api_key=args.api_key,
        requests=args.requests,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )
    print(f"Average latency: {result.average_latency_ms:.2f} ms")
    print(f"P95 latency: {result.p95_latency_ms:.2f} ms")
    print(f"Requests/sec: {result.requests_per_second:.2f}")
    print(f"Successful requests: {result.successful_requests}")
    print(f"Failed requests: {result.failed_requests}")
    print(f"Elapsed time: {result.elapsed_seconds:.2f} s")


if __name__ == "__main__":
    asyncio.run(main())
