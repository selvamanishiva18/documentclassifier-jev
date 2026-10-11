import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as client from '../api/client';
import { ExportBar } from '../components/ExportBar';
import { completedDoc, failedDoc, makeBatch, terminal } from '../test/fixtures';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    downloadExport: vi.fn((id: string, fmt: string) => `document-results-${id}.${fmt}`),
  };
});

const api = vi.mocked(client);

const batch = terminal(
  makeBatch({ documents: [completedDoc('d1', 'a.pdf'), failedDoc('d2', 'b.pdf')] }),
  'completed_with_errors',
);

beforeEach(() => vi.clearAllMocks());

describe('ExportBar', () => {
  it('copies the whole batch JSON, pretty-printed', async () => {
    const user = userEvent.setup();
    const onNotify = vi.fn();
    render(<ExportBar batch={batch} onRetry={vi.fn()} onNewBatch={vi.fn()} onNotify={onNotify} />);
    await user.click(screen.getByRole('button', { name: 'Copy batch JSON' }));
    expect(await navigator.clipboard.readText()).toBe(JSON.stringify(batch, null, 2));
    expect(onNotify).toHaveBeenCalledWith('JSON copied.');
  });

  it('triggers JSON and CSV downloads', async () => {
    const user = userEvent.setup();
    const onNotify = vi.fn();
    render(<ExportBar batch={batch} onRetry={vi.fn()} onNewBatch={vi.fn()} onNotify={onNotify} />);
    await user.click(screen.getByRole('button', { name: 'Download JSON' }));
    expect(api.downloadExport).toHaveBeenCalledWith('b_1', 'json');
    expect(onNotify).toHaveBeenCalledWith('Downloading document-results-b_1.json…');
    await user.click(screen.getByRole('button', { name: 'Download CSV' }));
    expect(api.downloadExport).toHaveBeenCalledWith('b_1', 'csv');
    expect(onNotify).toHaveBeenCalledWith('Downloading document-results-b_1.csv…');
  });

  it('shows Retry failed only when there are failed documents', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(
      <ExportBar batch={batch} onRetry={onRetry} onNewBatch={vi.fn()} onNotify={vi.fn()} />,
    );
    await user.click(screen.getByRole('button', { name: 'Retry failed' }));
    expect(onRetry).toHaveBeenCalled();

    const ok = terminal(makeBatch({ documents: [completedDoc('d1', 'a.pdf')] }), 'completed');
    rerender(<ExportBar batch={ok} onRetry={onRetry} onNewBatch={vi.fn()} onNotify={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Retry failed' })).not.toBeInTheDocument();
  });

  it('starts a new batch', async () => {
    const user = userEvent.setup();
    const onNewBatch = vi.fn();
    render(
      <ExportBar batch={batch} onRetry={vi.fn()} onNewBatch={onNewBatch} onNotify={vi.fn()} />,
    );
    await user.click(screen.getByRole('button', { name: 'Start new batch' }));
    expect(onNewBatch).toHaveBeenCalled();
  });
});
