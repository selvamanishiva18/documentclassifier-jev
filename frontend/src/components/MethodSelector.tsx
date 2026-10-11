import { useId } from 'react';
import { METHOD_COPY, MSG } from '../lib/messages';
import type { ExtractionMethod } from '../types';

interface MethodSelectorProps {
  value: ExtractionMethod | null;
  onChange: (method: ExtractionMethod) => void;
  preciseDisabled: boolean;
  disabled?: boolean;
}

const METHODS: ExtractionMethod[] = ['fast', 'precise'];

export function MethodSelector({
  value,
  onChange,
  preciseDisabled,
  disabled = false,
}: MethodSelectorProps) {
  const baseId = useId();

  return (
    <fieldset disabled={disabled}>
      <legend className="mb-2 font-semibold">Extraction method</legend>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {METHODS.map((m) => {
          const copy = METHOD_COPY[m];
          const isDisabled = m === 'precise' && preciseDisabled;
          const descId = `${baseId}-${m}-desc`;
          const reasonId = `${baseId}-${m}-reason`;
          const checked = value === m;
          return (
            <label
              key={m}
              className={`flex gap-3 rounded-lg border-2 bg-white p-4 has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-indigo-700 ${
                isDisabled
                  ? 'cursor-not-allowed border-slate-200 opacity-75'
                  : checked
                    ? 'cursor-pointer border-indigo-700'
                    : 'cursor-pointer border-slate-300 hover:border-slate-500'
              }`}
              title={
                isDisabled ? 'See README → Environment variables (ANTHROPIC_API_KEY)' : undefined
              }
            >
              <input
                type="radio"
                name="extraction_method"
                value={m}
                checked={checked}
                disabled={isDisabled}
                onChange={() => onChange(m)}
                aria-describedby={isDisabled ? `${descId} ${reasonId}` : descId}
                className="mt-1 h-4 w-4 accent-indigo-700"
              />
              <span className="flex flex-col gap-1">
                <span className="font-semibold">{copy.title}</span>
                <span id={descId} className="text-sm text-slate-700">
                  {copy.description}
                </span>
                {isDisabled && (
                  <span id={reasonId} className="text-sm font-medium text-red-800">
                    {MSG.preciseNotConfigured}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
