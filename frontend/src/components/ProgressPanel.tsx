import { useEffect, useRef, useState } from 'react';
import { formatDuration } from '../lib/format';
import { countDocs } from '../lib/messages';
import type { Batch, DocumentResult } from '../types';
import { StatusBadge } from './StatusBadge';

interface ProgressPanelProps {
  batch: Batch;
  onCancel: () => void;
  cancelling: boolean;
}

const isActive = (d: DocumentResult) => d.status === 'extracting' || d.status === 'classifying';

function serverDuration(d: DocumentResult): number | null {
  const ms = (d.extraction?.duration_ms ?? 0) + (d.classification?.duration_ms ?? 0);
  return d.extraction || d.classification ? ms : null;
}

export function ProgressPanel({ batch, onCancel, cancelling }: ProgressPanelProps) {
  const docs = batch.documents;
  const { total, completed, failed } = countDocs(batch);
  const done = completed + failed;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const activeIdx = docs.findIndex(isActive);
  const active = activeIdx >= 0 ? docs[activeIdx] : null;

  // Client-side elapsed time for the document currently in flight.
  const startedAt = useRef(new Map<string, number>());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    for (const d of docs) {
      if (isActive(d) && !startedAt.current.has(d.document_id)) {
        startedAt.current.set(d.document_id, Date.now());
      }
    }
  }, [docs]);
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);

  let currentLine: string;
  if (active) {
    const verb = active.status === 'extracting' ? 'Extracting' : 'Classifying';
    currentLine = `${verb} ${active.filename} (${activeIdx + 1}/${total})…`;
  } else if (batch.status === 'queued') {
    currentLine = 'Waiting to start…';
  } else {
    currentLine = 'Finishing up…';
  }

  const canCancel = !cancelling && (batch.status === 'processing' || batch.status === 'queued');

  return (
    <section aria-labelledby="progress-heading" className="rounded-lg border bg-white">
      <div
        data-testid="progress-header"
        className="sticky top-0 z-10 space-y-3 rounded-t-lg border-b bg-white p-4"
      >
        <h2 id="progress-heading" className="sr-only">
          Processing progress
        </h2>
        <div
          role="progressbar"
          aria-label="Batch progress"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={done}
          aria-valuetext={`${done} of ${total} documents processed`}
          className="h-3 w-full overflow-hidden rounded-full bg-slate-200"
        >
          <div className="h-full bg-indigo-700 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p data-testid="current-item" className="truncate text-xl font-semibold">
              {currentLine}
            </p>
            <p className="text-sm text-slate-700">
              {done} of {total} done
              {cancelling && ' · Cancelling after the current document…'}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={!canCancel}
            className="rounded-md border border-slate-400 px-4 py-2 font-medium hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        </div>
      </div>
      <ul aria-label="Documents" className="divide-y divide-slate-200">
        {docs.map((d) => {
          const started = startedAt.current.get(d.document_id);
          const server = serverDuration(d);
          let elapsed: string = '';
          if (isActive(d) && started !== undefined) elapsed = formatDuration(now - started);
          else if (server !== null) elapsed = formatDuration(server);
          return (
            <li
              key={d.document_id}
              data-testid="progress-row"
              className="flex items-center gap-3 px-4 py-2 text-sm"
            >
              <span className="min-w-0 flex-1 truncate" title={d.filename}>
                {d.filename}
              </span>
              <StatusBadge status={d.status} />
              <span className="w-16 text-right tabular-nums text-slate-700">{elapsed}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
