"""Cron workerで共有する純粋な業務規則。"""

from datetime import timedelta


def retry_delay(attempt_count: int) -> timedelta:
    """Claim試行回数に対する1h開始・24h上限の指数Backoff。"""
    return timedelta(hours=min(24, 2 ** (attempt_count - 1)))
