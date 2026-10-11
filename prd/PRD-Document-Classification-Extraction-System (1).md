# Document Classification & Extraction System — PRD

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 2026-10-04 |
| Status | Draft — ready for build |
| Phase | 1 (MVP) |
| Audience | Product, engineering, QA, and AI coding agents |

> **Note for coding agents:** This document is the single source of truth. Sections 1–15 define *what* the system must do. Section 16 (Technical Specification) defines *how* to build it: stack, project layout, environment variables, API contracts, external-service request/response shapes, prompts, and test plan. Build exactly what is specified; where a detail is not specified, choose the simplest option and note it in `DECISIONS.md` in the repo root (see 16.12 for what must be recorded).
>
> If any requirement in Sections 1–16 conflicts with an external API's current documented behaviour (Jev, Anthropic, Tesseract), prefer the external API's documented behaviour and record the deviation in `DECISIONS.md`. Never invent fields, status values, or error codes: the only valid status values are those in Section 8, the only valid `error_code` values are those in 16.8, and the only valid `extracted_fields` keys are the canonical set in 6.4. If something you need is missing, add it to `DECISIONS.md` as an open question rather than improvising.

---

## 1.0 Overview

The Document Classification & Extraction System is a stateless web application that lets a small business owner upload scanned business documents (JPG or PDF), convert them to text, and have each document automatically classified into one of ten business document types (or "None of the above") with a calibrated confidence score. Output is structured JSON that the user can view, copy, or download.

Small business owners receive a steady stream of paper and emailed scans — supplier invoices, purchase orders, receipts, packing slips, quotes — and currently sort and key them by hand. This system removes the sorting step and produces machine-readable output, laying the groundwork for Phase 2, where classified documents will be pushed into downstream applications (accounting, ERP) through their APIs.

The pipeline has three stages. **Extraction** converts the image/PDF to text using one of two user-selected methods: a local Python OCR path (Pytesseract plus PDF text extraction) or Claude Haiku 4.5 via the Anthropic API. **Classification** sends the extracted text to Jev, TypeSafe AI's System One model, which returns a typed `Choice` answer (the document type) together with a per-option probability distribution and a confidence value — not generated prose. **Output** assembles document metadata, the classification, and a flat key-value map of extracted fields into JSON.

Design principles: no login, no persistence (process-and-export), one extraction method per batch chosen by the user, deterministic typed classification via Jev, and an output schema stable enough for Phase 2 API integrations to build on.

---

## 2.0 Personas

1. **Small Business Owner**
   Uploads scanned documents, selects the extraction method, reviews the classification and extracted fields, and downloads the JSON/CSV. The only persona in Phase 1. Not technical; needs clear status and error messages.

2. **System** (non-human actor)
   Performs validation, extraction, classification, JSON assembly, and cleanup. Referenced in workflow and RBAC tables for completeness.

---

## 3.0 Visual References

No Figma or RXD proto exists yet. The MVP is built from the layout notes below plus the component inventory in 16.9; a design file may replace these later without changing behaviour.

**Layout (single page, max content width 960 px, centred; stacks to one column at < 640 px)**

```
┌──────────────────────────────────────────────────────────────┐
│ Header: app name · health badge (Fast ✓ / Precise ✓|✗)       │
├──────────────────────────────────────────────────────────────┤
│ [Setup state]                                                │
│  Dropzone (full width, dashed border, 160 px tall)           │
│  FileList (rows: name · size · ⓘ reason · ✕)                 │
│  MethodSelector (two radio cards side by side; stacked <640) │
│  [ Process N files ]  (primary, right-aligned)               │
├──────────────────────────────────────────────────────────────┤
│ [Processing state]                                           │
│  ProgressPanel — STICKY HEADER: overall bar · "Extracting    │
│  inv_0412.pdf (2/7)…" · [Cancel]                             │
│  Per-document rows: name · stage badge · duration            │
├──────────────────────────────────────────────────────────────┤
│ [Results state]                                              │
│  Summary strip: total · completed · failed · avg conf · time │
│  ExportBar (sticky at top of results): Copy batch JSON ·     │
│    Download JSON · Download CSV · Retry failed · New batch   │
│  ResultsTable — SORTABLE by filename, type, confidence,      │
│    status (default: upload order); row expands to            │
│  ResultDetail: Fields table | Probability bars (desc, chosen │
│    highlighted) | Raw text (scroll) | JSON (Copy document)   │
└──────────────────────────────────────────────────────────────┘
```

**Explicit layout rules**
- `ProgressPanel` header is sticky; the current filename and stage are the largest text in the panel.
- `ResultsTable` is sortable by confidence (numeric), type label, filename, and status; sort state is client-side only.
- Confidence is rendered as a percentage pill: green ≥ 85 %, amber 60–85 %, red < 60 % (display only; no routing logic).
- `ResultDetail` uses tabs (Fields / Probabilities / Raw text / JSON) on mobile and a two-column grid on desktop.
- Two distinct copy actions with unambiguous labels: **Copy batch JSON** (ExportBar) and **Copy document JSON** (ResultDetail).
- When the batch reaches a terminal state, keyboard focus moves to the summary strip, which has `tabindex="-1"` and `role="region"`.

---

## 4.0 Reference Documents

- TypeSafe / Jev — System One concept: https://docs.typesafe.ai/concepts/system-one
- TypeSafe / Jev — HTTP API reference: https://docs.typesafe.ai/api
- TypeSafe / Jev — Models, pricing, limits: https://docs.typesafe.ai/models
- TypeSafe / Jev — Python SDK: https://docs.typesafe.ai/sdk/python
- TypeSafe / Jev — Agent skill: https://docs.typesafe.ai/agent-skill
- Anthropic Python SDK: https://github.com/anthropics/anthropic-sdk-python
- Anthropic Messages API (vision / PDF input): https://docs.claude.com
- Pytesseract: https://pypi.org/project/pytesseract/
- pdfplumber: https://pypi.org/project/pdfplumber/
- pdf2image: https://pypi.org/project/pdf2image/

---

## 5.0 Process Flow

1. User opens the app (no sign-in).
2. User adds 1–20 files (`.jpg`, `.jpeg`, `.pdf`; ≤ 10 MB each) by drag-and-drop or file picker. Client validates type and size; invalid files are rejected with a message and the rest are kept.
3. User selects an extraction method for the batch: **Fast (Python OCR)** or **Precise (Claude Haiku)**.
4. User clicks **Process**. Client uploads the files and the method in one request; server returns a `batch_id` and begins processing.
5. Server processes documents sequentially. For each document: validate → extract text → extract fields → classify with Jev → assemble result. Failures are recorded per document; the batch continues.
6. Client polls batch status and shows progress (n of N, current stage).
7. When the batch completes, client renders per-document results (type, confidence, fields, raw text) and a batch summary.
8. User copies JSON, downloads JSON, or downloads CSV.
9. Server deletes all in-memory/temporary artifacts for the batch 15 minutes after completion or immediately when the user clicks **Start new batch**.

---

## 6.0 Feature Requirements

### 6.1 Document Upload & Validation

#### Details

The system accepts JPEG images and PDF files only. Validation runs on the client (extension + size, for fast feedback) and again on the server (magic bytes + size + count; server is authoritative). Files are held in memory or an ephemeral temp directory scoped to the batch and are never written to durable storage. Batch size is 1–20 files. Maximum size is 10 MB per file. Maximum PDF page count is 20; pages beyond 20 are ignored and a warning is attached to that document's result.

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | be able to add one or more JPG/PDF files by drag-and-drop or file picker | I can process a day's documents in one go |
| 2 | Small Business Owner | see immediately which files were rejected and why | I can fix the problem without guessing |
| 3 | Small Business Owner | be able to remove a file from the list before processing | I can correct a mis-selection without starting over |
| 4 | Small Business Owner | see a count of accepted files and total size | I know what will be processed |

#### Acceptance Criteria

1. Files with extension other than `.jpg`, `.jpeg`, `.pdf` are rejected client-side.
2. Server rejects any file whose magic bytes do not match JPEG (`FF D8 FF`) or PDF (`%PDF-`) regardless of extension.
3. A file > 10 MB is rejected; the remaining valid files are kept.
4. A batch of 0 valid files cannot be submitted; the Process control is disabled.
5. A batch of > 20 files is rejected at submission with a message; nothing is uploaded.
6. A PDF with > 20 pages is processed for the first 20 pages and the result carries `warnings: ["pdf_truncated_to_20_pages"]`.
7. No uploaded bytes exist on the server 15 minutes after batch completion.

