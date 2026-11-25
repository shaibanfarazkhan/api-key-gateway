"""Unit tests for the Redis limiter benchmark percentile calculation."""

from scripts.benchmark_rate_limiter import percentile


def test_percentile_uses_nearest_rank_and_returns_milliseconds() -> None:
    samples = [0.010, 0.020, 0.030, 0.040]

    assert percentile(samples, 50) == 20.0
    assert percentile(samples, 95) == 40.0
    assert percentile(samples, 99) == 40.0


def test_percentile_returns_zero_for_empty_samples() -> None:
    assert percentile([], 99) == 0.0
