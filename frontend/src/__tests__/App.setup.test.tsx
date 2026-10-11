import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import * as client from '../api/client';
import { fileOf, HEALTH_ALL, HEALTH_NO_HAIKU } from '../test/fixtures';

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
    downloadExport: vi.fn(),
  };
});

const api = vi.mocked(client);

function drop(files: File[]) {
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files } });
}

const processButton = () => screen.getByRole('button', { name: /^process/i });

beforeEach(() => {
  vi.clearAllMocks();
  api.getHealth.mockResolvedValue(HEALTH_ALL);
});

describe('Setup state', () => {
  it('rejects unsupported types and oversize files with messages, keeping valid ones', async () => {
    render(<App />);
    drop([
      fileOf('photo.png', 100, 'image/png'),
      fileOf('big.pdf', 11 * 1024 * 1024),
      fileOf('ok.jpg', 2048, 'image/jpeg'),
    ]);
    expect(screen.getByText('Only JPG, JPEG, and PDF files are supported.')).toBeInTheDocument();
    expect(screen.getByText('big.pdf is larger than 10 MB and was skipped.')).toBeInTheDocument();
    expect(
      screen.getByText(/1 file\(s\) ready\. Choose an extraction method\./),
    ).toBeInTheDocument();
    expect(processButton()).toHaveTextContent('Process 1 file');
  });

  it('accepts files picked through the file input', async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<App />);
    await user.upload(screen.getByLabelText(/drag and drop files here/i), [
      fileOf('a.pdf'),
      fileOf('b.jpeg', 10, 'image/jpeg'),
    ]);
    expect(screen.getByText(/2 file\(s\) ready/)).toBeInTheDocument();
  });

  it('lets the user remove a file before processing', async () => {
    const user = userEvent.setup();
    render(<App />);
    drop([fileOf('a.pdf'), fileOf('b.pdf')]);
    await user.click(screen.getByRole('button', { name: 'Remove a.pdf' }));
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument();
    expect(screen.getByText(/1 file\(s\) ready/)).toBeInTheDocument();
  });

  it('keeps Process disabled until a valid file and a method are chosen', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId('health-badge');
    expect(processButton()).toBeDisabled();
    expect(screen.getByText('Add at least one file to continue.')).toBeInTheDocument();

    drop([fileOf('bad.txt', 10, 'text/plain')]);
    expect(processButton()).toBeDisabled();

    drop([fileOf('a.pdf')]);
    expect(processButton()).toBeDisabled();
    expect(screen.getByText('Select an extraction method to continue.')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: /^fast/i }));
    expect(processButton()).toBeEnabled();
  });

  it('rejects a batch of more than 20 files at submission without uploading', async () => {
    const user = userEvent.setup();
    render(<App />);
    drop(Array.from({ length: 21 }, (_, i) => fileOf(`f${i}.pdf`)));
    await user.click(screen.getByRole('radio', { name: /^fast/i }));
    await user.click(processButton());
    expect(screen.getByText('You can process up to 20 files per batch.')).toBeInTheDocument();
    expect(api.createBatch).not.toHaveBeenCalled();
  });

  it('disables Precise with the exact reason when Haiku is not configured', async () => {
    api.getHealth.mockResolvedValue(HEALTH_NO_HAIKU);
    render(<App />);
    const reason = await screen.findByText(
      'Not configured: ANTHROPIC_API_KEY is not set on this server',
    );
    const precise = screen.getByRole('radio', { name: /^precise/i });
    expect(precise).toBeDisabled();
    expect(precise.getAttribute('aria-describedby')).toContain(reason.id);
    expect(screen.getByRole('radio', { name: /^fast/i })).toBeEnabled();
  });

  it('enables Precise when Haiku is configured', async () => {
    render(<App />);
    await screen.findByTestId('health-badge');
    expect(screen.getByRole('radio', { name: /^precise/i })).toBeEnabled();
    expect(
      screen.queryByText('Not configured: ANTHROPIC_API_KEY is not set on this server'),
    ).not.toBeInTheDocument();
  });

  it('shows the method copy from the PRD', async () => {
    render(<App />);
    expect(
      screen.getByText('Python OCR (Tesseract) — free, ~1–3 s per page, best for clean scans'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Claude Haiku 4.5 — paid API, ~3–8 s per page, better on low-quality or complex layouts',
      ),
    ).toBeInTheDocument();
  });

  it('shows a server error returned on submission', async () => {
    const user = userEvent.setup();
    api.createBatch.mockRejectedValue(
      new client.ApiError(429, 'SERVER_BUSY', 'The server is busy. Try again in a moment.'),
    );
    render(<App />);
    drop([fileOf('a.pdf')]);
    await user.click(screen.getByRole('radio', { name: /^fast/i }));
    await user.click(processButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The server is busy. Try again in a moment.',
    );
  });

  it('is fully keyboard operable: dropzone, remove, method, process', async () => {
    const user = userEvent.setup();
    api.getHealth.mockResolvedValue(HEALTH_NO_HAIKU);
    api.createBatch.mockReturnValue(new Promise(() => {}));
    render(<App />);
    await screen.findByTestId('health-badge');
    drop([fileOf('a.pdf')]);

    await user.tab();
    expect(screen.getByLabelText(/drag and drop files here/i)).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Remove a.pdf' })).toHaveFocus();
    await user.tab();
    const fast = screen.getByRole('radio', { name: /^fast/i });
    expect(fast).toHaveFocus();
    await user.keyboard(' ');
    expect(fast).toBeChecked();
    await user.tab();
    expect(processButton()).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(api.createBatch).toHaveBeenCalledWith([expect.any(File)], 'fast');
  });
});