#### Validations & Messages

**Field validations**
- Unsupported type: _"Only JPG, JPEG, and PDF files are supported."_
- Oversize: _"{filename} is larger than 10 MB and was skipped."_
- Too many files: _"You can process up to 20 files per batch."_
- Corrupt/mismatched content (server): _"{filename} could not be read. The file may be corrupted."_

**Business rule validations**
- Empty batch: Process control disabled; helper text _"Add at least one file to continue."_

**Success**
- _"{n} file(s) ready. Choose an extraction method."_

---

### 6.2 Extraction Method Selection & Text Extraction

#### Details

The user selects exactly one method per batch. The selection is sent with the batch and cannot be changed mid-batch.

**Fast (Python OCR)**
- JPEG: Pytesseract (Tesseract 5, `eng`, `--psm 6` default, fallback `--psm 3` if output < 20 characters).
- PDF: pdfplumber first. If a page yields fewer than 20 non-whitespace characters, that page is rasterized at 300 DPI with pdf2image and OCR'd with Pytesseract. Pages are joined with `\n\n--- page {n} ---\n\n`.
- Light preprocessing before OCR: convert to grayscale; auto-rotate using Tesseract OSD when confidence allows; no other preprocessing in Phase 1.
- Produces `raw_text` and `ocr_mean_confidence` (0–100, from `image_to_data`, averaged over words with conf ≥ 0).

**Precise (Claude Haiku 4.5)**
- Model: `claude-haiku-4-5-20251001`.
- JPEG sent as a base64 `image` content block; PDF sent as a base64 `document` content block (native PDF input).
- One call per document returns both the transcription and the extracted fields as a single JSON object (see Section 16.6 for the prompt and schema). This avoids a second API call.
- Produces `raw_text` and `extracted_fields`.

Both methods must produce a non-empty `raw_text` to proceed to classification. If `raw_text` is empty or < 10 non-whitespace characters, the document is marked failed with `error_code: "EMPTY_TEXT"` and is not sent to Jev.

Text sent downstream is capped at 20,000 characters (≈ 5k tokens) to stay well under Jev's 32k-token state limit and keep latency low. Truncation adds `warnings: ["text_truncated_for_classification"]`.

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | see both methods with a one-line description, typical speed, and whether it uses a paid API | I can choose based on document quality and budget |
| 2 | Small Business Owner | see which document is being processed and at which stage | I know the system is working and roughly how long remains |
| 3 | Small Business Owner | be able to cancel a running batch | I can stop early if I picked the wrong files or method |
| 4 | Small Business Owner | see the raw text that was extracted for each document | I can judge whether the classification was based on good input |

#### Acceptance Criteria

1. Exactly one method is selectable; the Process control is disabled until a method is chosen.
2. Fast method: p95 ≤ 3 s per single-page JPEG at 300 DPI on the reference container (2 vCPU).
3. Precise method: p95 ≤ 8 s per single-page document (network dependent).
4. A document with < 10 non-whitespace characters after extraction is marked failed with `EMPTY_TEXT` and is not classified.
5. Cancel stops after the current document finishes; completed documents remain available in results; status becomes `cancelled`.
6. Each result records `extraction.method`, `extraction.duration_ms`, `extraction.page_count`, and (Fast only) `extraction.ocr_mean_confidence`.
7. If `ANTHROPIC_API_KEY` is not configured, the Precise option is shown disabled with the message _"Precise mode is not configured on this server."_

#### Validations & Messages

- No method selected: _"Select an extraction method to continue."_
- Extraction failure (Fast): _"Could not read text from {filename}. Try the Precise method for low-quality scans."_
- Extraction failure (Precise, API error): _"The Precise extraction service returned an error. Try again or use the Fast method."_
- Empty text: _"No readable text was found in {filename}."_
- Success: _"Extracted text from {n} of {N} documents."_

---

### 6.3 Classification via Jev

#### Details

Each document's text is sent to Jev as `state`, with a single `Choice` question whose criteria are the eleven document categories below. Jev returns the chosen category, a probability for every category (summing to 1), and a confidence value in [0, 1]. The system stores all three and applies **no** threshold logic in Phase 1 — confidence is shown to the user as information only.

**Categories and criteria (exact option keys and rubric descriptions sent to Jev):**

| Option key | Display label | Rubric description sent as `criteria` value |
| --- | --- | --- |
| `purchase_order` | Purchase Order | A buyer's formal order to a supplier listing items/services to purchase, quantities, prices, and a PO number. Issued by the buyer, addressed to the seller. |
| `transport_request` | Transport Request | A request to move goods: pickup/delivery addresses, dates, weights, pallet or parcel counts, carrier or freight instructions. Not an invoice for transport. |
| `sales_order` | Sales Order | A seller's confirmation of a customer's order: order number, customer details, items, quantities, prices, delivery date. Issued by the seller. |
| `invoice_from_supplier` | Invoice from Supplier | A supplier's demand for payment for goods/services delivered: invoice number, invoice date, due date, line items, tax, total due, payment instructions. |
| `credit_note` | Credit Note | A document issued by a seller reducing an amount owed, usually referencing an earlier invoice; shows a negative or credited amount. |
| `receipt` | Receipt | Proof that payment was made, typically point-of-sale: merchant name, date/time, items, amount paid, payment method, "paid" or "thank you". |
| `bill` | Bill | A statement of charges for a service or utility (electricity, telecom, rent, subscription) with account number, billing period, and amount due. Not an itemised goods invoice. |
| `packing_slip` | Packing Slip | A shipment document listing items and quantities packed, often with order/PO reference and no or minimal pricing; accompanies delivered goods. |
| `quotation` | Quotation | A seller's offer stating prices for specified goods/services, valid for a period; may be labelled Quote, Quotation, Estimate, or Proposal. |
| `quote_request` | Quote Request | A buyer's request asking a supplier to provide prices; may be labelled RFQ, Request for Quotation, or ask "please quote". |
| `none_of_the_above` | None of the above | Not a business transaction document of the kinds listed, or the text is too sparse or unrelated to decide. |

The `instructions` sent to Jev: _"Classify this scanned business document into exactly one document type based on its content, layout cues, and labels such as 'Invoice', 'PO', 'Quote', 'Receipt'. If it does not clearly match any listed type, choose none_of_the_above."_

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | see each document's type as a readable label | I can sort or act on it |
| 2 | Small Business Owner | see the confidence and the full probability breakdown | I can judge how much to trust the result and spot near-ties |
| 3 | Small Business Owner | see the model version that produced the answer | results are reproducible and explainable later |

#### Acceptance Criteria

1. Request is `POST https://api.typesafe.ai/v1/systemone` (or the equivalent SDK call) with `model = JEV_MODEL` (default `jev-latest`), the `state`, and exactly one `choice` question named `document_type` with the eleven option keys above.
2. Response fields `choice`, `probabilities`, `confidence`, and top-level `model` are all stored on the document result.
3. `choice` is one of the eleven option keys; anything else fails the document with `error_code: "JEV_INVALID_RESPONSE"`.
4. `429` and `529` responses are retried with exponential backoff (base 1 s, factor 2, max 4 attempts, honouring `retry-after` if present). `401` and `422` are not retried and fail the document.
5. If `TYPESAFE_API_KEY` is missing, the server refuses to start and logs a clear configuration error.
6. p95 ≤ 3 s per document for the Jev call.

#### Validations & Messages

- Jev unavailable after retries: _"The classification service is temporarily unavailable. Try again in a few minutes."_
- Jev auth/config error: _"Classification is not configured correctly on this server. Contact the administrator."_
- Success: _"Classified {n} of {N} documents."_

---

### 6.4 Field Extraction & Result JSON

#### Details

Each result includes a flat `extracted_fields` map (string keys in `snake_case`, string values). Missing fields are omitted, never null. The source of fields depends on the method:

- **Precise:** Claude Haiku returns the fields in the same call as the transcription (Section 16.6).
- **Fast:** A deterministic regex/heuristic extractor runs over `raw_text` (Section 16.7). Fewer fields will be found; this is expected and acceptable.

**Canonical field keys (Phase 1 vocabulary — extractors must use these keys and no others):**

`document_number`, `document_date`, `due_date`, `issuer_name`, `recipient_name`, `reference_number`, `subtotal`, `tax_amount`, `total_amount`, `currency`, `payment_terms`, `line_items_summary`

