# Document Classification & Extraction System

Upload scanned business documents (JPG/PDF), extract their text (**Fast**: local Tesseract OCR, or **Precise**: Claude Haiku 4.5), classify each into one of eleven types with **Jev** (TypeSafe System One), and export structured JSON/CSV. Stateless: no login, nothing persisted, batches expire 15 minutes after completion.

Spec: [`prd/PRD-Document-Classification-Extraction-System (1).md`](prd/). Choices made where the PRD is silent: [`DECISIONS.md`](DECISIONS.md).

```
backend/    FastAPI (Python 3.12) — validation, extraction, Jev classification, batch processor, exports
frontend/   React 18 + TypeScript + Vite 5 + Tailwind — single-page UI, served by nginx in Docker
```

## Quick start (Docker)

```bash
cp .env.example .env          # set TYPESAFE_API_KEY; optionally ANTHROPIC_API_KEY
docker compose up --build     # UI http://localhost:5173 · API http://localhost:8000/api
```

The backend image installs `tesseract-ocr`, `tesseract-ocr-eng`, `poppler-utils`, `libmagic1`. With only `TYPESAFE_API_KEY` set, Fast mode works and Precise is shown disabled. To run the backend test suite inside Docker (with real Tesseract/Poppler): `docker build --target test backend`.

## Local development (without Docker)

System packages: Tesseract 5 (`eng`) and Poppler on `PATH` (Windows: UB-Mannheim Tesseract installer + Poppler for Windows; set `TESSERACT_CMD` if not on `PATH`).

```bash
# backend (reads .env from backend/ or the repo root)
cd backend
python -m venv .venv && .venv/Scripts/activate      # or: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --port 8000

# frontend (Vite proxies /api -> http://localhost:8000)
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

## Environment variables

<a id="environment-variables"></a>

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TYPESAFE_API_KEY` | **Yes** | — | Jev authentication. Server refuses to start without it. |
| `TYPESAFE_BASE_URL` | No | `https://api.typesafe.ai` | Gateway/testing override |
| `JEV_MODEL` | No | `jev-latest` | Pin (e.g. `jev-1.13.0`) for stable confidence values |
| `ANTHROPIC_API_KEY` | No | — | Enables Precise mode |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model id |
| `MAX_FILE_SIZE_MB` | No | `10` | Per-file limit |
| `MAX_FILES_PER_BATCH` | No | `20` | Batch size limit |
| `MAX_PDF_PAGES` | No | `20` | Pages processed per PDF |
| `CLASSIFICATION_TEXT_CAP` | No | `20000` | Characters sent to Jev |
| `BATCH_TTL_MINUTES` | No | `15` | Expiry after completion |
| `MAX_CONCURRENT_BATCHES` | No | `5` | Per-process limit |
| `ALLOWED_ORIGINS` | No | `http://localhost:5173` | CORS (comma-separated) |
| `TESSERACT_CMD` | No | `tesseract` | Path to Tesseract binary |
| `LOG_LEVEL` | No | `INFO` | Logging |

Frontend build-time: `VITE_API_BASE_URL` (default `/api`); dev proxy target `VITE_PROXY_TARGET` (default `http://localhost:8000`).

## API walkthrough (curl)

All endpoints are under `/api`. Errors are `{ "error_code": "...", "error_message": "..." }`.

```bash
API=http://localhost:8000/api

# Health
curl -s $API/health
# {"status":"ok","tesseract":true,"jev_configured":true,"haiku_configured":false,"version":"1.0.0"}

# Submit a batch (1–20 files, method fast|precise) -> 202 {batch_id, status, documents[]}
curl -s -X POST $API/batches \
  -F extraction_method=fast \
  -F files=@backend/tests/fixtures/invoice.pdf \
  -F files=@backend/tests/fixtures/receipt.jpg
BATCH=b_01J...   # from the response

# Poll (recommended every 1.5 s); full Batch incl. completed documents while processing
curl -s $API/batches/$BATCH

# Cancel (stops after the current document) / retry failed documents
curl -s -X POST $API/batches/$BATCH/cancel
curl -s -X POST $API/batches/$BATCH/retry

# Export (works in any state; includes only terminal documents)
curl -s -OJ $API/batches/$BATCH/export.json     # document-results-{batch_id}.json
curl -s -OJ $API/batches/$BATCH/export.csv      # document-results-{batch_id}.csv

# Delete now (otherwise purged 15 min after completion)
curl -s -X DELETE $API/batches/$BATCH -o /dev/null -w "%{http_code}\n"   # 204
```

Status codes: `400` `NO_FILES` / `TOO_MANY_FILES` / `INVALID_METHOD`, `413` `UPLOAD_TOO_LARGE` (> 220 MB), `429` `SERVER_BUSY` (6th concurrent batch or > 30 submissions/hour/IP), `503` `PRECISE_NOT_CONFIGURED`, `404` `BATCH_NOT_FOUND`, `409` `BATCH_STATE_CONFLICT`, `410` `BATCH_EXPIRED` (retry after purge). Per-file problems (`INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, `CORRUPT_FILE`) appear on the document, not as HTTP errors.

## Checks

```bash
# backend
cd backend
ruff check app tests && ruff format --check app tests
mypy app tests                      # strict
pytest -q                           # OCR tests auto-skip when Tesseract/Poppler are absent

# frontend
cd frontend
npm run lint && npm run typecheck && npm run format:check
npm test
npm run build
```

Regenerate the synthetic fixtures with `python -m tests.fixtures.make_fixtures` (from `backend/`).

## Operational notes

- **Single replica.** Batches live in process memory. Run one backend replica (or sticky sessions) until Phase 2 moves the store to Redis. A restart clears all batches.
- **Logs** are JSON on stdout and never contain document text, extracted fields, or API keys.
- **HTTPS** is expected at the edge (reverse proxy / load balancer) in front of the frontend container.
