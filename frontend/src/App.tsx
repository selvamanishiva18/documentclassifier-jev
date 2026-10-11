import { useCallback, useEffect, useRef, useState } from 'react';
import { Dropzone } from './components/Dropzone';
import { ExportBar } from './components/ExportBar';
import { FileList, type FileEntry } from './components/FileList';
import { MethodSelector } from './components/MethodSelector';
import { ProgressPanel } from './components/ProgressPanel';
import { ResultsTable } from './components/ResultsTable';
import { SummaryStrip } from './components/SummaryStrip';
import { Toast, type ToastMessage } from './components/Toast';
import { useBatch } from './hooks/useBatch';
import { useHealth } from './hooks/useHealth';
import { formatBytes } from './lib/format';
import { MAX_FILES_PER_BATCH, POLL_INTERVAL_MS } from './lib/limits';
import { countDocs, finalSummaryMessage, MSG } from './lib/messages';
import { validateFile } from './lib/validation';
import type { ExtractionMethod, HealthResponse } from './types';

let entrySeq = 0;
const nextEntryId = () => `f_${++entrySeq}`;

function HealthBadge({ health, failed }: { health: HealthResponse | null; failed: boolean }) {
  if (!health) {
    return (
      <span className="text-sm text-slate-700">
        {failed ? 'Server unreachable' : 'Checking server…'}
      </span>
    );
  }
  const item = (label: string, ok: boolean) => (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
        ok ? 'bg-green-100 text-green-900' : 'bg-red-100 text-red-900'
      }`}
      aria-label={`${label} mode ${ok ? 'available' : 'unavailable'}`}
    >
      {label} {ok ? '✓' : '✗'}
    </span>
  );
  return (
    <span className="flex gap-2" data-testid="health-badge">
      {item('Fast', health.tesseract)}
      {item('Precise', health.haiku_configured)}
    </span>
  );
}

interface AppProps {
  pollIntervalMs?: number;
}

export default function App({ pollIntervalMs = POLL_INTERVAL_MS }: AppProps) {
  const { health, failed: healthFailed } = useHealth();
  const b = useBatch(pollIntervalMs);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [method, setMethod] = useState<ExtractionMethod | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const notify = useCallback(
    (text: string) => setToast({ id: Date.now() + Math.random(), text }),
    [],
  );
  const dismissToast = useCallback(() => setToast(null), []);

  const preciseDisabled = health !== null && !health.haiku_configured;
  useEffect(() => {
    if (preciseDisabled && method === 'precise') setMethod(null);
  }, [preciseDisabled, method]);

  // Completion toast when the batch reaches a terminal state.
  const prevPhase = useRef(b.phase);
  useEffect(() => {
    if (prevPhase.current !== 'results' && b.phase === 'results' && b.batch) {
      notify(finalSummaryMessage(b.batch));
    }
    prevPhase.current = b.phase;
  }, [b.phase, b.batch, notify]);

  const valid = entries.filter((e) => !e.error);
  const totalSize = valid.reduce((sum, e) => sum + e.file.size, 0);
  const canProcess = valid.length > 0 && method !== null && !b.busy;
  const helper = valid.length === 0 ? MSG.emptyBatch : method === null ? MSG.noMethod : null;

  const addFiles = (files: File[]) => {
    setSetupError(null);
    setEntries((prev) => [
      ...prev,
      ...files.map((file) => ({ id: nextEntryId(), file, error: validateFile(file) })),
    ]);
  };

  const removeFile = (id: string) => {
    setSetupError(null);
    setEntries((prev) => prev.filter((e) => e.id !== id));
  };

  const process = async () => {
    if (!method || valid.length === 0) return;
    if (valid.length > MAX_FILES_PER_BATCH) {
      setSetupError(MSG.tooManyFiles);
      return;
    }
    setSetupError(null);
    await b.submit(
      valid.map((e) => e.file),
      method,
    );
  };

  const newBatch = async () => {
    await b.reset();
    setEntries([]);
    setMethod(null);
    setSetupError(null);
  };

  let liveText = '';
  if (b.batch && b.phase === 'processing') {
    const c = countDocs(b.batch);
    liveText = MSG.progress(c.completed + c.failed, c.total);
  } else if (b.batch && b.phase === 'results') {
    liveText = finalSummaryMessage(b.batch);
  }

  const processLabel = `Process ${valid.length} ${valid.length === 1 ? 'file' : 'files'}`;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-content flex-wrap items-center justify-between gap-2 px-4 py-3">
          <h1 className="text-lg font-bold">Document Classification &amp; Extraction</h1>
          <HealthBadge health={health} failed={healthFailed} />
        </div>
      </header>

      <main className="mx-auto max-w-content space-y-6 px-4 py-6">
        {b.error && (
          <div
            role="alert"
            className="flex items-start justify-between gap-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900"
          >
            <span>{b.error}</span>
            <button
              type="button"
              onClick={b.clearError}
              aria-label="Dismiss error"
              className="rounded px-1 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-800"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
        )}

        {b.phase === 'setup' && (
          <section aria-label="Upload documents" className="space-y-4">
            <Dropzone onFiles={addFiles} disabled={b.busy} />
            <FileList entries={entries} onRemove={removeFile} />
            {valid.length > 0 && (
              <p className="text-sm text-slate-800">
                {MSG.ready(valid.length)}{' '}
                <span className="text-slate-700">Total size: {formatBytes(totalSize)}</span>
              </p>
            )}
            <MethodSelector
              value={method}
              onChange={(m) => {
                setMethod(m);
                setSetupError(null);
              }}
              preciseDisabled={preciseDisabled}
              disabled={b.busy}
            />
            {setupError && (
              <p role="alert" className="text-sm font-medium text-red-800">
                {setupError}
              </p>
            )}
            <div className="flex flex-wrap items-center justify-end gap-3">
              {helper && (
                <p id="process-helper" className="text-sm text-slate-700">
                  {helper}
                </p>
              )}
              <button
                type="button"
                onClick={() => void process()}
                disabled={!canProcess}
                aria-describedby={helper ? 'process-helper' : undefined}
                className="rounded-md bg-indigo-700 px-5 py-2 font-semibold text-white hover:bg-indigo-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {b.busy ? 'Uploading…' : processLabel}
              </button>
            </div>
          </section>
        )}

        {b.phase === 'processing' && b.batch && (
          <ProgressPanel
            batch={b.batch}
            onCancel={() => void b.cancel()}
            cancelling={b.cancelling}
          />
        )}

        {b.phase === 'results' && b.batch && (
          <section aria-label="Results" className="space-y-4">
            <SummaryStrip batch={b.batch} />
            <ExportBar
              batch={b.batch}
              onRetry={() => void b.retry()}
              onNewBatch={() => void newBatch()}
              onNotify={notify}
              busy={b.busy}
            />
            <ResultsTable documents={b.batch.documents} onNotify={notify} />
          </section>
        )}
      </main>

      <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-region">
        {liveText}
      </div>
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
