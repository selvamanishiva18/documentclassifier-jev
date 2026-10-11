import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultDetail } from '../components/ResultDetail';
import { completedDoc } from '../test/fixtures';

function docWithProbs() {
  const doc = completedDoc('d1', 'inv.pdf', 'invoice_from_supplier', 0.91);
  doc.classification!.probabilities = {
    purchase_order: 0.02,
    transport_request: 0,
    sales_order: 0.03,
    invoice_from_supplier: 0.91,
    credit_note: 0,
    receipt: 0.01,
    bill: 0.03,
    packing_slip: 0,
    quotation: 0,
    quote_request: 0,
    none_of_the_above: 0,
  };
  doc.warnings = ['pdf_truncated_to_20_pages'];
  return doc;
}

describe('ResultDetail', () => {
  it('renders probability bars sorted descending with the chosen type highlighted', () => {
    render(<ResultDetail doc={docWithProbs()} onNotify={vi.fn()} />);
    const rows = screen.getAllByTestId('prob-row');
    expect(rows).toHaveLength(11);
    const values = rows.map((r) => Number(r.textContent?.match(/([\d.]+)%/)?.[1]));
    expect(values).toEqual([...values].sort((a, b) => b - a));
    expect(rows[0]).toHaveAttribute('data-key', 'invoice_from_supplier');
    const chosen = rows.filter((r) => r.getAttribute('data-chosen') === 'true');
    expect(chosen).toHaveLength(1);
    expect(chosen[0]).toHaveAttribute('aria-current', 'true');
    expect(chosen[0]).toHaveTextContent('(chosen)');
    expect(screen.getByText(/Model: jev-1\.13\.0/)).toBeInTheDocument();
  });

  it('renders the fields table, raw text and warnings', () => {
    render(<ResultDetail doc={docWithProbs()} onNotify={vi.fn()} />);
    expect(screen.getByRole('rowheader', { name: 'Document number' })).toBeInTheDocument();
    expect(screen.getByText('INV-1')).toBeInTheDocument();
    expect(screen.getByLabelText('Raw extracted text for inv.pdf')).toHaveTextContent(
      'TAX INVOICE inv.pdf',
    );
    expect(screen.getByText('pdf_truncated_to_20_pages')).toBeInTheDocument();
  });

  it('copies the document JSON (not the batch) to the clipboard', async () => {
    const user = userEvent.setup();
    const onNotify = vi.fn();
    const doc = docWithProbs();
    render(<ResultDetail doc={doc} onNotify={onNotify} />);
    await user.click(screen.getByRole('button', { name: 'Copy document JSON' }));
    expect(await navigator.clipboard.readText()).toBe(JSON.stringify(doc, null, 2));
    expect(onNotify).toHaveBeenCalledWith('JSON copied.');
  });

  it('supports arrow-key navigation between tabs', async () => {
    const user = userEvent.setup();
    render(<ResultDetail doc={docWithProbs()} onNotify={vi.fn()} />);
    const fieldsTab = screen.getByRole('tab', { name: 'Fields' });
    expect(fieldsTab).toHaveAttribute('aria-selected', 'true');
    fieldsTab.focus();
    await user.keyboard('{ArrowRight}');
    const probTab = screen.getByRole('tab', { name: 'Probabilities' });
    expect(probTab).toHaveFocus();
    expect(probTab).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'JSON' })).toHaveFocus();
  });
});
