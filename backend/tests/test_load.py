"""Non-functional load check (PRD 16.10): 5 concurrent batches x 3 JPEGs in Fast mode with real Tesseract.

Jev is faked so the run measures local OCR throughput only. Skipped when Tesseract is not installed.
"""

import asyncio
import time
from typing import Any

from app.main import create_app
from app.services.extraction.fast import FastExtractor
from tests.conftest import FakeClassifier, fixture_bytes, make_settings, requires_tesseract, upload, wait_terminal

# PRD 9.0: a batch of 3 single-page JPEGs completes in <= 30 s (Fast). All five run concurrently here.
BATCH_LIMIT_S = 30.0


@requires_tesseract
async def test_five_concurrent_fast_batches(client_for: Any) -> None:
    ext = FastExtractor()
    app = create_app(
        make_settings(),
        classifier=FakeClassifier(choice="receipt"),
        extractors={"fast": ext},
        tesseract_check=lambda: True,
        run_purge_loop=False,
    )
    client = await client_for(app)
    jpg = fixture_bytes("receipt.jpg")
    started = time.perf_counter()
    ids = []
    for _ in range(5):
        resp = await client.post("/api/batches", **upload([("r1.jpg", jpg), ("r2.jpg", jpg), ("r3.jpg", jpg)]))
        assert resp.status_code == 202
        ids.append(resp.json()["batch_id"])

    async def finish(batch_id: str) -> dict[str, Any]:
        async with asyncio.timeout(BATCH_LIMIT_S * 2):
            while True:
                try:
                    return await wait_terminal(client, batch_id)
                except TimeoutError:
                    continue

    results = await asyncio.gather(*(finish(b) for b in ids))
    elapsed = time.perf_counter() - started
    assert all(r["status"] == "completed" for r in results), [r["status"] for r in results]
    assert elapsed <= BATCH_LIMIT_S, f"5 concurrent batches took {elapsed:.1f}s"
