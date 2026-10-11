import { useId, useState, type KeyboardEvent } from 'react';
import { copyText, toPrettyJson } from '../lib/clipboard';
import { formatDuration, formatPercent, humanizeKey } from '../lib/format';
import { MSG } from '../lib/messages';
import {
  CANONICAL_FIELDS,
  DOCUMENT_TYPE_LABELS,
  type DocumentResult,
  type DocumentType,
} from '../types';

type TabKey = 'fields' | 'probabilities' | 'raw' | 'json';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'fields', label: 'Fields' },
  { key: 'probabilities', label: 'Probabilities' },
  { key: 'raw', label: 'Raw text' },
  { key: 'json', label: 'JSON' },
];

interface ResultDetailProps {
  doc: DocumentResult;
  onNotify: (message: string) => void;
}

export function ResultDetail({ doc, onNotify }: ResultDetailProps) {
  const baseId = useId();
  const [active, setActive] = useState<TabKey>('fields');
  const tabId = (k: TabKey) => `${baseId}-tab-${k}`;
  const panelId = (k: TabKey) => `${baseId}-panel-${k}`;

  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const idx = TABS.findIndex((t) => t.key === active);
    let next = idx;
    if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = TABS.length - 1;
    else return;
    e.preventDefault();
    const key = TABS[next].key;
    setActive(key);
    document.getElementById(tabId(key))?.focus();
  };

  // Mobile: tabs; desktop (md+): every panel visible in a two-column grid.
  const panelClass = (k: TabKey) =>
    `${active === k ? 'block' : 'hidden'} md:block min-w-0 space-y-2`;

  const copyDoc = async () => {
    if (await copyText(toPrettyJson(doc))) onNotify(MSG.copied);
  };

  const fields = CANONICAL_FIELDS.filter((k) => doc.extracted_fields[k]);
  const probs = doc.classification
    ? (Object.entries(doc.classification.probabilities) as [DocumentType, number][]).sort(
        (a, b) => b[1] - a[1],
      )
    : [];
  const chosen = doc.classification?.document_type;

  return (
    <div className="space-y-4 bg-slate-50 p-4">
      {doc.status === 'failed' && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          <p>{doc.error_message ?? MSG.genericError}</p>
          <details className="mt-1">
            <summary className="cursor-pointer font-medium">Details</summary>
            <p className="mt-1">
              Error code: <code data-testid="error-code">{doc.error_code}</code>
            </p>
          </details>
        </div>
      )}
      {doc.warnings.length > 0 && (
        <ul aria-label="Warnings" className="text-sm text-amber-900">
          {doc.warnings.map((w) => (
            <li key={w}>
              <span aria-hidden="true">⚠ </span>
              {w}
            </li>
          ))}
        </ul>
      )}

      <div role="tablist" aria-label="Result views" className="flex gap-1 border-b md:hidden">
        {TABS.map((t) => (
          <button
            key={t.key}
            id={tabId(t.key)}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            aria-controls={panelId(t.key)}
            tabIndex={active === t.key ? 0 : -1}
            onClick={() => setActive(t.key)}
            onKeyDown={onTabKeyDown}
            className={`rounded-t-md px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700 ${
              active === t.key ? 'border-b-2 border-indigo-700 text-indigo-900' : 'text-slate-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="md:grid md:grid-cols-2 md:gap-6">
        <div
          id={panelId('fields')}
          role="tabpanel"
          aria-labelledby={tabId('fields')}
          className={panelClass('fields')}
        >
          <h4 className="font-semibold">Fields</h4>
          {fields.length ? (
            <table className="w-full text-left text-sm">
              <tbody>
                {fields.map((k) => (
                  <tr key={k} className="border-b border-slate-200 align-top">
                    <th scope="row" className="py-1 pr-3 font-medium text-slate-700">
                      {humanizeKey(k)}
                    </th>
                    <td className="break-words py-1">{doc.extracted_fields[k]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-slate-700">No fields were extracted.</p>
          )}
        </div>

        <div
          id={panelId('probabilities')}
          role="tabpanel"
          aria-labelledby={tabId('probabilities')}
          className={panelClass('probabilities')}
        >
          <h4 className="font-semibold">Probabilities</h4>
          {doc.classification ? (
            <>
              <ul className="space-y-1" aria-label="Probability by document type">
                {probs.map(([key, p]) => {
                  const isChosen = key === chosen;
                  return (
                    <li
                      key={key}
                      data-testid="prob-row"
                      data-key={key}
                      data-chosen={isChosen ? 'true' : 'false'}
                      aria-current={isChosen ? 'true' : undefined}
                      className="text-sm"
                    >
                      <div className="flex justify-between gap-2">
                        <span className={isChosen ? 'font-semibold text-indigo-900' : ''}>
                          {DOCUMENT_TYPE_LABELS[key] ?? key}
                          {isChosen && <span className="sr-only"> (chosen)</span>}
                        </span>
                        <span className="tabular-nums">{formatPercent(p)}</span>
                      </div>
                      <div className="h-2 w-full rounded bg-slate-200" aria-hidden="true">
                        <div
                          className={`h-2 rounded ${isChosen ? 'bg-indigo-700' : 'bg-slate-500'}`}
                          style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
              <p className="text-xs text-slate-700">
                Model: {doc.classification.model} · Classified in{' '}
                {formatDuration(doc.classification.duration_ms)}
              </p>
            </>
          ) : (
            <p className="text-sm text-slate-700">Not classified.</p>
          )}
        </div>

        <div
          id={panelId('raw')}
          role="tabpanel"
          aria-labelledby={tabId('raw')}
          className={panelClass('raw')}
        >
          <h4 className="font-semibold">Raw text</h4>
          {doc.extraction ? (
            <>
              <p className="text-xs text-slate-700">
                Method: {doc.extraction.method} · Pages: {doc.document_metadata.page_count} ·
                Extracted in {formatDuration(doc.extraction.duration_ms)}
                {doc.extraction.ocr_mean_confidence !== null &&
                  ` · OCR confidence: ${doc.extraction.ocr_mean_confidence.toFixed(1)}`}
              </p>
              <pre
                tabIndex={0}
                aria-label={`Raw extracted text for ${doc.filename}`}
                className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded border bg-white p-2 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
              >
                {doc.extraction.raw_text}
              </pre>
            </>
          ) : (
            <p className="text-sm text-slate-700">No text was extracted.</p>
          )}
        </div>

        <div
          id={panelId('json')}
          role="tabpanel"
          aria-labelledby={tabId('json')}
          className={panelClass('json')}
        >
          <div className="flex items-center justify-between">
            <h4 className="font-semibold">JSON</h4>
            <button
              type="button"
              onClick={() => void copyDoc()}
              className="rounded-md border border-slate-400 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
            >
              Copy document JSON
            </button>
          </div>
          <pre
            tabIndex={0}
            aria-label={`JSON for ${doc.filename}`}
            className="max-h-80 overflow-auto rounded border bg-white p-2 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
          >
            {toPrettyJson(doc)}
          </pre>
        </div>
      </div>
    </div>
  );
}
