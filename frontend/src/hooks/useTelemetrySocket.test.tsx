import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTelemetrySocket } from './useTelemetrySocket';

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  readonly url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.onclose?.();
  }

  send(): void {}

  emitOpen(): void {
    act(() => this.onopen?.());
  }

  emitMessage(payload: unknown): void {
    const data = typeof payload === 'string' ? payload : JSON.stringify(payload);
    act(() => this.onmessage?.({ data } as MessageEvent<string>));
  }

  emitClose(): void {
    act(() => this.onclose?.());
  }
}

function lastSocket(): MockWebSocket {
  const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  if (!socket) throw new Error('Không có WebSocket nào được mở');
  return socket;
}

describe('useTelemetrySocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('KETOAN không mở socket: backend từ chối 403 ngay lúc bắt tay', () => {
    const { result } = renderHook(() => useTelemetrySocket('token-ketoan', false));
    expect(result.current.status).toBe('disabled');
    expect(result.current.snapshot).toBeNull();
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('chưa đăng nhập thì không mở socket', () => {
    const { result } = renderHook(() => useTelemetrySocket(null, true));
    expect(result.current.status).toBe('disabled');
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('trình duyệt không gửi được header nên token phải nằm trong query string', () => {
    const { result } = renderHook(() => useTelemetrySocket('jwt.vanhanh', true));
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(lastSocket().url).toContain('/ws/telemetry?token=jwt.vanhanh');
    expect(result.current.status).toBe('connecting');
  });

  it('token có ký tự đặc biệt vẫn phải an toàn trong URL', () => {
    renderHook(() => useTelemetrySocket('a b&c=d', true));
    expect(lastSocket().url).toContain('token=a%20b%26c%3Dd');
  });

  it('bắt tay thành công thì chuyển sang LIVE', () => {
    const { result } = renderHook(() => useTelemetrySocket('jwt', true));
    lastSocket().emitOpen();
    expect(result.current.status).toBe('open');
  });

  it('nhận snapshot Nhiệt + Cảnh báo từ server', () => {
    const { result } = renderHook(() => useTelemetrySocket('jwt', true));
    const socket = lastSocket();
    socket.emitOpen();
    socket.emitMessage({ thermal_summary: { total_power_kw: 384.8 }, alerts: [{ id: 1 }] });
    expect(result.current.snapshot?.thermal_summary?.total_power_kw).toBe(384.8);
    expect(result.current.snapshot?.alerts).toHaveLength(1);
  });

  it('khung tin hỏng thì giữ bản cũ, không làm sập màn hình', () => {
    const { result } = renderHook(() => useTelemetrySocket('jwt', true));
    const socket = lastSocket();
    socket.emitOpen();
    socket.emitMessage({ thermal_summary: { total_power_kw: 100 } });
    socket.emitMessage('{json cat ngang');
    expect(result.current.snapshot?.thermal_summary?.total_power_kw).toBe(100);
    expect(result.current.status).toBe('open');
  });

  it('rớt kết nối thì báo reconnecting và thử lại theo cấp số nhân', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useTelemetrySocket('jwt', true));
    const first = lastSocket();
    first.emitOpen();
    first.emitClose();
    expect(result.current.status).toBe('reconnecting');
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => vi.advanceTimersByTime(2000));
    expect(MockWebSocket.instances).toHaveLength(2);

    lastSocket().emitClose();
    act(() => vi.advanceTimersByTime(4000));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('unmount phải đóng socket, không để lọt kết nối mồ côi', () => {
    const { unmount } = renderHook(() => useTelemetrySocket('jwt', true));
    const socket = lastSocket();
    expect(socket.closed).toBe(false);
    unmount();
    expect(socket.closed).toBe(true);
  });

  it('StrictMode mount hai lần cũng chỉ giữ một socket sống', () => {
    const first = renderHook(() => useTelemetrySocket('jwt', true));
    const firstSocket = lastSocket();
    first.unmount();

    renderHook(() => useTelemetrySocket('jwt', true));
    expect(firstSocket.closed).toBe(true);
    expect(lastSocket().closed).toBe(false);
  });

  it('tắt realtime giữa chừng thì huỷ socket và xoá snapshot', () => {
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useTelemetrySocket('jwt', enabled),
      { initialProps: { enabled: true } },
    );
    lastSocket().emitOpen();
    lastSocket().emitMessage({ alerts: [{ id: 9 }] });
    expect(result.current.snapshot?.alerts).toHaveLength(1);

    rerender({ enabled: false });
    expect(result.current.status).toBe('disabled');
    expect(result.current.snapshot).toBeNull();
  });
});
