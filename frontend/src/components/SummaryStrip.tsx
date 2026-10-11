import { useEffect, useRef } from 'react';
import { formatDuration, formatPercent, formatTime } from '../lib/format';
import { countDocs, finalSummaryMessage } from '../lib/messages';
import type { Batch } from '../types';

export function SummaryStrip({ batch }: { batch: Batch }) {
  const ref = useRef<HTMLElement>(null);

  // Focus moves here when the batch reaches a terminal state (PRD 3.0).
  useEffect(() => {
    ref.current?.focus();
  }, []);

  const counts = countDocs(batch);
  const s = batch.summary;
  const items: [string, string][] = [
    ['Total', String(s?.total ?? counts.total)],
    ['Completed', String(s?.completed ?? counts.completed)],
    ['Failed', String(s?.failed ?? counts.failed)],
    ['Cancelled', String(s?.cancelled ?? counts.cancelled)],
    [
      'Avg confidence',
      s?.average_confidence !== null && s?.average_confidence !== undefined
        ? formatPercent(s.average_confidence)
        : '—',
    ],
    ['Total time', s ? formatDuration(s.total_duration_ms) : '—'],
  ];

  return (
    <section
      ref={ref}
      tabIndex={-1}
      role="region"
      aria-label="Batch summary"
      data-testid="summary-strip"
      className="space-y-3 rounded-lg border bg-white p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
    >
      <p className="font-semibold">{finalSummaryMessage(batch)}</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
        {items.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs uppercase tracking-wide text-slate-700">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {batch.expires_at && (
        <p className="text-sm text-slate-700">
          This batch expires at {formatTime(batch.expires_at)}.
        </p>
      )}
    </section>
  );
}
