// Mirrors PRD Section 16.5 (authoritative schemas).

export type ExtractionMethod = 'fast' | 'precise';

export type BatchStatus =
  'queued' | 'processing' | 'completed' | 'completed_with_errors' | 'cancelled';

export type DocumentStatus =
  'queued' | 'extracting' | 'classifying' | 'completed' | 'failed' | 'cancelled';

export type DocumentType =
  | 'purchase_order'
  | 'transport_request'
  | 'sales_order'
  | 'invoice_from_supplier'
  | 'credit_note'
  | 'receipt'
  | 'bill'
  | 'packing_slip'
  | 'quotation'
  | 'quote_request'
  | 'none_of_the_above';

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  purchase_order: 'Purchase Order',
  transport_request: 'Transport Request',
  sales_order: 'Sales Order',
  invoice_from_supplier: 'Invoice from Supplier',
  credit_note: 'Credit Note',
  receipt: 'Receipt',
  bill: 'Bill',
  packing_slip: 'Packing Slip',
  quotation: 'Quotation',
  quote_request: 'Quote Request',
  none_of_the_above: 'None of the above',
};

export const CANONICAL_FIELDS = [
  'document_number',
  'document_date',
  'due_date',
  'issuer_name',
  'recipient_name',
  'reference_number',
  'subtotal',
  'tax_amount',
  'total_amount',
  'currency',
  'payment_terms',
  'line_items_summary',
] as const;

export type CanonicalField = (typeof CANONICAL_FIELDS)[number];

export type ErrorCode =
  | 'INVALID_FILE_TYPE'
  | 'FILE_TOO_LARGE'
  | 'TOO_MANY_FILES'
  | 'UPLOAD_TOO_LARGE'
  | 'NO_FILES'
  | 'INVALID_METHOD'
  | 'PRECISE_NOT_CONFIGURED'
  | 'SERVER_BUSY'
  | 'CORRUPT_FILE'
  | 'EMPTY_TEXT'
  | 'OCR_FAILED'
  | 'HAIKU_UNAVAILABLE'
  | 'HAIKU_AUTH_ERROR'
  | 'HAIKU_BAD_OUTPUT'
  | 'JEV_UNAVAILABLE'
  | 'JEV_AUTH_ERROR'
  | 'JEV_BAD_REQUEST'
  | 'JEV_INVALID_RESPONSE'
  | 'BATCH_NOT_FOUND'
  | 'BATCH_EXPIRED'
  | 'BATCH_STATE_CONFLICT'
  | 'INTERNAL_ERROR';

export interface DocumentMetadata {
  mime_type: 'image/jpeg' | 'application/pdf' | string;
  size_bytes: number;
  page_count: number;
  uploaded_at: string;
}

export interface Extraction {
  method: ExtractionMethod;
  duration_ms: number;
  ocr_mean_confidence: number | null;
  raw_text: string;
  truncated_for_classification: boolean;
}

export interface Classification {
  document_type: DocumentType;
  document_type_label: string;
  confidence: number;
  probabilities: Record<DocumentType, number>;
  model: string;
  duration_ms: number;
}

export type ExtractedFields = Partial<Record<CanonicalField, string>>;

export interface DocumentResult {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  error_code: ErrorCode | null;
  error_message: string | null;
  warnings: string[];
  document_metadata: DocumentMetadata;
  extraction: Extraction | null;
  classification: Classification | null;
  extracted_fields: ExtractedFields;
}

export interface BatchSummary {
  total: number;
  completed: number;
  failed: number;
  cancelled: number;
  average_confidence: number | null;
  total_duration_ms: number;
}

export interface Batch {
  batch_id: string;
  status: BatchStatus;
  extraction_method: ExtractionMethod;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  summary: BatchSummary | null;
  documents: DocumentResult[];
}

export interface BatchCreated {
  batch_id: string;
  status: BatchStatus;
  documents: {
    document_id: string;
    filename: string;
    status: DocumentStatus;
    error_code?: ErrorCode | null;
  }[];
}

export interface HealthResponse {
  status: string;
  tesseract: boolean;
  jev_configured: boolean;
  haiku_configured: boolean;
  version?: string;
}

export const TERMINAL_BATCH_STATUSES: readonly BatchStatus[] = [
  'completed',
  'completed_with_errors',
  'cancelled',
];

export function isTerminalBatch(status: BatchStatus): boolean {
  return TERMINAL_BATCH_STATUSES.includes(status);
}