Values are strings exactly as they appear in the document (no normalisation of dates or numbers in Phase 1). `currency` is an ISO-4217 code when it can be inferred from a symbol or code (e.g. `$`→`USD` only if country cues suggest US; otherwise leave the symbol out and omit the field unless an explicit code is present). `line_items_summary` is a single string, e.g. `"3 line items: Widget A x10; Widget B x2; Freight x1"`.

**Per-document result schema** is defined authoritatively in Section 16.5.

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | view the extracted fields as a readable table and the full JSON | I can read it quickly or paste it into another tool |
| 2 | Small Business Owner | copy the JSON for one document or the whole batch to the clipboard | I can paste it into email, a ticket, or a script |
| 3 | Small Business Owner | download the whole batch as a `.json` file | I can keep a record or feed it into another system |
| 4 | Small Business Owner | download the whole batch as a `.csv` file | I can open it in a spreadsheet |

#### Data Templates

**CSV export** — one row per document, UTF-8, comma-separated, RFC 4180 quoting, header row exactly:

| filename* | status* | document_type* | document_type_label* | confidence* | extraction_method* | document_number | document_date | due_date | issuer_name | recipient_name | reference_number | subtotal | tax_amount | total_amount | currency | payment_terms | line_items_summary | warnings | error_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| inv_0412.pdf | completed | invoice_from_supplier | Invoice from Supplier | 0.91 | precise | INV-2026-0412 | 2026-09-28 | 2026-10-28 | Acme Supplies Pty Ltd | Blue Gum Café | PO-1187 | 1,180.00 | 118.00 | 1,298.00 | AUD | Net 30 | 4 line items: Coffee beans x20; Cups x500; ... |  |  |
| receipt_cafe.jpg | completed | receipt | Receipt | 0.97 | fast |  | 03/10/2026 |  | Officeworks |  |  |  |  | 46.85 | AUD |  |  |  |  |
| scan003.jpg | failed |  |  |  | fast |  |  |  |  |  |  |  |  |  |  |  |  |  | EMPTY_TEXT |

`warnings` is a `;`-joined list. Probability breakdown is not included in CSV (JSON only).

#### Acceptance Criteria

1. Every completed result contains `document_metadata`, `extraction`, `classification`, and `extracted_fields` objects conforming to Section 16.5.
2. `extracted_fields` uses only the canonical keys; unknown keys are dropped server-side before output.
3. Fields with no value are absent from the object (no `null`, no `""`).
4. JSON download is a single file named `document-results-{batch_id}.json` containing the batch object.
5. CSV download is named `document-results-{batch_id}.csv` with the header above, in that order.
6. Copy-to-clipboard copies pretty-printed JSON (2-space indent).
7. Raw text is included in JSON under `extraction.raw_text` (full, up to the 20,000-character cap) and is viewable in the UI.

#### Validations & Messages

- Copy success: _"JSON copied."_
- Download started: _"Downloading {filename}…"_

---

### 6.5 Batch Processing, Status & Summary

#### Details

A batch is processed sequentially in upload order by a background task in the API process. The client polls `GET /api/batches/{batch_id}` every 1.5 s. The batch exposes overall status, per-document status/stage, counts, and a summary once complete. The batch and all its data are removed from memory by a cleanup task at `completed_at + 15 min`, or immediately on `DELETE /api/batches/{batch_id}`.

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | process up to 20 documents with one action | I save repeated clicks |
| 2 | Small Business Owner | see a live count of completed, failed, and remaining documents | I know how long to wait |
| 3 | Small Business Owner | see a batch summary (counts, average confidence, total time) | I can gauge overall quality at a glance |
| 4 | Small Business Owner | retry only the failed documents | I don't re-process the ones that worked |
| 5 | Small Business Owner | start a new batch and have the old one cleared | my data doesn't linger on the server |

#### Acceptance Criteria

1. Batch status values are exactly: `queued`, `processing`, `completed`, `completed_with_errors`, `cancelled`.
2. Document status values are exactly: `queued`, `extracting`, `classifying`, `completed`, `failed`, `cancelled`.
3. A failure in one document never aborts the batch.
4. `summary` contains `total`, `completed`, `failed`, `cancelled`, `average_confidence` (completed only, 3 dp, `null` if none), `total_duration_ms`.
5. Retry failed: `POST /api/batches/{batch_id}/retry` re-queues only documents with status `failed`, reusing the same method; original bytes must still be in memory (within the 15-minute window) or the endpoint returns `410 Gone`.
6. The batch is unreachable (`404`) 15 minutes after completion.
7. At most 5 batches may be processing concurrently per server instance; a 6th submission returns `429` with _"The server is busy. Try again in a moment."_

#### Validations & Messages

- All succeeded: _"Processed {N} of {N} documents."_
- Partial: _"Processed {n} of {N} documents. {f} failed — you can retry them below."_
- All failed: _"None of the documents could be processed. Check the files and try again."_
- Cancelled: _"Batch cancelled. {n} document(s) were completed before cancelling."_
- Expired: _"This batch has expired. Upload the files again to process them."_

---

### 6.6 Error Handling & Resilience

#### Details

Every failure is classified with a stable `error_code` and a user-facing `error_message`. Error codes are enumerated in Section 16.8. Transient upstream errors are retried automatically; configuration errors fail fast; file-level errors fail only that document. The server never exposes stack traces, upstream raw error bodies, or API keys to the client. All logs are structured JSON and exclude document text and extracted fields.

#### User Journey

| # | As a / an | I want / must | So that |
| --- | --- | --- | --- |
| 1 | Small Business Owner | see an error message in plain language with a suggested next step | I can recover without technical help |
| 2 | Small Business Owner | keep the results that succeeded even when some fail | I don't lose work |

#### Acceptance Criteria

1. Every `failed` document has a non-empty `error_code` from Section 16.8 and an `error_message`.
2. Jev `429`/`529`: retried as in 6.3; Anthropic `429`/`529`/`5xx`: same policy. Final failure maps to `JEV_UNAVAILABLE` / `HAIKU_UNAVAILABLE`.
3. Any unhandled exception in document processing is caught, logged with batch and document ids, and recorded as `INTERNAL_ERROR` on that document; the batch continues.
4. Client shows a generic message with the `error_code` in a collapsible "details" area.
5. Server health endpoint `GET /api/health` returns `200` with `{ "status": "ok", "tesseract": true|false, "jev_configured": true|false, "haiku_configured": true|false }`.

---

## 7.0 Business Logic / Computation

1. **Method applies to batch.** `extraction_method ∈ {fast, precise}` is a batch attribute; all documents inherit it.
2. **Text gate.** `len(raw_text.strip()) < 10` ⇒ document fails with `EMPTY_TEXT`; Jev is not called.
3. **Classification text cap.** `classification_text = raw_text[:20000]`; if truncated add warning `text_truncated_for_classification`.
4. **Confidence.** Stored as returned by Jev (`answers.document_type.confidence`), rounded to 3 dp for display only; the raw value is kept in JSON.
5. **Average confidence.** `mean(confidence for d in documents if d.status == "completed")`, 3 dp; `null` when no completed documents.
6. **Field key whitelist.** `extracted_fields = {k: v for k, v in fields.items() if k in CANONICAL_FIELDS and isinstance(v, str) and v.strip()}`.
7. **PDF page handling.** Pages > 20 are dropped before extraction; warning `pdf_truncated_to_20_pages`.
8. **Fast-mode OCR fallback.** Per page: pdfplumber text ⇒ if `< 20` non-whitespace chars ⇒ rasterize at 300 DPI ⇒ Tesseract `--psm 6` ⇒ if `< 20` chars ⇒ Tesseract `--psm 3`.
9. **Retry policy (upstream APIs).** Attempts = 4; delays = 1 s, 2 s, 4 s (+ jitter ≤ 250 ms); respect `retry-after` header if larger. Retry on HTTP 429, 529, 5xx, and connection/timeouts. Do not retry 400, 401, 403, 404, 422.
10. **Timeouts.** Tesseract per page: 60 s. Anthropic request: 90 s. Jev request: 30 s.
11. **Batch expiry.** `expires_at = completed_at + 15 min`; a scheduler runs every 60 s and purges expired batches.
12. **Concurrency.** Documents within a batch are processed sequentially. Up to `MAX_CONCURRENT_BATCHES` (default 5) batches run in parallel per process.
13. **Phase 2 thresholds (informational, not implemented).** Suggested routing: `confidence ≥ 0.85` auto-accept; `0.60–0.85` review; `< 0.60` manual. These are to be tuned against real data and are explicitly out of Phase 1 scope.

