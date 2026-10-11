// User-facing copy from PRD Sections 6 and 16.8/16.9.
import type { Batch } from '../types';

export const MSG = {
  unsupportedType: 'Only JPG, JPEG, and PDF files are supported.',
  oversize: (filename: string) => `${filename} is larger than 10 MB and was skipped.`,
  tooManyFiles: 'You can process up to 20 files per batch.',
  emptyBatch: 'Add at least one file to continue.',
  ready: (n: number) => `${n} file(s) ready. Choose an extraction method.`,
  noMethod: 'Select an extraction method to continue.',
  preciseNotConfigured: 'Not configured: ANTHROPIC_API_KEY is not set on this server',
  copied: 'JSON copied.',
  downloading: (filename: string) => `Downloading ${filename}…`,
  expired: 'This batch has expired. Upload the files again to process them.',
  progress: (n: number, total: number) => `Processed ${n} of ${total} documents`,
  unreachable: 'Could not reach the server. Check your connection and try again.',
  genericError: 'Something went wrong. Try again.',
} as const;

export const METHOD_COPY = {
  fast: {
    title: 'Fast',
    description: 'Python OCR (Tesseract) — free, ~1–3 s per page, best for clean scans',
  },
  precise: {
    title: 'Precise',
    description:
      'Claude Haiku 4.5 — paid API, ~3–8 s per page, better on low-quality or complex layouts',
  },
} as const;

export function countDocs(batch: Batch) {
  let completed = 0;
  let failed = 0;
  let cancelled = 0;
  for (const d of batch.documents) {
    if (d.status === 'completed') completed += 1;
    else if (d.status === 'failed') failed += 1;
    else if (d.status === 'cancelled') cancelled += 1;
  }
  return { total: batch.documents.length, completed, failed, cancelled };
}

/** Final summary sentence for a terminal batch (PRD 6.5 messages). */
export function finalSummaryMessage(batch: Batch): string {
  const { total, completed, failed } = countDocs(batch);
  if (batch.status === 'cancelled') {
    return `Batch cancelled. ${completed} document(s) were completed before cancelling.`;
  }
  if (completed === 0 && failed > 0) {
    return 'None of the documents could be processed. Check the files and try again.';
  }
  if (failed === 0) {
    return `Processed ${total} of ${total} documents.`;
  }
  return `Processed ${completed} of ${total} documents. ${failed} failed — you can retry them below.`;
}
