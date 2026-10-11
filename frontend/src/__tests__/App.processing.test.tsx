import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import * as client from '../api/client';
import type { Batch } from '../types';
import {
  completedDoc,
  failedDoc,
  fileOf,
  HEALTH_ALL,
  makeBatch,
  makeDoc,
  terminal,
} from '../test/fixtures';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getHealth: vi.fn(),
    createBatch: vi.fn(),
    getBatch: vi.fn(),
    cancelBatch: vi.fn(),
    retryBatch: vi.fn(),
    deleteBatch: vi.fn(),
    downloadExport: vi.fn((id: string, fmt: string) => `document-results-${id}.${fmt}`),
  };
});

const api = vi.mocked(client);
let server: Batch;

beforeEach(() => {
  vi.clearAllMocks();
  api.getHealth.mockResolvedValue(HEALTH_ALL);
  api.createBatch.mockResolvedValue({ batch_id: 'b_1', status: 'queued', documents: [] });
  api.getBatch.mockImplementation(async () => server);
  api.deleteBatch.mockResolvedValue(undefined);
});

async function startBatch(filenames: string[]) {
  const user = userEvent.setup();
  render(<App pollIntervalMs={10} />);
  fireEvent.drop(screen.getByTestId('dropzone'), {
    dataTransfer: { files: filenames.map((n) => fileOf(n)) },
  });
  await user.click(screen.getByRole('radio', { name: /^fast/i }));
  await user.click(screen.getByRole('button', { name: /^process/i }));
  return user;
}

const liveRegion = () => screen.getByTestId('live-region');

