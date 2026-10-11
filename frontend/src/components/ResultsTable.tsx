import { Fragment, useMemo, useState } from 'react';
import type { DocumentResult } from '../types';
import { ConfidencePill } from './ConfidencePill';
import { ResultDetail } from './ResultDetail';
import { StatusBadge } from './StatusBadge';

type SortKey = 'upload' | 'filename' | 'type' | 'confidence' | 'status';
type SortDir = 'asc' | 'desc';

interface ResultsTableProps {
  documents: DocumentResult[];
  onNotify: (message: string) => void;
}

const COLUMNS: { key: Exclude<SortKey, 'upload'>; label: string }[] = [
  { key: 'filename', label: 'File' },
  { key: 'type', label: 'Type' },
  { key: 'confidence', label: 'Confidence' },
  { key: 'status', label: 'Status' },
];

function compare(a: DocumentResult, b: DocumentResult, key: SortKey): number {
  switch (key) {
    case 'filename':
      return a.filename.localeCompare(b.filename);
    case 'type':
      return (a.classification?.document_type_label ?? '').localeCompare(
        b.classification?.document_type_label ?? '',
      );
    case 'confidence':
      return (a.classification?.confidence ?? -1) - (b.classification?.confidence ?? -1);
    case 'status':
      return a.status.localeCompare(b.status);
    default:
      return 0;
  }
}

export function ResultsTable({ documents, onNotify }: ResultsTableProps) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'upload', dir: 'asc' });
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  // Client-side only; default is upload order.
  const rows = useMemo(() => {
    if (sort.key === 'upload') return documents;
    const factor = sort.dir === 'asc' ? 1 : -1;
    return documents
      .map((d, i) => [d, i] as const)
      .sort(([a, ia], [b, ib]) => compare(a, b, sort.key) * factor || ia - ib)
      .map(([d]) => d);
  }, [documents, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    );

  const toggleRow = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="overflow-x-auto rounded-lg border bg-white">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Classification results</caption>
        <thead className="border-b bg-slate-100">
          <tr>
            {COLUMNS.map((c) => {
              const activeSort = sort.key === c.key;
              const ariaSort = activeSort
                ? sort.dir === 'asc'
                  ? 'ascending'
                  : 'descending'
                : 'none';
              return (
                <th key={c.key} scope="col" aria-sort={ariaSort} className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => toggleSort(c.key)}
                    className="flex items-center gap-1 font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
                  >
                    {c.label}
                    <span aria-hidden="true">
                      {activeSort ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
                    </span>
                  </button>
                </th>
              );
            })}
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Details</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const isOpen = expanded.has(d.document_id);
            const detailId = `detail-${d.document_id}`;
            return (
              <Fragment key={d.document_id}>
                <tr data-testid="result-row" className="border-b border-slate-200">
                  <td className="max-w-[16rem] truncate px-3 py-2 font-medium" title={d.filename}>
                    {d.filename}
                  </td>
                  <td className="px-3 py-2">{d.classification?.document_type_label ?? '—'}</td>
                  <td className="px-3 py-2">
                    <ConfidencePill value={d.classification?.confidence} />
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => toggleRow(d.document_id)}
                      aria-expanded={isOpen}
                      aria-controls={detailId}
                      aria-label={`${isOpen ? 'Hide' : 'Show'} details for ${d.filename}`}
                      className="rounded px-2 py-1 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
                    >
                      <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr id={detailId}>
                    <td colSpan={5} className="p-0">
                      <ResultDetail doc={d} onNotify={onNotify} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
