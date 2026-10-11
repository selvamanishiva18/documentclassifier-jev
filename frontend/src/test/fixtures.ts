import type { Batch, DocumentResult, DocumentType, HealthResponse } from '../types';
import { DOCUMENT_TYPE_LABELS } from '../types';

const KEYS = Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[];

export function probabilities(
  chosen: DocumentType,
  confidence: number,
): Record<DocumentType, number> {
  const rest = (1 - confidence) / (KEYS.length - 1);
  return Object.fromEntries(KEYS.map((k) => [k, k === chosen ? confidence : rest])) as Record<
    DocumentType,
    number
  >;
}

export function makeDoc(overrides: Partial<DocumentResult> = {}): DocumentResult {
  return {
    document_id: 'd_1',
    filename: 'a.pdf',
    status: 'queued',
    error_code: null,
    error_message: null,
    warnings: [],
    document_metadata: {
      mime_type: 'application/pdf',
      size_bytes: 1000,
      page_count: 1,
      uploaded_at: '2026-10-04T03:12:45.120Z',
    },
    extraction: null,
    classification: null,
    extracted_fields: {},
    ...overrides,
  };
}

export function completedDoc(
  id: string,
  filename: string,
  type: DocumentType = 'invoice_from_supplier',
  confidence = 0.91,
): DocumentResult {
  return makeDoc({
    document_id: id,
    filename,
    status: 'completed',
    extraction: {
      method: 'fast',
      duration_ms: 1200,
      ocr_mean_confidence: 88.5,
      raw_text: `TAX INVOICE ${filename}`,
      truncated_for_classification: false,
    },
    classification: {
      document_type: type,
      document_type_label: DOCUMENT_TYPE_LABELS[type],
      confidence,
      probabilities: probabilities(type, confidence),
      model: 'jev-1.13.0',
      duration_ms: 640,
    },
    extracted_fields: { document_number: 'INV-1', total_amount: '1,298.00' },
  });
}

export function failedDoc(id: string, filename: string): DocumentResult {
  return makeDoc({
    document_id: id,
    filename,
    status: 'failed',
    error_code: 'EMPTY_TEXT',
    error_message: `No readable text was found in ${filename}.`,
  });
}

export function makeBatch(overrides: Partial<Batch> = {}): Batch {
  return {
    batch_id: 'b_1',
    status: 'processing',
    extraction_method: 'fast',
    created_at: '2026-10-04T03:12:45.120Z',
    completed_at: null,
    expires_at: null,
    summary: null,
    documents: [],
    ...overrides,
  };
}

export function terminal(batch: Batch, status: Batch['status']): Batch {
  const docs = batch.documents;
  const completed = docs.filter((d) => d.status === 'completed');
  return {
    ...batch,
    status,
    completed_at: '2026-10-04T03:13:21.904Z',
    expires_at: '2026-10-04T03:28:21.904Z',
    summary: {
      total: docs.length,
      completed: completed.length,
      failed: docs.filter((d) => d.status === 'failed').length,
      cancelled: docs.filter((d) => d.status === 'cancelled').length,
      average_confidence: completed.length
        ? completed.reduce((s, d) => s + (d.classification?.confidence ?? 0), 0) / completed.length
        : null,
      total_duration_ms: 3000,
    },
  };
}

export const HEALTH_ALL: HealthResponse = {
  status: 'ok',
  tesseract: true,
  jev_configured: true,
  haiku_configured: true,
  version: '1.0.0',
};

export const HEALTH_NO_HAIKU: HealthResponse = { ...HEALTH_ALL, haiku_configured: false };

export function fileOf(name: string, size = 1024, type = 'application/pdf'): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}
