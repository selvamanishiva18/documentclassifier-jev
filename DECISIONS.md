# DECISIONS

Append-only log. Format: **context → decision → alternatives considered → consequence.**
All entries dated 2026-10-04 (initial build) unless stated.

---

## Build-time choices made with the product owner

- **D-00 Repo layout.** Context: PRD 16.2 shows a `docclassify/` root. → Decision: the owner asked for no extra folder, so `backend/`, `frontend/`, `README.md`, `DECISIONS.md`, `docker-compose.yml` sit directly in the project root. No git repo was initialised. → Alternatives: nested `docclassify/`. → Consequence: paths in the PRD drop the `docclassify/` prefix.
- **D-00b Stack fidelity.** Context: the build agent suggested replacing pdf2image+Poppler with `pypdfium2` and using Anthropic structured outputs. → Decision: the owner chose to follow the PRD stack exactly, so neither change was made. → Consequence: Poppler stays a system dependency, and Haiku output is JSON requested by prompt, repaired with one corrective retry.
- **D-00c Local verification.** Context: the dev machine (Windows) has no Docker, Tesseract, or Poppler. → Decision: the application was built and checked locally with mocks. Tests that need real OCR are marked with `skipif` and run in `docker build --target test backend`. → Consequence: 3 OCR tests and the load test were **not executed** during the initial build (see "Verification status" at the end).

---

## Required entries (PRD 16.12)

### 1. Deviations from external API contracts

- **Jev request/response.** The PRD 16.6.1 shape matches the SDK (`typesafe-sdk` 0.7.2: `POST {base}/v1/systemone`, body `{state, model, questions}`, response `{model, answers, usage}`). No deviation. Ref: https://docs.typesafe.ai/api, https://docs.typesafe.ai/sdk/python.
  - The SDK's `SystemOneResponse` requires `usage`. A response without it fails SDK validation, which maps to `JEV_INVALID_RESPONSE`.
- **Anthropic Messages API.** Used as specified: `image` / `document` base64 blocks, `temperature=0`, `max_tokens=4096`, a system prompt, and a corrective retry that appends one text block to the same user turn. No deviation. Ref: https://docs.claude.com.
- **Tesseract.** `--oem 1 --psm 6` with a `--psm 3` fallback (see item 4). OSD runs as `--psm 0` via `image_to_osd`.
- **Test tooling deviation:** PRD 16.10 says to mock Jev with `respx`. The official SDK uses **`httpx2`**, which `respx` cannot intercept. Jev tests therefore inject `httpx2.MockTransport` through the SDK's supported `transport=` argument (`backend/tests/test_jev.py`). Anthropic tests use `respx` as specified.

### 2. Jev client path

- Decision: official **`typesafe-sdk==0.7.2`** (`AsyncTypeSafeClient` + `Choice`), pinned in `backend/pyproject.toml`.
- **Retries:** the SDK's own retry is disabled (`RetryPolicy(max_retries=0)`), and the PRD 7.9 policy is applied by `app/services/retry.py`. The policy is 4 attempts with 1 s / 2 s / 4 s delays plus **additive** jitter of ≤ 250 ms. It retries on 429, 529, 5xx, connection errors, and timeouts, and honours `retry-after`.
  - Alternative: the SDK's `RetryPolicy`. Rejected because its jitter is subtractive and its delays differ from 7.9.
  - Consequence: one identical retry policy covers Jev and Anthropic, and tests can replace `retry.sleep`.
- 401/403 map to `JEV_AUTH_ERROR`. 400/404/422 map to `JEV_BAD_REQUEST`; these are not retried and are logged with status only. Exhausted retries map to `JEV_UNAVAILABLE`. A malformed body maps to `JEV_INVALID_RESPONSE`.
- Request timeout is 30 s. The SDK reads `TYPESAFE_*` env vars, but the app passes the key, base URL, and model explicitly from `Settings`.

### 3. Magic-byte detection

