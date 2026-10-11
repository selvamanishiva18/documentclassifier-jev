import { downloadExport, type ExportFormat } from '../api/client';
import { copyText, toPrettyJson } from '../lib/clipboard';
import { MSG } from '../lib/messages';
import type { Batch } from '../types';

interface ExportBarProps {
  batch: Batch;
  onRetry: () => void;
  onNewBatch: () => void;
  onNotify: (message: string) => void;
  busy?: boolean;
}

const BTN =
  'rounded-md border px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700 disabled:cursor-not-allowed disabled:opacity-60';

export function ExportBar({ batch, onRetry, onNewBatch, onNotify, busy = false }: ExportBarProps) {
  const hasFailed = batch.documents.some((d) => d.status === 'failed');

  const copyBatch = async () => {
    if (await copyText(toPrettyJson(batch))) onNotify(MSG.copied);
  };

  const download = (format: ExportFormat) => {
    const filename = downloadExport(batch.batch_id, format);
    onNotify(MSG.downloading(filename));
  };

  return (
    <div
      role="group"
      aria-label="Export and batch actions"
      className="sticky top-0 z-10 flex flex-wrap gap-2 rounded-lg border bg-white p-3"
    >
      <button
        type="button"
        className={`${BTN} border-slate-400 bg-white hover:bg-slate-100`}
        onClick={() => void copyBatch()}
      >
        Copy batch JSON
      </button>
      <button
        type="button"
        className={`${BTN} border-slate-400 bg-white hover:bg-slate-100`}
        onClick={() => download('json')}
      >
        Download JSON
      </button>
      <button
        type="button"
        className={`${BTN} border-slate-400 bg-white hover:bg-slate-100`}
        onClick={() => download('csv')}
      >
        Download CSV
      </button>
      {hasFailed && (
        <button
          type="button"
          className={`${BTN} border-amber-700 bg-amber-50 text-amber-900 hover:bg-amber-100`}
          onClick={onRetry}
          disabled={busy}
        >
          Retry failed
        </button>
      )}
      <button
        type="button"
        className={`${BTN} ml-auto border-indigo-700 bg-indigo-700 text-white hover:bg-indigo-800`}
        onClick={onNewBatch}
        disabled={busy}
      >
        Start new batch
      </button>
    </div>
  );
}
