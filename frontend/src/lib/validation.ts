import { ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES } from './limits';
import { MSG } from './messages';

/** Client-side check (extension + size). Returns a rejection reason, or null when valid. */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return MSG.unsupportedType;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return MSG.oversize(file.name);
  }
  return null;
}