- Decision: a **pure-Python header check**: JPEG `FF D8 FF`, PDF `%PDF-` (`app/services/validation.py`). Alternative: `python-magic`/`libmagic`. Not needed for two formats. `libmagic1` is still installed in the image, per PRD 16.3.
- The server ignores the file extension. A JPEG named `.pdf` is accepted as a JPEG.
- After the magic check, readability is verified: JPEGs with `PIL.Image.verify()`, PDFs by counting pages with `pypdf`. Either failing gives `CORRUPT_FILE`.

### 4. Tesseract configuration

- Target: Tesseract **5.x** with `eng` (Debian `tesseract-ocr` in `python:3.12-slim`).
- `--oem 1` (LSTM). `--psm 6` first. If the result has fewer than 20 non-whitespace characters, `--psm 3` runs, and the longer output is kept.
- OSD: `image_to_osd --psm 0`. The image is rotated only when `Orientation confidence ≥ 2.0` and `Rotate ≠ 0`. If OSD fails (sparse text), the image is left unrotated.
- Rasterisation: **300 DPI**, grayscale, via `pdf2image.convert_from_bytes`, one page at a time.
- Per-page timeout: 60 s, for both OCR and rasterisation.
- Text is rebuilt from `image_to_data` lines (block/paragraph/line order), so each page needs one OCR pass. `ocr_mean_confidence` is the mean of word `conf ≥ 0`, rounded to 2 dp.
- OCR runs in `asyncio.to_thread` so the event loop and status polling stay responsive.

### 5. PDF text-layer threshold

- Unchanged: **20** non-whitespace characters per page.
- `ocr_mean_confidence` is **`null`** for a Fast-mode PDF where no page needed OCR, because there are no OCR words to average. Alternative: report 100. Rejected as misleading.

### 6. CSV

- Python `csv.writer` with the `excel` dialect, `QUOTE_MINIMAL`, and `\r\n` line terminators (RFC 4180). Fields containing commas, quotes, or newlines are quoted, and embedded newlines are preserved inside quotes.
- UTF-8 **without BOM**. Excel may mis-detect the encoding of non-ASCII text when the file is opened directly.
- `confidence` is the raw float from Jev (`repr`, e.g. `0.91`). `extraction_method` is filled even for failed rows. `warnings` are joined with `;`.

### 7. IDs

- **`python-ulid` 3.1.0**, format `b_<ULID>` / `d_<ULID>`.
- IDs are **not** guaranteed monotonic within a millisecond. They are random within that millisecond and only used as opaque keys.
- The document IDs in PRD examples are shortened. Real IDs use the full 26-character ULID.

### 8. Timestamps

- `datetime.now(UTC)`, truncated to milliseconds, serialised as ISO 8601 with a `Z` suffix (`2026-10-04T03:12:45.120Z`) via a pydantic `PlainSerializer`.
- `expires_at = completed_at + BATCH_TTL_MINUTES`.

### 9. In-memory store and purge

- A `dict[batch_id, BatchRecord]` with **no `asyncio.Lock`**. All mutations happen on the single event loop thread with no `await` inside a mutation, so they are atomic. Alternative: dict + lock. It would add nothing in a single-loop process.
- The purge loop is an `asyncio` task created in the FastAPI lifespan. It runs every 60 s and removes batches whose `expires_at ≤ now`.
- Batch tasks are tracked with `asyncio.create_task` plus a registry set, not FastAPI `BackgroundTasks`. `BackgroundTasks` run inside the request lifecycle and cannot be cancelled or counted for `MAX_CONCURRENT_BATCHES`.
- Purged and deleted batch IDs are kept as **tombstones**: IDs only, no content, capped at 10,000 entries with oldest evicted first. This lets `POST /retry` answer `410 BATCH_EXPIRED` while `GET` answers `404 BATCH_NOT_FOUND`, per 16.4 and 16.10.

### 10. Body-size limit

