import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  cancelBatch,
  createBatch,
  deleteBatch,
  getBatch,
  retryBatch,
} from '../api/client';
import { POLL_INTERVAL_MS } from '../lib/limits';
import { MSG } from '../lib/messages';
import { isTerminalBatch, type Batch, type ExtractionMethod } from '../types';

export type Phase = 'setup' | 'processing' | 'results';

function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : MSG.genericError;
}

/** Submit, poll, cancel, retry, and reset a batch (PRD 16.2 hooks/useBatch.ts). */
export function useBatch(pollIntervalMs: number = POLL_INTERVAL_MS) {
  const [phase, setPhase] = useState<Phase>('setup');
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const applyBatch = useCallback((b: Batch) => {
    setBatch(b);
    const terminal = isTerminalBatch(b.status);
    setPhase(terminal ? 'results' : 'processing');
    if (terminal) setCancelling(false);
  }, []);

  const expire = useCallback(() => {
    setBatch(null);
    setPhase('setup');
    setCancelling(false);
    setError(MSG.expired);
  }, []);

  const batchId = batch?.batch_id ?? null;

  useEffect(() => {
    if (phase !== 'processing' || !batchId) return undefined;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const b = await getBatch(batchId);
        if (stopped) return;
        applyBatch(b);
        if (isTerminalBatch(b.status)) return;
      } catch (e) {
        if (stopped) return;
        if (e instanceof ApiError && e.status === 404) {
          expire();
          return;
        }
        // Transient poll failures are ignored; the next tick tries again.
      }
      timer = setTimeout(() => void tick(), pollIntervalMs);
    };

    timer = setTimeout(() => void tick(), pollIntervalMs);
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [phase, batchId, pollIntervalMs, applyBatch, expire]);

  const submit = useCallback(
    async (files: File[], method: ExtractionMethod): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        const created = await createBatch(files, method);
        const full = await getBatch(created.batch_id);
        applyBatch(full);
        return true;
      } catch (e) {
        setError(errorMessage(e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [applyBatch],
  );

  const cancel = useCallback(async () => {
    if (!batch) return;
    setCancelling(true);
    setError(null);
    try {
      applyBatch(await cancelBatch(batch.batch_id));
    } catch (e) {
      setCancelling(false);
      setError(errorMessage(e));
    }
  }, [batch, applyBatch]);

  const retry = useCallback(async () => {
    if (!batch) return;
    setBusy(true);
    setError(null);
    try {
      applyBatch(await retryBatch(batch.batch_id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [batch, applyBatch]);

  const reset = useCallback(async () => {
    if (batch) {
      try {
        await deleteBatch(batch.batch_id);
      } catch {
        // Already purged or unreachable: the server TTL cleans up regardless.
      }
    }
    setBatch(null);
    setPhase('setup');
    setCancelling(false);
    setError(null);
  }, [batch]);

  const clearError = useCallback(() => setError(null), []);

  return { phase, batch, error, busy, cancelling, submit, cancel, retry, reset, clearError };
}
