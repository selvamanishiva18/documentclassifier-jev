export const MAX_FILE_SIZE_MB = 10;
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
export const MAX_FILES_PER_BATCH = 20;
export const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.pdf'] as const;
export const POLL_INTERVAL_MS = 1500;
