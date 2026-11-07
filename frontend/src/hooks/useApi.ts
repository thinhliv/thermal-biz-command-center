import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet } from '../lib/api';

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

function messageOf(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Yêu cầu thất bại.';
}

/**
 * `path = null` nghĩa là bị tắt (dùng để chặn theo quyền).
 * `pollMs > 0` thì gọi lại ngầm: không bật `loading` để màn hình không nhấp nháy.
 */
export function useApi<T>(path: string | null, options: { pollMs?: number } = {}): ApiState<T> {
  const { pollMs = 0 } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const activeRequest = useRef<AbortController | null>(null);

  const load = useCallback((target: string | null, silent: boolean) => {
    activeRequest.current?.abort();
    if (!target) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    activeRequest.current = controller;
    if (!silent) setLoading(true);
    apiGet<T>(target, controller.signal)
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((caught: unknown) => {
        if ((caught as Error).name !== 'AbortError') setError(messageOf(caught));
      })
      .finally(() => {
        if (activeRequest.current === controller) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load(path, false);
  }, [path, load]);

  useEffect(() => {
    if (!path || pollMs <= 0) return;
    const id = window.setInterval(() => load(path, true), pollMs);
    return () => window.clearInterval(id);
  }, [path, pollMs, load]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const refresh = useCallback(() => load(path, false), [load, path]);
  return { data, error, loading, refresh };
}
