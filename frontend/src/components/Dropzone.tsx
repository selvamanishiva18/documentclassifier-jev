import { useId, useState, type DragEvent } from 'react';
import { MAX_FILES_PER_BATCH, MAX_FILE_SIZE_MB } from '../lib/limits';

interface DropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ onFiles, disabled = false }: DropzoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const inputId = useId();
  const hintId = useId();

  const handleDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) onFiles(files);
  };

  return (
    <div>
      <input
        id={inputId}
        type="file"
        multiple
        accept=".jpg,.jpeg,.pdf,image/jpeg,application/pdf"
        className="peer sr-only"
        disabled={disabled}
        aria-describedby={hintId}
        onChange={(e) => {
          const list = e.target.files;
          if (list && list.length) onFiles(Array.from(list));
          e.target.value = '';
        }}
      />
      <label
        htmlFor={inputId}
        data-testid="dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex h-40 w-full cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 text-center transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-indigo-700 ${
          dragOver
            ? 'border-indigo-700 bg-indigo-50'
            : 'border-slate-400 bg-white hover:bg-slate-50'
        }`}
      >
        <span className="font-medium text-slate-900">
          Drag and drop files here, or click to choose files
        </span>
        <span id={hintId} className="text-sm text-slate-700">
          JPG, JPEG, or PDF · up to {MAX_FILE_SIZE_MB} MB each · up to {MAX_FILES_PER_BATCH} files
        </span>
      </label>
    </div>
  );
}