---

## 8.0 Workflow

**Batch status lifecycle**

| Status | Trigger | Next States | Actor |
| --- | --- | --- | --- |
| queued | `POST /api/batches` accepted | processing | System |
| processing | Background task starts | completed, completed_with_errors, cancelled | System |
| completed | All documents `completed` | — (expires) | System |
| completed_with_errors | ≥ 1 document `failed`, none still running | processing (via retry), — (expires) | System / Small Business Owner |
| cancelled | `POST /api/batches/{id}/cancel` and current document finished | — (expires) | Small Business Owner |

**Document status lifecycle**

| Status | Trigger | Next States | Actor |
| --- | --- | --- | --- |
| queued | Batch created | extracting, cancelled | System |
| extracting | Processor picks the document | classifying, failed | System |
| classifying | Extraction produced ≥ 10 chars | completed, failed | System |
| completed | Jev answer stored, result assembled | — | System |
| failed | Any error with an `error_code` | queued (via retry) | System / Small Business Owner |
| cancelled | Batch cancelled before this document started | — | System |

---

## 9.0 Acceptance Criteria (Module-Level)

- A user with no account can upload 1–20 JPG/PDF files (≤ 10 MB each), pick Fast or Precise, process, and download JSON and CSV.
- Fast mode works with no external API other than Jev; Precise mode is disabled gracefully when the Anthropic key is absent.
- Every completed document has a Jev `choice` from the eleven keys, a `probabilities` map summing to 1 ± 0.01, a `confidence` in [0, 1], and the responding `model` id.
- A batch of 3 single-page JPEGs completes in ≤ 30 s (Fast) and ≤ 45 s (Precise) at p95 on the reference container.
- No document bytes, text, or fields persist beyond 15 minutes after batch completion; a restart of the server clears everything.
- The UI is usable on a 375 px-wide mobile viewport and passes WCAG 2.1 AA for keyboard focus, labels, and contrast.
- All error paths in Section 16.8 are reachable in tests and produce the specified `error_code`.

---

## 10.0 Non-Functional Requirements

- **Performance:** As in 6.2, 6.3, 9.0. Upload of 20 × 10 MB over a 20 Mbps link ≤ 90 s (network-bound; server must stream uploads, not buffer in a single string).
- **Security:** HTTPS at the edge (reverse proxy); API keys only via environment variables; server-side magic-byte validation; upload body limit 220 MB; per-IP rate limit 30 batch submissions/hour; CORS restricted to `ALLOWED_ORIGINS`; no file paths or stack traces in responses; dependencies pinned.
- **Privacy:** No persistence of documents or results; logs exclude content; Jev is not trained on requests (per vendor docs); Anthropic usage subject to the account's data settings.
- **Scalability:** Stateless container; in-memory batch store per instance means sticky sessions are required if > 1 replica (Phase 1 target is 1 replica). Phase 2 may move the batch store to Redis.
- **Observability:** Structured JSON logs (batch_id, document_id, stage, duration_ms, error_code); `/api/health`; request logging middleware.
- **Accessibility:** WCAG 2.1 AA — all controls keyboard reachable, visible focus, labelled inputs, ARIA live region for progress, contrast ≥ 4.5:1.
- **Browser support:** Latest two versions of Chrome, Firefox, Safari, Edge.

---

## 11.0 Out of Scope (Phase 1)

- Authentication, user accounts, multi-tenancy
- Persistent storage, history, search
- Manual override/correction of the classification
- Confidence-threshold routing or approval workflows
- Pushing results into external applications (QuickBooks, Xero, SAP, etc.) — Phase 2
- Non-English OCR or classification tuning
- Handwriting-specific models; image deskew/denoise beyond grayscale + rotation
- Parallel processing of documents within a batch
- Email/SMS notifications
- Custom categories or custom field schemas
- Formats other than JPEG and PDF (PNG, TIFF, HEIC)
- Date/number normalisation of extracted fields

---

## 12.0 Notifications & Alerts

| Trigger | Recipient | Channel | Content |
| --- | --- | --- | --- |
| Batch completes | Small Business Owner | In-app (toast + results view) | Summary message per 6.5 |
| Document fails | Small Business Owner | In-app (row badge + details) | `error_message` and retry affordance |
| Health check fails (`tesseract=false` or `jev_configured=false`) | Operator | Process log at `ERROR` | Configuration diagnostic |

No email, push, or SMS in Phase 1.

---

## 13.0 Dependencies

**System parameters / configuration (environment variables)**

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TYPESAFE_API_KEY` | Yes | — | Jev authentication (Bearer) |
| `TYPESAFE_BASE_URL` | No | `https://api.typesafe.ai` | Override for gateway/testing |
| `JEV_MODEL` | No | `jev-latest` | Pin to e.g. `jev-1.13.0` for reproducibility |
| `ANTHROPIC_API_KEY` | No | — | Enables Precise mode |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model id |
| `MAX_FILE_SIZE_MB` | No | `10` | Per-file limit |
| `MAX_FILES_PER_BATCH` | No | `20` | Batch size limit |
| `MAX_PDF_PAGES` | No | `20` | Pages processed per PDF |
| `CLASSIFICATION_TEXT_CAP` | No | `20000` | Characters sent to Jev |
| `BATCH_TTL_MINUTES` | No | `15` | Expiry after completion |
| `MAX_CONCURRENT_BATCHES` | No | `5` | Per-process limit |
| `ALLOWED_ORIGINS` | No | `http://localhost:5173` | CORS |
| `TESSERACT_CMD` | No | `tesseract` | Path to binary |
| `LOG_LEVEL` | No | `INFO` | Logging |

**Dependent modules (Phase 2, not built now):** persistence (Redis/Postgres), auth, integration connectors, review UI.

**External integrations**

1. **TypeSafe Jev** — `POST https://api.typesafe.ai/v1/systemone`, Bearer auth, JSON. Limits (per vendor, subject to change): 80 req/s, 100k tokens/s, 64k-token request budget, 32k tokens for state + longest question; input text only; priced per input token. Python SDK: `typesafe-sdk` (`pip install typesafe-sdk`, Python 3.10+), default model `jev-latest`, built-in retry/backoff.
2. **Anthropic Claude Haiku 4.5** — Messages API via `anthropic` Python SDK; image and PDF document content blocks; JSON-only response requested by prompt.
3. **Tesseract OCR 5.x** — system package (`tesseract-ocr`, `tesseract-ocr-eng`), accessed via `pytesseract`.
4. **Poppler** — system package (`poppler-utils`) for `pdf2image`.

---

## 14.0 Assumptions & Limitations

- Documents are predominantly English, machine-printed, and scanned at ≥ 200 DPI; accuracy degrades outside this.
- Jev accepts text only, so classification quality is bounded by extraction quality; the probability breakdown helps users spot weak inputs.
- Jev aliases move between versions; `JEV_MODEL` can be pinned when confidence behaviour must be stable.
- Vendor rate limits are dynamic; the retry policy and sequential processing keep Phase 1 well within them.
- Fast-mode field extraction is heuristic and will miss fields on unusual layouts; this is accepted for MVP.
- Single-instance deployment; in-memory batch store is lost on restart (acceptable: batches are short-lived by design).
- Currency inference is conservative; ambiguous symbols are omitted rather than guessed.

---

## 14.5 Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Jev rate limits (429) or overload (529) under load | Medium | High | Sequential per-batch processing; retry with backoff honouring `retry-after` (Section 7); `MAX_CONCURRENT_BATCHES` cap surfaces `SERVER_BUSY` early instead of queueing silently; log 429/529 counts |
| Low-quality scans produce `EMPTY_TEXT` or weak classification | High | Medium | Fast-mode PSM fallback; `OCR_FAILED` message recommends Precise; show `ocr_mean_confidence`, confidence colour, and raw text prominently so the user can judge the input |
| Anthropic PDF input latency or size limits | Medium | Medium | 20-page cap; 10 MB file cap; 90 s timeout; retry then `HAIKU_UNAVAILABLE` with fallback-to-Fast messaging |
| In-memory batch store lost on restart | High (by design) | Low | 15-minute TTL documented in UI copy ("This batch expires at HH:MM"); Phase 2 moves store to Redis |
| Heuristic field extractor misses common layouts | High | Medium | Accepted for MVP; log which canonical keys were found per document (counts only, no values) to prioritise pattern improvements |
| Jev alias `jev-latest` moves and shifts confidence values | Medium | Medium | `JEV_MODEL` env var; responding `model` id recorded on every result |
| Haiku returns non-JSON or wrong shape | Medium | Low | `temperature=0`, JSON-only prompt, one corrective retry, then `HAIKU_BAD_OUTPUT`; canonical-key whitelist |
| Multi-replica deployment breaks in-memory store | Low (Phase 1 is 1 replica) | High | Documented single-replica constraint; sticky sessions required if scaled before Phase 2 |

