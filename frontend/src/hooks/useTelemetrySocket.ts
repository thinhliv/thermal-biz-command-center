import { useEffect, useState } from 'react';
import { WS_BASE, WS_TELEMETRY_PATH } from '../lib/config';
import type { StreamSnapshot } from '../types/api';

export type SocketStatus = 'disabled' | 'connecting' | 'open' | 'reconnecting';

const MAX_BACKOFF_MS = 15_000;

export interface TelemetrySocket {
  snapshot: StreamSnapshot | null;
  status: SocketStatus;
}

/**
 * Trình duyệt không gửi được header Authorization qua WebSocket nên token nằm ở query
 * string. Đó vẫn là một JWT thật: backend từ chối bằng HTTP 403 ngay lúc bắt tay.
 *
 * Vì vậy KETOAN (không có scope thermal/alerts) phải truyền `enabled = false` — đừng
 * mở socket chỉ để nhận 403. `disposed` trong cleanup đảm bảo React.StrictMode mount
 * hai lần cũng không để lọt socket thứ hai sống sót.
 */
export function useTelemetrySocket(token: string | null, enabled: boolean): TelemetrySocket {
  const [snapshot, setSnapshot] = useState<StreamSnapshot | null>(null);
  const [status, setStatus] = useState<SocketStatus>(enabled && token ? 'connecting' : 'disabled');

  useEffect(() => {
    if (!enabled || !token) {
      setSnapshot(null);
      setStatus('disabled');
      return;
    }

    let disposed = false;
    let socket: WebSocket | null = null;
    let retryTimer = 0;
    let attempt = 0;

    const connect = () => {
      if (disposed) return;
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      const url = `${WS_BASE}${WS_TELEMETRY_PATH}?token=${encodeURIComponent(token)}`;
      socket = new WebSocket(url);

      socket.onopen = () => {
        if (disposed) return;
        attempt = 0;
        setStatus('open');
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        if (disposed) return;
        try {
          setSnapshot(JSON.parse(event.data) as StreamSnapshot);
        } catch {
          // Khung tin hỏng thì giữ nguyên bản cũ, không làm sập cả màn hình.
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        setStatus('reconnecting');
        attempt += 1;
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(attempt, 4));
        retryTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [enabled, token]);

  return { snapshot, status };
}
