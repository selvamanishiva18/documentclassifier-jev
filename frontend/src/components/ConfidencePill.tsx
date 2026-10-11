import { confidenceLevel, formatPercent } from '../lib/format';

const LEVEL_CLASSES = {
  high: 'bg-green-100 text-green-900 border-green-700',
  medium: 'bg-amber-100 text-amber-900 border-amber-700',
  low: 'bg-red-100 text-red-900 border-red-700',
} as const;

export function ConfidencePill({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) {
    return <span className="text-slate-600">—</span>;
  }
  const level = confidenceLevel(value);
  return (
    <span
      data-testid="confidence-pill"
      data-level={level}
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-semibold tabular-nums ${LEVEL_CLASSES[level]}`}
    >
      {formatPercent(value)}
    </span>
  );
}
