"""Upstream retry policy (PRD 7.9): 4 attempts, delays 1 s / 2 s / 4 s + jitter ≤ 250 ms, honour retry-after."""

import asyncio
import random
from collections.abc import Awaitable, Callable

MAX_ATTEMPTS = 4
BASE_DELAY_S = 1.0
FACTOR = 2.0
MAX_JITTER_S = 0.25
RETRYABLE_STATUSES = frozenset({429, 529})


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUSES or 500 <= status <= 599


def backoff_delay(attempt: int, retry_after_s: float | None = None) -> float:
    """Delay before attempt `attempt + 1` (attempt is 1-based)."""
    delay = BASE_DELAY_S * FACTOR ** (attempt - 1) + random.uniform(0, MAX_JITTER_S)  # noqa: S311 - jitter only
    if retry_after_s is not None and retry_after_s > delay:
        return retry_after_s
    return delay


# Indirection so tests can replace sleeping with a no-op.
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


async def with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[BaseException], bool],
    retry_after: Callable[[BaseException], float | None] = lambda _e: None,
    on_retry: Callable[[int, BaseException], None] = lambda _a, _e: None,
) -> T:
    attempt = 1
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= MAX_ATTEMPTS or not should_retry(exc):
                raise
            on_retry(attempt, exc)
            await sleep(backoff_delay(attempt, retry_after(exc)))
            attempt += 1
