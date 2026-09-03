'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = [], opts: { poll?: number } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const out = await fnRef.current();
      setData(out);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('UNKNOWN', String(e), 0));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!opts.poll) return;
    const t = setInterval(() => refresh(true), opts.poll);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.poll, ...deps]);

  return { data, error, loading, refresh };
}
