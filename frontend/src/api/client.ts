// Typed fetch wrappers for PRD Section 16.4.
import type { Batch, BatchCreated, ExtractionMethod, HealthResponse } from '../types';
import { MSG } from '../lib/messages';

const rawBase = import.meta.env.VITE_API_BASE_URL as string | undefined;
export const API_BASE = (rawBase && rawBase.trim() ? rawBase.trim() : '/api').replace(/\/$/, '');

export type ExportFormat = 'json' | 'csv';

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;

  constructor(status: number, errorCode: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
  }
}

interface ErrorBody {
  error_code?: unknown;
  error_message?: unknown;
  detail?: unknown;
}

function parseErrorBody(status: number, body: unknown): ApiError {
  let candidate: ErrorBody | null = null;
  if (body && typeof body === 'object') {
    const b = body as ErrorBody;
    candidate = b.detail && typeof b.detail === 'object' ? (b.detail as ErrorBody) : b;
  }
  const code =
    candidate && typeof candidate.error_code === 'string' ? candidate.error_code : 'INTERNAL_ERROR';
  const message =
    candidate && typeof candidate.error_message === 'string'
      ? candidate.error_message
      : MSG.genericError;
  return new ApiError(status, code, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, 'INTERNAL_ERROR', MSG.unreachable);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw parseErrorBody(res.status, body);
  }
  return body as T;
}

const batchPath = (batchId: string) => `/batches/${encodeURIComponent(batchId)}`;

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export function createBatch(files: File[], method: ExtractionMethod): Promise<BatchCreated> {
  const form = new FormData();
  form.append('extraction_method', method);
  for (const f of files) {
    form.append('files', f, f.name);
  }
  return request<BatchCreated>('/batches', { method: 'POST', body: form });
}

export function getBatch(batchId: string): Promise<Batch> {
  return request<Batch>(batchPath(batchId));
}

export function cancelBatch(batchId: string): Promise<Batch> {
  return request<Batch>(`${batchPath(batchId)}/cancel`, { method: 'POST' });
}

export function retryBatch(batchId: string): Promise<Batch> {
  return request<Batch>(`${batchPath(batchId)}/retry`, { method: 'POST' });
}

export function deleteBatch(batchId: string): Promise<void> {
  return request<void>(batchPath(batchId), { method: 'DELETE' });
}

export function exportFilename(batchId: string, format: ExportFormat): string {
  return `document-results-${batchId}.${format}`;
}

export function exportUrl(batchId: string, format: ExportFormat): string {
  return `${API_BASE}${batchPath(batchId)}/export.${format}`;
}

/** Triggers a browser download of the server-side export; returns the file name. */
export function downloadExport(batchId: string, format: ExportFormat): string {
  const filename = exportFilename(batchId, format);
  const a = document.createElement('a');
  a.href = exportUrl(batchId, format);
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  return filename;
}
