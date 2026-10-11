import type { DocumentStatus } from '../types';

const STYLES: Record<DocumentStatus, { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-slate-100 text-slate-800' },
  extracting: { label: 'Extracting', className: 'bg-blue-100 text-blue-900' },
  classifying: { label: 'Classifying', className: 'bg-indigo-100 text-indigo-900' },
  completed: { label: 'Completed', className: 'bg-green-100 text-green-900' },
  failed: { label: 'Failed', className: 'bg-red-100 text-red-900' },
  cancelled: { label: 'Cancelled', className: 'bg-slate-200 text-slate-800' },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const s = STYLES[status];
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${s.className}`}
      data-status={status}
    >
      {s.label}
    </span>
  );
}
