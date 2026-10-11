"""In-memory batch store with TTL purge (PRD 6.5, 7.11). Nothing is ever written to durable storage."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.schemas import Batch

log = logging.getLogger("docclassify.store")

PURGE_INTERVAL_S = 60
MAX_TOMBSTONES = 10_000


def utc_now() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


@dataclass
class StoredFile:
    data: bytes
    mime_type: str
    pages_processed: int


@dataclass
class BatchRecord:
    batch: Batch
    # Original bytes for documents that passed validation, kept only for processing and retry.
    files: dict[str, StoredFile] = field(default_factory=dict)
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = None


class BatchStore:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._batches: dict[str, BatchRecord] = {}
        # Ids of purged batches (ids only, no content) so retry can answer 410 instead of 404.
        self._tombstones: OrderedDict[str, None] = OrderedDict()
        self.clock = clock

    def add(self, record: BatchRecord) -> None:
        self._batches[record.batch.batch_id] = record

    def get(self, batch_id: str) -> BatchRecord | None:
        return self._batches.get(batch_id)

    def was_purged(self, batch_id: str) -> bool:
        return batch_id in self._tombstones

    def remove(self, batch_id: str) -> BatchRecord | None:
        record = self._batches.pop(batch_id, None)
        if record is not None:
            if record.task is not None and not record.task.done():
                record.task.cancel()
            record.files.clear()
            self._tombstones[batch_id] = None
            while len(self._tombstones) > MAX_TOMBSTONES:
                self._tombstones.popitem(last=False)
        return record

    def purge_expired(self) -> list[str]:
        now = self.clock()
        expired = [
            bid
            for bid, rec in self._batches.items()
            if rec.batch.expires_at is not None and rec.batch.expires_at <= now
        ]
        for bid in expired:
            self.remove(bid)
            log.info("batch purged", extra={"batch_id": bid, "stage": "purge"})
        return expired

    def clear(self) -> None:
        for bid in list(self._batches):
            self.remove(bid)

    def __len__(self) -> int:
        return len(self._batches)

    async def run_purge_loop(self, interval_s: float = PURGE_INTERVAL_S) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                self.purge_expired()
            except Exception:
                log.exception("purge failed")
