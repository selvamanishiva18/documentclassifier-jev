import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfidencePill } from '../components/ConfidencePill';
import { ResultsTable } from '../components/ResultsTable';
import { completedDoc, failedDoc } from '../test/fixtures';

const docs = [
  completedDoc('d1', 'mid.pdf', 'quotation', 0.7),
  completedDoc('d2', 'high.pdf', 'receipt', 0.95),
  failedDoc('d3', 'failed.jpg'),
  completedDoc('d4', 'low.pdf', 'bill', 0.5),
];

const rowNames = () =>
  screen.getAllByTestId('result-row').map((r) => within(r).getAllByRole('cell')[0].textContent);

describe('ResultsTable', () => {
  it('defaults to upload order', () => {
    render(<ResultsTable documents={docs} onNotify={vi.fn()} />);
    expect(rowNames()).toEqual(['mid.pdf', 'high.pdf', 'failed.jpg', 'low.pdf']);
  });

  it('sorts by confidence ascending then descending', async () => {
    const user = userEvent.setup();
    render(<ResultsTable documents={docs} onNotify={vi.fn()} />);
    const header = screen.getByRole('button', { name: /confidence/i });

    await user.click(header);
    expect(rowNames()).toEqual(['failed.jpg', 'low.pdf', 'mid.pdf', 'high.pdf']);
    expect(screen.getByRole('columnheader', { name: /confidence/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );

    await user.click(header);
    expect(rowNames()).toEqual(['high.pdf', 'mid.pdf', 'low.pdf', 'failed.jpg']);
    expect(screen.getByRole('columnheader', { name: /confidence/i })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
  });

  it('sorts by filename, type and status', async () => {
    const user = userEvent.setup();
    render(<ResultsTable documents={docs} onNotify={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /^file/i }));
    expect(rowNames()).toEqual(['failed.jpg', 'high.pdf', 'low.pdf', 'mid.pdf']);
    await user.click(screen.getByRole('button', { name: /^type/i }));
    expect(rowNames()).toEqual(['failed.jpg', 'low.pdf', 'mid.pdf', 'high.pdf']);
    await user.click(screen.getByRole('button', { name: /^status/i }));
    expect(rowNames()[3]).toBe('failed.jpg');
  });

  it('expands a row to show its detail', async () => {
    const user = userEvent.setup();
    render(<ResultsTable documents={docs} onNotify={vi.fn()} />);
    const toggle = screen.getByRole('button', { name: 'Show details for high.pdf' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Hide details for high.pdf' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Copy document JSON' })).toBeInTheDocument();
  });
});

describe('ConfidencePill', () => {
  it.each([
    [0.85, 'high', 'bg-green-100'],
    [0.95, 'high', 'bg-green-100'],
    [0.8499, 'medium', 'bg-amber-100'],
    [0.6, 'medium', 'bg-amber-100'],
    [0.5999, 'low', 'bg-red-100'],
    [0.1, 'low', 'bg-red-100'],
  ])('confidence %s is %s', (value, level, cls) => {
    render(<ConfidencePill value={value} />);
    const pill = screen.getByTestId('confidence-pill');
    expect(pill).toHaveAttribute('data-level', level);
    expect(pill.className).toContain(cls);
  });

  it('renders as a percentage', () => {
    render(<ConfidencePill value={0.91} />);
    expect(screen.getByTestId('confidence-pill')).toHaveTextContent('91.0%');
  });

  it('renders a dash when there is no confidence', () => {
    render(<ConfidencePill value={null} />);
    expect(screen.queryByTestId('confidence-pill')).not.toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