describe('Processing and results', () => {
  it('polls and updates the sticky progress header, current item, and live region', async () => {
    server = makeBatch({
      documents: [
        makeDoc({ document_id: 'd1', filename: 'a.pdf', status: 'extracting' }),
        makeDoc({ document_id: 'd2', filename: 'b.pdf', status: 'queued' }),
      ],
    });
    await startBatch(['a.pdf', 'b.pdf']);

    const header = await screen.findByTestId('progress-header');
    expect(header.className).toContain('sticky');
    expect(screen.getByTestId('current-item')).toHaveTextContent('Extracting a.pdf (1/2)…');
    expect(liveRegion()).toHaveTextContent('Processed 0 of 2 documents');

    server = makeBatch({
      documents: [
        completedDoc('d1', 'a.pdf'),
        makeDoc({ document_id: 'd2', filename: 'b.pdf', status: 'classifying' }),
      ],
    });
    await waitFor(() =>
      expect(screen.getByTestId('current-item')).toHaveTextContent('Classifying b.pdf (2/2)…'),
    );
    expect(liveRegion()).toHaveTextContent('Processed 1 of 2 documents');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');

    server = terminal(
      makeBatch({ documents: [completedDoc('d1', 'a.pdf'), completedDoc('d2', 'b.pdf')] }),
      'completed',
    );
    const summary = await screen.findByTestId('summary-strip');
    await waitFor(() => expect(summary).toHaveFocus());
    expect(summary).toHaveAttribute('tabindex', '-1');
    expect(summary).toHaveAttribute('role', 'region');
    expect(liveRegion()).toHaveTextContent('Processed 2 of 2 documents.');
    expect(within(summary).getByText(/This batch expires at \d{2}:\d{2}\./)).toBeInTheDocument();
    expect(screen.getAllByTestId('result-row')).toHaveLength(2);
  });

  it('cancel keeps completed results and enables export', async () => {
    server = makeBatch({
      documents: [
        makeDoc({ document_id: 'd1', filename: 'a.pdf', status: 'extracting' }),
        makeDoc({ document_id: 'd2', filename: 'b.pdf', status: 'queued' }),
        makeDoc({ document_id: 'd3', filename: 'c.pdf', status: 'queued' }),
      ],
    });
    const user = await startBatch(['a.pdf', 'b.pdf', 'c.pdf']);
    await screen.findByTestId('progress-header');

    api.cancelBatch.mockResolvedValue(server);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.cancelBatch).toHaveBeenCalledWith('b_1');
    expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled();

    server = terminal(
      makeBatch({
        documents: [
          completedDoc('d1', 'a.pdf', 'receipt', 0.97),
          makeDoc({ document_id: 'd2', filename: 'b.pdf', status: 'cancelled' }),
          makeDoc({ document_id: 'd3', filename: 'c.pdf', status: 'cancelled' }),
        ],
      }),
      'cancelled',
    );

    const summary = await screen.findByTestId('summary-strip');
    expect(summary).toHaveTextContent(
      'Batch cancelled. 1 document(s) were completed before cancelling.',
    );
    expect(liveRegion()).toHaveTextContent(
      'Batch cancelled. 1 document(s) were completed before cancelling.',
    );
    expect(screen.getByText('Receipt')).toBeInTheDocument();

    const downloadJson = screen.getByRole('button', { name: 'Download JSON' });
    expect(downloadJson).toBeEnabled();
    await user.click(downloadJson);
    expect(api.downloadExport).toHaveBeenCalledWith('b_1', 'json');
    expect(await screen.findByText('Downloading document-results-b_1.json…')).toBeInTheDocument();
  });

  it('retries failed documents and returns to processing', async () => {
    server = terminal(
      makeBatch({ documents: [completedDoc('d1', 'a.pdf'), failedDoc('d2', 'b.pdf')] }),
      'completed_with_errors',
    );
    const user = await startBatch(['a.pdf', 'b.pdf']);
    const summary = await screen.findByTestId('summary-strip');
    expect(summary).toHaveTextContent(
      'Processed 1 of 2 documents. 1 failed — you can retry them below.',
    );

    const retrying = makeBatch({
      documents: [
        completedDoc('d1', 'a.pdf'),
        makeDoc({ document_id: 'd2', filename: 'b.pdf', status: 'extracting' }),
      ],
    });
    api.retryBatch.mockResolvedValue(retrying);
    server = retrying;
    await user.click(screen.getByRole('button', { name: 'Retry failed' }));
    expect(api.retryBatch).toHaveBeenCalledWith('b_1');
    expect(await screen.findByTestId('current-item')).toHaveTextContent('Extracting b.pdf (2/2)…');
  });

  it('shows the all-failed message and error details', async () => {
    server = terminal(
      makeBatch({ documents: [failedDoc('d1', 'scan.jpg')] }),
      'completed_with_errors',
    );
    const user = await startBatch(['scan.jpg']);
    expect(await screen.findByTestId('summary-strip')).toHaveTextContent(
      'None of the documents could be processed. Check the files and try again.',
    );
    await user.click(screen.getByRole('button', { name: 'Show details for scan.jpg' }));
    expect(screen.getByText('No readable text was found in scan.jpg.')).toBeInTheDocument();
    expect(screen.getByTestId('error-code')).toHaveTextContent('EMPTY_TEXT');
  });

  it('Start new batch deletes the batch and resets to setup', async () => {
    server = terminal(makeBatch({ documents: [completedDoc('d1', 'a.pdf')] }), 'completed');
    const user = await startBatch(['a.pdf']);
    await screen.findByTestId('summary-strip');
    await user.click(screen.getByRole('button', { name: 'Start new batch' }));
    expect(api.deleteBatch).toHaveBeenCalledWith('b_1');
    expect(await screen.findByTestId('dropzone')).toBeInTheDocument();
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument();
  });

  it('shows the expiry message when the batch disappears while polling', async () => {
    server = makeBatch({
      documents: [makeDoc({ document_id: 'd1', filename: 'a.pdf', status: 'extracting' })],
    });
    await startBatch(['a.pdf']);
    await screen.findByTestId('progress-header');
    api.getBatch.mockRejectedValue(
      new client.ApiError(404, 'BATCH_NOT_FOUND', 'This batch has expired.'),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This batch has expired. Upload the files again to process them.',
    );
  });
});