---

## 15.0 Tracking Reference

To be assigned at project kickoff.

---

## 16.0 Technical Specification (for implementation / coding agents)

### 16.1 Stack

| Layer | Choice | Version / notes |
| --- | --- | --- |
| Language | Python | 3.12 |
| Web framework | FastAPI | ≥ 0.115, served by Uvicorn |
| Background work | FastAPI `BackgroundTasks` + `asyncio` task registry | No Celery/Redis in Phase 1 |
| OCR | `pytesseract` ≥ 0.3.13 + Tesseract 5.x (`eng`) | `--psm 6` default |
| PDF | `pdfplumber` ≥ 0.11, `pdf2image` ≥ 1.17 (needs Poppler), `pypdf` ≥ 4 for page counting | |
| Imaging | `Pillow` ≥ 10 | grayscale, rotation |
| Jev client | `typesafe-sdk` (latest) via `TypeSafeClient` / `AsyncTypeSafeClient` | fall back to `httpx` raw call if SDK unavailable; contract in 16.6 |
| Claude client | `anthropic` (latest) | `messages.create` |
| HTTP | `httpx` ≥ 0.27 | timeouts per Section 7 |
| Validation | `pydantic` v2 | all schemas in 16.5 |
| File type sniffing | `python-magic` or manual magic-byte check | manual is acceptable |
| Frontend | React 18 + TypeScript + Vite 5 | single-page app |
| Styling | Tailwind CSS 3 | no component library required |
| Frontend tests | Vitest + React Testing Library | |
| Backend tests | `pytest`, `pytest-asyncio`, `respx` (mock httpx), `httpx.AsyncClient` test client | |
| Packaging | Docker (multi-stage); `docker-compose.yml` for local dev | |
| Lint/format | `ruff`, `mypy --strict` (backend); `eslint`, `prettier` (frontend) | |

### 16.2 Repository layout

```
docclassify/
├── README.md
├── DECISIONS.md                     # agent records any unspecified choices here
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, routers, lifespan (config check, cleanup scheduler)
│   │   ├── config.py                # pydantic-settings; env vars from Section 13
│   │   ├── schemas.py               # pydantic models from 16.5
│   │   ├── errors.py                # ErrorCode enum + messages from 16.8
│   │   ├── store.py                 # in-memory BatchStore with TTL purge
│   │   ├── api/
│   │   │   ├── batches.py           # routes from 16.4
│   │   │   └── health.py
│   │   ├── services/
│   │   │   ├── validation.py        # magic bytes, size, count, page count
│   │   │   ├── extraction/
│   │   │   │   ├── base.py          # Extractor protocol -> ExtractionResult
│   │   │   │   ├── fast.py          # pytesseract + pdfplumber + pdf2image
│   │   │   │   └── precise.py       # Anthropic Haiku
│   │   │   ├── fields/
│   │   │   │   ├── canonical.py     # CANONICAL_FIELDS, whitelist filter
│   │   │   │   └── heuristic.py     # regex extractor for fast mode (16.7)
│   │   │   ├── classification/
│   │   │   │   └── jev.py           # Jev client wrapper, categories, retry
│   │   │   ├── processor.py         # per-batch orchestration (sequential)
│   │   │   └── export.py            # JSON/CSV builders
│   │   └── logging.py               # structured JSON logging
│   └── tests/
│       ├── fixtures/                # sample jpg/pdf (tiny, synthetic)
│       ├── test_validation.py
│       ├── test_fast_extractor.py
│       ├── test_precise_extractor.py
│       ├── test_jev.py
│       ├── test_processor.py
│       ├── test_api.py
│       └── test_export.py
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/client.ts            # typed fetch wrappers for 16.4
        ├── types.ts                 # mirrors 16.5
        ├── components/
        │   ├── Dropzone.tsx
        │   ├── FileList.tsx
        │   ├── MethodSelector.tsx
        │   ├── ProgressPanel.tsx
        │   ├── ResultsTable.tsx
        │   ├── ResultDetail.tsx     # fields table, probabilities, raw text, JSON
        │   ├── ExportBar.tsx
        │   └── Toast.tsx
        └── hooks/useBatch.ts        # submit, poll, cancel, retry, reset
```

### 16.3 Local run

```
# system deps (Debian/Ubuntu): tesseract-ocr tesseract-ocr-eng poppler-utils libmagic1
cp .env.example .env            # set TYPESAFE_API_KEY, optionally ANTHROPIC_API_KEY
docker compose up --build       # backend :8000, frontend :5173
```

`docker-compose.yml` runs two services (`backend`, `frontend`); the backend image installs the system packages above in the Dockerfile.

### 16.4 HTTP API (backend)

