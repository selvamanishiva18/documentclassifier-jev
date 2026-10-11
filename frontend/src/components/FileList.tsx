import { formatBytes } from '../lib/format';

export interface FileEntry {
  id: string;
  file: File;
  error: string | null;
}

interface FileListProps {
  entries: FileEntry[];
  onRemove: (id: string) => void;
}

export function FileList({ entries, onRemove }: FileListProps) {
  if (entries.length === 0) return null;
  return (
    <ul
      aria-label="Selected files"
      className="divide-y divide-slate-200 rounded-lg border bg-white"
    >
      {entries.map((entry) => (
        <li
          key={entry.id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
        >
          <span className="min-w-0 flex-1 truncate font-medium" title={entry.file.name}>
            {entry.file.name}
          </span>
          <span className="text-slate-700">{formatBytes(entry.file.size)}</span>
          {entry.error && (
            <span className="w-full text-red-800 sm:w-auto">
              <span aria-hidden="true">ⓘ </span>
              {entry.error}
            </span>
          )}
          <button
            type="button"
            onClick={() => onRemove(entry.id)}
            aria-label={`Remove ${entry.file.name}`}
            className="rounded px-2 py-1 text-slate-700 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