- Enforced in the app by a pure-ASGI middleware (`app/api/limits.py`): a 220 MB check against `Content-Length` up front, and against streamed bytes when there is no `Content-Length`. Returns `413 UPLOAD_TOO_LARGE` in the standard error body.
- nginx (frontend container) also sets `client_max_body_size 220m` and `proxy_request_buffering off`. nginx's own 413 is a default HTML page, so the app-level check is the one that produces the specified error code when the backend is reached directly.
- Starlette spools multipart uploads larger than 1 MB to an anonymous temp file during parsing. That file is deleted when the request ends. Bytes kept for processing and retry live in memory only.

### 11. Non-canonical Haiku keys

- Not yet observed (no `ANTHROPIC_API_KEY` was available during the build). The extractor logs `unknown_keys` (key names only) at INFO when Haiku returns extra keys. Review these logs and record observations here.

### 12. Open questions and interim choices

1. **Rate-limit error code.** The per-IP limit (30 accepted submissions per hour) has no dedicated code in 16.8. Interim: `429 SERVER_BUSY`. The client IP comes from `X-Real-IP` (set by the bundled nginx), falling back to the socket peer. Open question: is a distinct code like `RATE_LIMITED` wanted?
2. **Retrying file-validation failures.** `INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, and `CORRUPT_FILE` documents are **not** re-queued, because their bytes are not kept and retrying cannot change the outcome. If a batch's only failures are validation failures, `POST /retry` returns `409 BATCH_STATE_CONFLICT`.
3. **Retry from `cancelled`.** Not allowed (`409`). Section 8 only defines `completed_with_errors → processing`.
4. **Cancel while `queued`.** Allowed. The 16.4 wording "409 if not processing" is read as "409 if not queued or processing".
5. **`total_duration_ms`.** The sum of each document's extraction and classification `duration_ms`, not wall-clock time. This keeps it stable across retries.
6. **Text gate.** Implemented as "fewer than 10 non-whitespace characters" (6.2 and 8.0), which is slightly stricter than `len(raw_text.strip()) < 10` (7.2) when whitespace sits inside the text.
7. **`extraction.raw_text`** stores the text up to `CLASSIFICATION_TEXT_CAP`, per 6.4 AC7. The Fast-mode heuristic field extractor runs over the **full**, uncapped text.
8. **Error message source.** Where Section 6 and 16.8 wording differ (for example the Precise API error), the **16.8** message is used.
9. **Upload field name.** `POST /batches` accepts files under `files` (what the frontend sends) and `files[]`.
10. **Unknown routes.** These return the standard error body with `BATCH_NOT_FOUND`/404, because 16.8 has no generic not-found code.
11. **`DELETE`** is idempotent: `204` even for unknown or expired IDs.
12. **Anthropic non-retryable 4xx** (e.g. 400 for an oversized PDF) map to `HAIKU_UNAVAILABLE`, and 401/403 map to `HAIKU_AUTH_ERROR`. 16.8 has no better fit.
13. **Heuristic extractor details beyond the 16.7 table.**
    - `\b` word boundaries on keywords, so "po" in "Report" is not matched.
    - Recipient labels accept an inline value (`Sold To: X`).
    - Summary rows (subtotal/tax/total) are excluded from line-item counting.
    - The due-date line is excluded when picking `document_date`.
    - `payment_terms` may match a validity phrase such as "valid for 30 days", as the 16.7 pattern allows.
14. **`choice_not_argmax`** is added only when the chosen key's probability is strictly below the maximum. Ties don't trigger it.

---

## Frontend (PRD silent)

- Client-side checks are by extension only (`.jpg`/`.jpeg`/`.pdf`, case-insensitive) and size (≤ 10 MB, exactly 10 MB allowed). Rejected files stay listed with their reason and are not uploaded.
- More than 20 valid files can be listed. Clicking Process then shows "You can process up to 20 files per batch." and uploads nothing ("rejected at submission", 6.1).
- After `POST /batches`, the client fetches once immediately, then polls every 1500 ms. Only `404` stops polling; transient polling errors are ignored until the next tick.
- If `/api/health` fails, the header shows "Server unreachable" and Precise stays selectable, because the server's `503` is the real enforcement. Fast is not disabled when `tesseract=false`; the badge shows ✗.
- Cancel is enabled while `queued`/`processing` and shows "Cancelling…" until the batch is terminal.
- Confidence is shown as a percentage with 1 dp. Colour bands use the raw value: green ≥ 0.85, amber 0.60 to < 0.85, red < 0.60.
- The in-flight document gets a client-side elapsed timer. Finished documents show extraction + classification `duration_ms`.
- Downloads use `<a download>` links to the export endpoints. Copy uses `navigator.clipboard`, with a hidden-textarea fallback.
- A network failure is shown as status 0 / `INTERNAL_ERROR`: "Could not reach the server. Check your connection and try again."
- `ResultDetail` uses tabs below 768 px (Tailwind `md`) and a two-column grid above. Method cards stack below 640 px.
- "Start new batch" sends `DELETE` and ignores errors (TTL purges anyway), then clears files and method.
- The Docker image builds with Node 22 and serves through nginx 1.27 on port 5173, proxying `/api/` to `backend:8000`.

---

## Vercel deployment (2026-10-05)

- **Container services.** Context: deploying with Vercel container Functions (https://vercel.com/kb/guide/docker). → Decision: `vercel.json` defines two services, `frontend/Dockerfile.vercel` and `backend/Dockerfile.vercel`, and rewrites `/api/*` to the backend and everything else to the frontend. The existing `Dockerfile`s and compose setup remain for local Docker. → Alternatives: Vercel's static/Python builders, rejected because Tesseract and Poppler need system packages. → Consequence: same-origin `/api`. The frontend nginx no longer proxies; it only serves `dist/`.
- **Port.** Both containers listen on `$PORT`, defaulting to Vercel's 80. The backend image runs as root so it can bind port 80. The local Dockerfile keeps a non-root user on 8000.
- **Secrets.** `.vercelignore` excludes `.env`. `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY`, and the other variables must be set in Vercel project settings.
- **Open risk: in-memory batch store.** The PRD assumes one long-lived process. On Vercel Functions, instances autoscale and are stopped after 5 minutes idle (production), so:
  - polling may reach an instance that doesn't hold the batch, giving a `404`;
  - background processing after the `202` response may be frozen or stopped;
  - batches may disappear before the 15-minute TTL.
  This was **not verified**. If it shows up, the fix is the Phase 2 Redis store or processing synchronously within the request.
- **Open risk: request body size.** Standard Vercel Function limits apply, including a request-body cap that is far below 220 MB. Large batches may fail at the edge before the app's `UPLOAD_TOO_LARGE` handling. **Not verified.**

---

## Verification status (2026-10-04)

| Check | Result |
| --- | --- |
| Backend `ruff check`, `ruff format --check`, `mypy --strict` (app + tests) | clean |
| Backend `pytest` | 122 passed, **4 skipped** (3 real-OCR tests + load test: no Tesseract/Poppler on the dev machine) |
| Frontend `eslint`, `tsc --noEmit`, `prettier --check`, `vitest run`, `vite build` | clean; 47 tests passed |
| Live Jev smoke test (real key, synthetic fixtures, Fast mode, text-layer PDFs) | invoice → `invoice_from_supplier` 1.0, quotation → `quotation` 1.0, model `jev-1.13.0`, ~250–520 ms per call; renamed PNG → `INVALID_FILE_TYPE`; 21-page PDF → `pdf_truncated_to_20_pages`; export/delete OK; no key or document text in logs |
| Not yet verified | Docker build/compose, real Tesseract OCR path, Precise mode against the live Anthropic API, p95 latency targets |
