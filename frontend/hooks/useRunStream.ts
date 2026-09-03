'use client';

/**
 * Live execution feed (§41). Tries Server-Sent Events first and transparently
 * degrades to polling — the UI works even when SSE is unavailable behind a
 * proxy or serverless edge.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiUrl } from '@/lib/api';
import type { RunStatusPayload, WorkflowEvent } from '@/lib/types';

export type Transport = 'sse' | 'polling' | 'idle';

export function useRunStream(runId: string | null, enabled = true) {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [status, setStatus] = useState<RunStatusPayload | null>(null);
  const [transport, setTransport] = useState<Transport>('idle');
  const seqRef = useRef(0);
  const stoppedRef = useRef(false);

  const pullStatus = useCallback(async () => {
    if (!runId) return null;
    try {
      const s = await api.runStatus(runId);
      setStatus(s);
      return s;
    } catch { return null; }
  }, [runId]);

  const pullEvents = useCallback(async () => {
    if (!runId) return;
    try {
      const batch = await api.runEvents(runId, seqRef.current);
      if (batch.length) {
        seqRef.current = batch[batch.length - 1].seq;
        setEvents((prev) => [...prev, ...batch]);
      }
    } catch { /* transient */ }
  }, [runId]);

  useEffect(() => {
    setEvents([]);
    seqRef.current = 0;
    stoppedRef.current = false;
    if (!runId || !enabled) { setTransport('idle'); return; }

    let source: EventSource | null = null;
    let statusTimer: ReturnType<typeof setInterval> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (pollTimer || stoppedRef.current) return;
      setTransport('polling');
      pullEvents();
      pollTimer = setInterval(pullEvents, 1500);
    };

    const finish = () => {
      stoppedRef.current = true;
      source?.close();
      if (pollTimer) clearInterval(pollTimer);
      if (statusTimer) clearInterval(statusTimer);
    };

    // Status is always polled: it is cheap and it is the source of truth.
    pullStatus().then((s) => { if (s?.terminal) { pullEvents().then(finish); } });
    statusTimer = setInterval(async () => {
      const s = await pullStatus();
      if (s?.terminal) { await pullEvents(); finish(); }
    }, 2000);

    if (typeof window !== 'undefined' && 'EventSource' in window) {
      try {
        source = new EventSource(apiUrl(`/api/runs/${runId}/stream?after_seq=0`));
        source.addEventListener('workflow', (e) => {
          const payload = JSON.parse((e as MessageEvent).data) as WorkflowEvent;
          seqRef.current = Math.max(seqRef.current, payload.seq);
          setEvents((prev) => (prev.some((p) => p.seq === payload.seq) ? prev : [...prev, payload]));
          setTransport('sse');
        });
        source.addEventListener('end', finish);
        source.onopen = () => setTransport('sse');
        source.onerror = () => { source?.close(); source = null; startPolling(); };
      } catch { startPolling(); }
    } else {
      startPolling();
    }

    return finish;
  }, [runId, enabled, pullEvents, pullStatus]);

  return { events, status, transport };
}