Base path `/api`. All responses JSON unless noted. Error body shape: `{ "error_code": "...", "error_message": "..." }`.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `200 HealthResponse` |
| `POST` | `/batches` | `multipart/form-data`: `extraction_method` (`fast`\|`precise`), `files[]` (1–20) | `202 BatchCreated { batch_id, status, documents:[{document_id, filename, status, error_code?}] }`. **Whole-batch rejections** (no batch is created): `400 TOO_MANY_FILES`, `400 INVALID_METHOD`, `400` no files, `413 UPLOAD_TOO_LARGE`, `429 SERVER_BUSY`, `503 PRECISE_NOT_CONFIGURED`. **Per-file problems** (batch is created): each invalid file becomes a document with `status: "failed"` and `error_code` ∈ {`INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, `CORRUPT_FILE`}; if every file is invalid the batch is created and immediately terminal as `completed_with_errors` |
| `GET` | `/batches/{batch_id}` | — | `200 Batch` (full, including results for completed documents); `404` unknown/expired |
| `POST` | `/batches/{batch_id}/cancel` | — | `202 Batch`; `409` if not processing |
| `POST` | `/batches/{batch_id}/retry` | — | `202 Batch` (failed docs re-queued); `409` if processing; `410` if originals purged |
| `GET` | `/batches/{batch_id}/export.json` | — | `200 application/json`, `Content-Disposition: attachment; filename="document-results-{batch_id}.json"` |
| `GET` | `/batches/{batch_id}/export.csv` | — | `200 text/csv; charset=utf-8`, attachment, header per 6.4 |
| `DELETE` | `/batches/{batch_id}` | — | `204`; purges immediately |

Polling interval recommended to clients: 1500 ms. `GET /batches/{id}` is cheap (in-memory) and always returns the **full** `Batch` object, including completed `DocumentResult`s, while the batch is still `processing` — partial results are visible and exportable before completion (export endpoints work in any state and include only documents that are terminal at call time).

`Idempotency-Key` header support on `POST /batches` is **out of scope** for Phase 1; duplicate submissions create duplicate batches.

### 16.5 Data schemas (pydantic / TypeScript — authoritative)

```jsonc
// Batch (GET /api/batches/{id} and export.json)
{
  "batch_id": "b_01J9ZK8Q7X5N2M4P6R8T0V2W4Y",      // ULID
  "status": "completed_with_errors",            // queued|processing|completed|completed_with_errors|cancelled
  "extraction_method": "precise",               // fast|precise
  "created_at": "2026-10-04T03:12:45.120Z",
  "completed_at": "2026-10-04T03:13:21.904Z",   // null until terminal
  "expires_at": "2026-10-04T03:28:21.904Z",     // null until terminal
  "summary": {                                  // null until terminal
    "total": 3, "completed": 2, "failed": 1, "cancelled": 0,
    "average_confidence": 0.902,
    "total_duration_ms": 36784
  },
  "documents": [ /* DocumentResult[] in upload order */ ]
}
```

```jsonc
// DocumentResult
{
  "document_id": "d_01J9ZK8Q7XABCDEF",
  "filename": "inv_0412.pdf",
  "status": "completed",                        // queued|extracting|classifying|completed|failed|cancelled
  "error_code": null,                           // string from 16.8 when failed
  "error_message": null,
  "warnings": ["pdf_truncated_to_20_pages"],    // [] when none
  "document_metadata": {
    "mime_type": "application/pdf",             // image/jpeg | application/pdf
    "size_bytes": 184233,
    "page_count": 2,                            // pages processed (after cap)
    "uploaded_at": "2026-10-04T03:12:45.120Z"
  },
  "extraction": {                               // null until extraction done
    "method": "precise",
    "duration_ms": 4120,
    "ocr_mean_confidence": null,                // number 0-100 for fast, null for precise
    "raw_text": "TAX INVOICE\nAcme Supplies Pty Ltd ...",
    "truncated_for_classification": false
  },
  "classification": {                           // null until classified
    "document_type": "invoice_from_supplier",   // option key
    "document_type_label": "Invoice from Supplier",
    "confidence": 0.91,
    "probabilities": {
      "purchase_order": 0.02, "transport_request": 0.0, "sales_order": 0.03,
      "invoice_from_supplier": 0.91, "credit_note": 0.0, "receipt": 0.01,
      "bill": 0.03, "packing_slip": 0.0, "quotation": 0.0,
      "quote_request": 0.0, "none_of_the_above": 0.0
    },
    "model": "jev-1.13.0",                      // from Jev response top-level `model`
    "duration_ms": 640
  },
  "extracted_fields": {                         // flat; canonical keys only; no nulls
    "document_number": "INV-2026-0412",
    "document_date": "28/09/2026",
    "due_date": "28/10/2026",
    "issuer_name": "Acme Supplies Pty Ltd",
    "recipient_name": "Blue Gum Café",
    "reference_number": "PO-1187",
    "subtotal": "1,180.00",
    "tax_amount": "118.00",
    "total_amount": "1,298.00",
    "currency": "AUD",
    "payment_terms": "Net 30",
    "line_items_summary": "4 line items: Coffee beans 1kg x20; Takeaway cups x500; Lids x500; Delivery x1"
  }
}
```

```jsonc
// HealthResponse
{ "status": "ok", "tesseract": true, "jev_configured": true, "haiku_configured": false, "version": "1.0.0" }
```

Label map (`document_type` → `document_type_label`) is the table in 6.3.

**Schema invariants (enforce in pydantic validators and tests)**
- `classification.probabilities` keys are exactly the eleven option keys and values sum to `1.0 ± 0.01`; otherwise the document fails with `JEV_INVALID_RESPONSE`.
- `classification.confidence` ∈ [0, 1]; `classification.document_type` must equal the argmax key of `probabilities` (if Jev's `choice` disagrees, trust `choice` and add warning `choice_not_argmax`).
- `extracted_fields` values are **always strings**, never numbers, booleans, or nulls; the heuristic extractor must stringify, and the Haiku post-filter must drop non-string values.
- `HealthResponse.version` is read from the backend package version (`pyproject.toml`), never hard-coded.
- `warnings` is top-level per document only in Phase 1; an `extraction.warnings` array is reserved for Phase 2 and must not be emitted now.
- Timestamps are ISO 8601 UTC with millisecond precision and `Z` suffix.

### 16.6 External service contracts

**16.6.1 Jev classification (TypeSafe System One)**

Request (raw HTTP; the SDK call is equivalent):

```http
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer {TYPESAFE_API_KEY}
Content-Type: application/json
```
```json
{
  "model": "jev-latest",
  "state": {
    "document_text": "<classification_text, ≤ 20000 chars>",
    "filename": "inv_0412.pdf",
    "page_count": 2
  },
  "questions": {
    "document_type": {
      "type": "choice",
      "instructions": "Classify this scanned business document into exactly one document type based on its content, layout cues, and labels such as 'Invoice', 'PO', 'Quote', 'Receipt'. If it does not clearly match any listed type, choose none_of_the_above.",
      "criteria": {
        "purchase_order": "A buyer's formal order to a supplier listing items/services to purchase, quantities, prices, and a PO number. Issued by the buyer, addressed to the seller.",
        "transport_request": "A request to move goods: pickup/delivery addresses, dates, weights, pallet or parcel counts, carrier or freight instructions. Not an invoice for transport.",
        "sales_order": "A seller's confirmation of a customer's order: order number, customer details, items, quantities, prices, delivery date. Issued by the seller.",
        "invoice_from_supplier": "A supplier's demand for payment for goods/services delivered: invoice number, invoice date, due date, line items, tax, total due, payment instructions.",
        "credit_note": "A document issued by a seller reducing an amount owed, usually referencing an earlier invoice; shows a negative or credited amount.",
        "receipt": "Proof that payment was made, typically point-of-sale: merchant name, date/time, items, amount paid, payment method, 'paid' or 'thank you'.",
        "bill": "A statement of charges for a service or utility (electricity, telecom, rent, subscription) with account number, billing period, and amount due. Not an itemised goods invoice.",
        "packing_slip": "A shipment document listing items and quantities packed, often with order/PO reference and no or minimal pricing; accompanies delivered goods.",
        "quotation": "A seller's offer stating prices for specified goods/services, valid for a period; may be labelled Quote, Quotation, Estimate, or Proposal.",
        "quote_request": "A buyer's request asking a supplier to provide prices; may be labelled RFQ, Request for Quotation, or ask 'please quote'.",
        "none_of_the_above": "Not a business transaction document of the kinds listed, or the text is too sparse or unrelated to decide."
      }
    }
  }
}
```

Response (store `model`, and `answers.document_type.{choice, probabilities, confidence}`):

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "document_type": {
      "type": "choice",
      "choice": "invoice_from_supplier",
      "probabilities": { "invoice_from_supplier": 0.91, "sales_order": 0.03, "bill": 0.03, "purchase_order": 0.02, "receipt": 0.01, "transport_request": 0.0, "credit_note": 0.0, "packing_slip": 0.0, "quotation": 0.0, "quote_request": 0.0, "none_of_the_above": 0.0 },
      "confidence": 0.91
    }
  },
  "usage": { "input_tokens": 1842, "output_tokens": 34 }
}
```

Python SDK equivalent:

```python
from typesafe_sdk import AsyncTypeSafeClient, Choice

async with AsyncTypeSafeClient() as client:              # reads TYPESAFE_API_KEY
    resp = await client.system_one(
        model=settings.jev_model,
        state={"document_text": text, "filename": filename, "page_count": pages},
        questions={"document_type": Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)},
    )
answer = resp.choices["document_type"]                    # .choice, .probabilities, .confidence
model_used = resp.model
```

Errors: `401` → `JEV_AUTH_ERROR` (no retry); `422` → `JEV_BAD_REQUEST` (no retry, log body); `429`/`529`/`5xx`/timeout → retry per Section 7 then `JEV_UNAVAILABLE`.

Alignment notes with the live API docs:
- `state` may be a plain string or an object; the object shape above is used so `filename` and `page_count` are available as context. Do not put anything else in `state`.
- A Choice supports up to 255 options; this question uses 11. Do not add options.
- Prefer the official `typesafe-sdk` (`AsyncTypeSafeClient` + `Choice`), which already retries 429/529 with backoff and honours `retry-after`. Only if the package cannot be installed, call the HTTP endpoint with `httpx` using the exact body above and implement the retry policy from Section 7 yourself. Record which path was used in `DECISIONS.md`.
- Store the response's top-level `model` (versioned id), not the alias that was requested.

**16.6.2 Claude Haiku precise extraction (Anthropic Messages API)**

```python
import anthropic, base64, json

client = anthropic.AsyncAnthropic()                       # reads ANTHROPIC_API_KEY
content_block = (
    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    if mime == "image/jpeg" else
    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
)
msg = await client.messages.create(
    model=settings.haiku_model,                           # claude-haiku-4-5-20251001
    max_tokens=4096,
    temperature=0,
    system=HAIKU_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": [content_block, {"type": "text", "text": HAIKU_USER_PROMPT}]}],
)
text = "".join(b.text for b in msg.content if b.type == "text")
payload = json.loads(strip_code_fences(text))
```

`HAIKU_SYSTEM_PROMPT`:

```
You are a precise document transcription engine for scanned business documents.
You output ONLY a single JSON object and nothing else — no prose, no markdown fences.
```

`HAIKU_USER_PROMPT`:

```
Transcribe the full text of this document in reading order, preserving line breaks.
Then extract the fields listed below if, and only if, they are explicitly present.
Return exactly this JSON shape:

{
  "raw_text": "<full transcription>",
  "fields": {
    "document_number": "<e.g. invoice/PO/order/quote number>",
    "document_date": "<date as written>",
    "due_date": "<as written>",
    "issuer_name": "<company that issued the document>",
    "recipient_name": "<company/person it is addressed to>",
    "reference_number": "<related PO/order/invoice reference>",
    "subtotal": "<as written>",
    "tax_amount": "<as written>",
    "total_amount": "<as written>",
    "currency": "<ISO 4217 code only if explicitly shown or unambiguous>",
    "payment_terms": "<as written>",
    "line_items_summary": "<'N line items: desc x qty; desc x qty; ...' max 300 chars>"
  }
}

Rules: omit any field you cannot find (do not output null or empty strings);
copy values exactly as written; do not infer or calculate; do not classify the document.
```

Call parameters are mandatory: `temperature=0`, `max_tokens=4096`.

Post-processing (in order):
1. Strip code fences; `json.loads`.
2. Validate: top-level is an object; `raw_text` is a **non-empty** string; `fields` is an object (missing `fields` → treat as `{}`).
3. Filter `fields`: keep only canonical keys whose values are non-empty strings; drop everything else silently.
4. If step 1 or 2 fails, retry the call **once** with an appended user line `"Your previous output was not valid JSON matching the required shape. Output only the JSON object."`; on second failure → `HAIKU_BAD_OUTPUT`.

API errors: `401` → `HAIKU_AUTH_ERROR`; `429`/`529`/`5xx`/timeout → retry per Section 7 then `HAIKU_UNAVAILABLE`.

### 16.7 Fast-mode heuristic field extractor (minimum behaviour)

Operate on `raw_text` (case-insensitive, line-oriented). Omit a key when no match. All returned values are strings.

**Ordering rule:** extraction order matters for overlapping patterns. Run in this sequence: `document_number` → `reference_number` → dates → names → amounts → `currency` → `payment_terms` → `line_items_summary`. Within a key, prefer the **first match in document order**. A line consumed by `document_number` is excluded from `reference_number` matching.

Reference implementation skeleton:

```python
# backend/app/services/fields/heuristic.py
import re
from dataclasses import dataclass, field

AMOUNT = r"-?\(?[$€£]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?"
DATE = r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"
DOC_NO = re.compile(r"(invoice|inv|tax invoice|purchase order|po|order|quotation|quote|receipt|credit note)\s*(?:no\.?|number|#|:)?\s*[:#]?\s*([A-Z]{0,5}[-/]?\d[\w\-/]{2,})", re.I)
REF_NO = re.compile(r"\b(?:ref(?:erence)?|po|your order|order ref)\s*(?:no\.?|#|:)?\s*[:#]?\s*([A-Z0-9][\w\-/]{2,})", re.I)
AMOUNT_RE = re.compile(AMOUNT)

@dataclass
class Ctx:
    lines: list[str]
    used: set[int] = field(default_factory=set)   # line indexes already consumed

def _first_line(ctx: Ctx, pred) -> int | None:
    for i, ln in enumerate(ctx.lines):
        if i not in ctx.used and pred(ln):
            return i
    return None

def _amount_on(ctx: Ctx, keyword_re: str, last: bool = False) -> str | None:
    hits = [(i, AMOUNT_RE.findall(ln)) for i, ln in enumerate(ctx.lines) if re.search(keyword_re, ln, re.I)]
    hits = [(i, a) for i, a in hits if a]
    if not hits: return None
    i, amts = hits[-1] if last else hits[0]
    return re.sub(r"[$€£\s]", "", amts[-1])     # last amount on the line, symbols stripped

def extract(raw_text: str) -> dict[str, str]:
    ctx = Ctx([ln.strip() for ln in raw_text.splitlines() if ln.strip()])
    out: dict[str, str] = {}
    # 1 document_number
    for i, ln in enumerate(ctx.lines):
        if m := DOC_NO.search(ln):
            out["document_number"] = m.group(2); ctx.used.add(i); break
    # 2 reference_number (skip consumed line)
    for i, ln in enumerate(ctx.lines):
        if i in ctx.used: continue
        if m := REF_NO.search(ln):
            out["reference_number"] = m.group(1); ctx.used.add(i); break
    # 3 dates
    # ... document_date (line containing 'date' first, else first date anywhere), due_date (line containing 'due')
    # 4 names, 5 amounts (subtotal / tax_amount / total_amount via _amount_on), 6 currency, 7 payment_terms, 8 line_items_summary
    return {k: str(v) for k, v in out.items() if v and str(v).strip()}
```

Fill in the elided steps using the pattern table below; every branch must be covered by a unit test.

| Key | Patterns (illustrative; implement as compiled regexes) |
| --- | --- |
| `document_number` | `(invoice|inv|tax invoice|po|purchase order|order|quote|quotation|receipt|credit note)\s*(no\.?|number|#|:)?\s*[:#]?\s*([A-Z]{0,5}[-/]?\d[\w\-/]{2,})` → group 3 |
| `document_date` | first date-like token: `\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b` preferring one on a line containing `date` |
| `due_date` | same date regex on a line containing `due` |
| `issuer_name` | first non-empty line of the document that contains any of `pty|ltd|llc|inc|limited|co\.|corp|gmbh` or, failing that, the first non-empty line ≤ 60 chars |
| `recipient_name` | first non-empty line following a line matching `^(bill to|ship to|to|customer|sold to)\b` |
| `reference_number` | `\b(ref(erence)?|po|your order|order ref)\s*(no\.?|#|:)?\s*[:#]?\s*([A-Z0-9][\w\-/]{2,})` on a line not already used for `document_number` |
| `subtotal` | amount on a line containing `subtotal|sub total|net` |
| `tax_amount` | amount on a line containing `gst|vat|tax` (not `total`) |
| `total_amount` | amount on the last line containing `total|amount due|balance due|grand total` |
| `currency` | explicit code `\b(AUD|USD|EUR|GBP|NZD|CAD|SGD|INR|JPY)\b`; otherwise omit |
| `payment_terms` | `\b(net\s*\d{1,3}|due on receipt|cod|\d{1,3}\s*days)\b` |
| `line_items_summary` | count lines matching `^.{3,60}\s+\d+(\.\d+)?\s+[\d,]+\.\d{2}` (desc qty price) → `"N line items: " + first 3 descriptions joined by "; "`; omit if N = 0 |

Amount regex: `-?\(?[$€£]?\s?\d{1,3}(,\d{3})*(\.\d{2})\)?`. Strip currency symbols and whitespace from values; keep thousands separators and decimals. When multiple amounts appear on a matching line, take the last one.

**Required fixtures for the heuristic extractor tests** (see 16.10): (a) a two-page supplier invoice with subtotal, GST, total, PO reference and Net 30 terms; (b) a point-of-sale receipt with tax and total but no document number; (c) a quotation with a validity line. Each fixture asserts the exact expected `extracted_fields` dict and asserts `document_number ≠ reference_number`.

### 16.8 Error codes

**Scope semantics:** `batch`-scoped codes are returned as the HTTP error body of a request and never appear on a `DocumentResult`. `document`-scoped codes appear only in `DocumentResult.error_code` (HTTP column is `—`, or the status used when the file is rejected inside `POST /batches`, in which case the batch is still created). `INTERNAL_ERROR` may appear in either position. `UPLOAD_TOO_LARGE` must be enforced by the server's body-size limit (FastAPI/Uvicorn or reverse proxy) and mapped to this code; it is not left to the framework default response.

| `error_code` | Scope | HTTP (when direct) | `error_message` shown to user |
| --- | --- | --- | --- |
| `INVALID_FILE_TYPE` | document | 400 | Only JPG, JPEG, and PDF files are supported. |
| `FILE_TOO_LARGE` | document | 400 | {filename} is larger than 10 MB and was skipped. |
| `TOO_MANY_FILES` | batch | 400 | You can process up to 20 files per batch. |
| `UPLOAD_TOO_LARGE` | batch | 413 | The upload is too large. Keep the total under 220 MB. |
| `NO_FILES` | batch | 400 | Add at least one file to continue. |
| `INVALID_METHOD` | batch | 400 | Choose Fast or Precise extraction. |
| `PRECISE_NOT_CONFIGURED` | batch | 503 | Precise mode is not configured on this server. |
| `SERVER_BUSY` | batch | 429 | The server is busy. Try again in a moment. |
| `CORRUPT_FILE` | document | — | {filename} could not be read. The file may be corrupted. |
| `EMPTY_TEXT` | document | — | No readable text was found in {filename}. |
| `OCR_FAILED` | document | — | Could not read text from {filename}. Try the Precise method for low-quality scans. |
| `HAIKU_UNAVAILABLE` | document | — | The Precise extraction service is temporarily unavailable. Try again or use Fast. |
| `HAIKU_AUTH_ERROR` | document | — | Precise extraction is not configured correctly on this server. |
| `HAIKU_BAD_OUTPUT` | document | — | Precise extraction returned an unexpected result for {filename}. Try again. |
| `JEV_UNAVAILABLE` | document | — | The classification service is temporarily unavailable. Try again in a few minutes. |
| `JEV_AUTH_ERROR` | document | — | Classification is not configured correctly on this server. Contact the administrator. |
| `JEV_BAD_REQUEST` | document | — | The document could not be classified. |
| `JEV_INVALID_RESPONSE` | document | — | The classification service returned an unexpected result. |
| `BATCH_NOT_FOUND` | batch | 404 | This batch has expired. Upload the files again to process them. |
| `BATCH_EXPIRED` | batch | 410 | The original files have been cleared and cannot be retried. |
| `BATCH_STATE_CONFLICT` | batch | 409 | This action is not available while the batch is in its current state. |
| `INTERNAL_ERROR` | document/batch | 500 | Something went wrong processing {filename}. Try again. |

### 16.9 Minimal screen inventory (sufficient without a design file)

Single page, three vertical states driven by `useBatch` hook state:

1. **Setup** — `Dropzone` (click or drag; shows accepted extensions and limits), `FileList` (name, size, remove button, inline rejection reason), `MethodSelector` (two radio cards with exact copy: **Fast** — *"Python OCR (Tesseract) — free, ~1–3 s per page, best for clean scans"*; **Precise** — *"Claude Haiku 4.5 — paid API, ~3–8 s per page, better on low-quality or complex layouts"*. When `health.haiku_configured=false` the Precise card is disabled, shows *"Not configured: ANTHROPIC_API_KEY is not set on this server"*, and has a tooltip/`aria-describedby` pointing to the README env-var section), primary **Process N files** button (disabled until ≥ 1 valid file and a method).
2. **Processing** — `ProgressPanel` with a sticky header: overall bar (`completed+failed / total`), a prominent current-item line *"Extracting inv_0412.pdf (2/7)…"* / *"Classifying …"*, and **Cancel**. Per-document rows show status badge, stage, and elapsed time. An ARIA live region (`aria-live="polite"`) announces *"Processed n of N documents"* on each change and the final summary sentence on completion. On cancel: completed results are kept, remaining documents are shown as `cancelled`, and the Results state is entered with export enabled for what finished.
3. **Results** — summary strip (total, completed, failed, cancelled, average confidence, duration; receives focus on entry), `ExportBar` (**Copy batch JSON**, **Download JSON**, **Download CSV**, **Retry failed** when any, **Start new batch** → `DELETE` then reset), `ResultsTable` (sortable; columns: filename, type label, confidence pill coloured green ≥ 85 % / amber 60–85 % / red < 60 %, status badge, expand), `ResultDetail` (fields table; probability bars sorted descending with the chosen type highlighted; raw text in a scrollable `pre`; pretty JSON with **Copy document JSON**).

Responsive at 375 px; all controls focusable; toasts via `Toast` with `role="status"`.

### 16.10 Test plan (must pass in CI)

**Backend unit**
- `validation`: accepts JPEG/PDF by magic bytes; rejects renamed PNG; enforces size/count; counts PDF pages; applies 20-page cap with warning.
- `fast extractor`: synthetic JPEG with rendered text → `raw_text` contains the text; text-layer PDF uses pdfplumber (no OCR call); image-only PDF triggers OCR fallback; empty image → `EMPTY_TEXT`.
- `heuristic fields`: the three required fixtures from 16.7 (two-page invoice with tax/total/PO ref; receipt with tax/total; quotation) → exact expected dicts; all values are `str`; no non-canonical keys; `document_number` and `reference_number` never come from the same line.
- `precise extractor` (mocked Anthropic): parses valid JSON; strips fences; retries once on invalid JSON then `HAIKU_BAD_OUTPUT`; maps 429→retry→`HAIKU_UNAVAILABLE`.
- `jev` (mocked via `respx`): builds exact request body from 16.6.1; parses response; rejects unknown `choice`; rejects probabilities not summing to 1 ± 0.01 or with wrong key set (`JEV_INVALID_RESPONSE`); retry on 429/529 with backoff; no retry on 401/422; records `model`.
- `processor`: sequential order preserved; one failing doc doesn't stop batch; status transitions per Section 8; cancel after current doc; retry re-queues only failed; TTL purge removes batch.
- `export`: JSON equals store object; CSV header exact; quoting of commas/newlines; `warnings` joined by `;`.

**Backend API (httpx test client)**
- `POST /batches` happy path returns 202 with document list; 0 files → 400 `NO_FILES`; 21 files → 400 `TOO_MANY_FILES`; body > 220 MB → 413 `UPLOAD_TOO_LARGE`; precise without key → 503; 6th concurrent → 429; a mix of one valid and one renamed PNG creates a batch where the PNG is `failed/INVALID_FILE_TYPE`.
- `GET /batches/{id}` during processing returns the full object with completed documents populated and pending ones `queued`/`extracting`.
- `GET /batches/{id}` reflects progress; 404 after purge.
- Cancel/retry state conflicts return 409; retry after purge returns 410.
- `/health` reports tesseract and key presence.

**Frontend**
- Dropzone rejects wrong type/size with messages; Process disabled logic; MethodSelector disables Precise from health with the exact reason text; polling updates the sticky progress header and current-item line; cancel keeps completed results and enables export; results render fields, confidence pill colours at the 0.60/0.85 boundaries, and probability bars with the chosen type highlighted; table sorts by confidence; export buttons trigger downloads (mock); both copy buttons copy the correct scope; live region text updates; focus moves to summary on completion; keyboard navigation through all controls.

**Non-functional**
- Load: 5 concurrent batches × 3 JPEGs (Fast) complete within limits on 2 vCPU container.
- Security: upload > 220 MB rejected; API keys never appear in any response or log (assert in tests with a sentinel key).

### 16.11 Definition of done

- All tests in 16.10 pass; `ruff`, `mypy --strict`, `eslint` clean.
- `docker compose up` yields a working app with only `TYPESAFE_API_KEY` set (Fast mode) and full function with `ANTHROPIC_API_KEY` added.
- `README.md` covers setup, env vars, and a curl walkthrough of 16.4.
- `DECISIONS.md` lists every choice made where this PRD was silent (see 16.12).
- Manual acceptance: process the three fixture documents in both modes and verify the JSON matches 16.5 and the CSV matches 6.4.

---

### 16.12 DECISIONS.md — required contents

`DECISIONS.md` is a dated, append-only log. Each entry: *context → decision → alternatives considered → consequence*. At minimum it **must** record:

1. Any deviation from an external API contract as documented by the vendor at build time (Jev request/response, Anthropic Messages API content blocks or parameters, Tesseract flags), with a link to the doc page relied upon.
2. Jev client path used: official `typesafe-sdk` vs raw `httpx`, and the SDK version pinned.
3. Magic-byte detection approach: `python-magic`/`libmagic` vs pure-Python header check.
4. Exact Tesseract configuration: version, `--psm` fallback order, OSD rotation threshold, DPI used for rasterisation, and the `--oem` value.
5. PDF text-layer threshold (characters per page) that triggers OCR fallback, if different from 20.
6. CSV writer/quoting library and dialect (e.g. Python `csv` with `QUOTE_MINIMAL`), and newline handling inside cells.
7. ULID generation library and whether ids are monotonic within a process.
8. Timestamp source and precision; timezone handling.
9. In-memory store implementation (dict + asyncio lock vs other) and the purge scheduler mechanism.
10. Body-size limit enforcement point (framework setting vs reverse proxy) for `UPLOAD_TOO_LARGE`.
11. Any canonical field a Haiku response frequently returns that is not in the whitelist (log as an observation, do not add the key).
12. Open questions the PRD does not answer, with the interim choice made.

---

*End of document.*
