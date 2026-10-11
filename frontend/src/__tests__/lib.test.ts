import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  createBatch,
  deleteBatch,
  downloadExport,
  exportUrl,
  getBatch,
} from '../api/client';
import { confidenceLevel, formatTime } from '../lib/format';
import { finalSummaryMessage } from '../lib/messages';
import { validateFile } from '../lib/validation';
import { completedDoc, failedDoc, fileOf, makeBatch, makeDoc } from '../test/fixtures';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('validateFile', () => {
  it('accepts jpg, jpeg and pdf case-insensitively', () => {
    expect(validateFile(fileOf('a.JPG'))).toBeNull();
    expect(validateFile(fileOf('a.jpeg'))).toBeNull();
    expect(validateFile(fileOf('a.Pdf'))).toBeNull();
  });
  it('rejects other extensions', () => {
    expect(validateFile(fileOf('a.png'))).toBe('Only JPG, JPEG, and PDF files are supported.');
  });
  it('rejects files over 10 MB but accepts exactly 10 MB', () => {
    expect(validateFile(fileOf('a.pdf', 10 * 1024 * 1024))).toBeNull();
    expect(validateFile(fileOf('a.pdf', 10 * 1024 * 1024 + 1))).toBe(
      'a.pdf is larger than 10 MB and was skipped.',
    );
  });
});

describe('confidenceLevel', () => {
  it('uses the 0.60 / 0.85 boundaries', () => {
    expect(confidenceLevel(0.85)).toBe('high');
    expect(confidenceLevel(0.849)).toBe('medium');
    expect(confidenceLevel(0.6)).toBe('medium');
    expect(confidenceLevel(0.599)).toBe('low');
  });
});

describe('formatTime', () => {
  it('formats HH:MM', () => {
    expect(formatTime('2026-10-04T03:28:21.904Z')).toMatch(/^\d{2}:\d{2}$/);
  });
});

describe('finalSummaryMessage', () => {
  it('covers all four outcomes', () => {
    const two = [completedDoc('d1', 'a.pdf'), completedDoc('d2', 'b.pdf')];
    expect(finalSummaryMessage(makeBatch({ status: 'completed', documents: two }))).toBe(
      'Processed 2 of 2 documents.',
    );
    expect(
      finalSummaryMessage(
        makeBatch({
          status: 'completed_with_errors',
          documents: [completedDoc('d1', 'a.pdf'), failedDoc('d2', 'b.pdf')],
        }),
      ),
    ).toBe('Processed 1 of 2 documents. 1 failed — you can retry them below.');
    expect(
      finalSummaryMessage(
        makeBatch({ status: 'completed_with_errors', documents: [failedDoc('d1', 'a.pdf')] }),
      ),
    ).toBe('None of the documents could be processed. Check the files and try again.');
    expect(
      finalSummaryMessage(
        makeBatch({
          status: 'cancelled',
          documents: [completedDoc('d1', 'a.pdf'), makeDoc({ status: 'cancelled' })],
        }),
      ),
    ).toBe('Batch cancelled. 1 document(s) were completed before cancelling.');
  });
});

describe('api client', () => {
  it('posts files and the method as multipart form data', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ batch_id: 'b_1', status: 'queued', documents: [] }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const res = await createBatch([fileOf('a.pdf'), fileOf('b.jpg')], 'precise');
    expect(res.batch_id).toBe('b_1');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/batches');
    expect(init.method).toBe('POST');
    const form = init.body as FormData;
    expect(form.get('extraction_method')).toBe('precise');
    expect(form.getAll('files')).toHaveLength(2);
  });

  it('maps error bodies to ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error_code: 'BATCH_NOT_FOUND',
            error_message: 'This batch has expired. Upload the files again to process them.',
          }),
          { status: 404 },
        ),
      ),
    );
    const err = await getBatch('b_x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).errorCode).toBe('BATCH_NOT_FOUND');
  });

  it('maps network failures to a friendly ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fail')));
    const err = await getBatch('b_x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
  });

  it('handles 204 on delete', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(deleteBatch('b_1')).resolves.toBeUndefined();
  });

  it('downloads exports through an anchor with the PRD file name', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    expect(exportUrl('b_1', 'csv')).toBe('/api/batches/b_1/export.csv');
    expect(downloadExport('b_1', 'csv')).toBe('document-results-b_1.csv');
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });
});
