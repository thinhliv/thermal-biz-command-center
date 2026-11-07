import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, apiPost, onUnauthorized, setAccessToken } from './api';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('lib/api', () => {
  beforeEach(() => {
    setAccessToken(null);
    onUnauthorized(() => {});
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function fetchMock() {
    return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  }

  it('không gửi header Authorization khi chưa đăng nhập', async () => {
    fetchMock().mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiGet('/api/health');
    const init = fetchMock().mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBeNull();
  });

  it('gắn Bearer token khi đã đăng nhập', async () => {
    setAccessToken('jwt-day-la-token');
    fetchMock().mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiGet('/api/auth/me');
    const init = fetchMock().mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer jwt-day-la-token');
  });

  it('POST có body thì tự khai Content-Type, không body thì không', async () => {
    // Response chỉ đọc được một lần, nên test gọi hai lượt phải tạo mới mỗi lượt.
    fetchMock().mockImplementation(async () => jsonResponse(200, {}));
    await apiPost('/api/alerts/1/acknowledge', { note: 'đã xử lý' });
    const withBody = fetchMock().mock.calls[0][1] as RequestInit;
    expect(new Headers(withBody.headers).get('Content-Type')).toBe('application/json');
    expect(withBody.body).toBe(JSON.stringify({ note: 'đã xử lý' }));

    await apiPost('/api/alerts/1/clear');
    const withoutBody = fetchMock().mock.calls[1][1] as RequestInit;
    expect(new Headers(withoutBody.headers).get('Content-Type')).toBeNull();
    expect(withoutBody.body).toBeUndefined();
  });

  it('ưu tiên thông báo lỗi thật từ FastAPI detail', async () => {
    fetchMock().mockResolvedValue(jsonResponse(409, { detail: 'Canh bao da duoc xac nhan.' }));
    await expect(apiPost('/api/alerts/7/acknowledge', {})).rejects.toThrow('Canh bao da duoc xac nhan.');
  });

  it('lấy msg đầu tiên khi detail là mảng validate của Pydantic', async () => {
    fetchMock().mockResolvedValue(
      jsonResponse(422, { detail: [{ loc: ['body', 'new_password'], msg: 'String should have at least 8 characters' }] }),
    );
    await expect(apiPost('/api/auth/change-password', {})).rejects.toThrow('String should have at least 8 characters');
  });

  it('dịch các mã lỗi quen thuộc sang tiếng Việt khi server không kèm detail', async () => {
    fetchMock().mockResolvedValue(jsonResponse(401, {}));
    await expect(apiGet('/api/business')).rejects.toThrow('Phiên đăng nhập hết hạn');

    fetchMock().mockResolvedValue(jsonResponse(403, {}));
    await expect(apiGet('/api/business')).rejects.toThrow('không có quyền');

    fetchMock().mockResolvedValue(jsonResponse(404, {}));
    await expect(apiGet('/api/business')).rejects.toThrow('Không tìm thấy dữ liệu');

    fetchMock().mockResolvedValue(jsonResponse(503, {}));
    await expect(apiGet('/api/business')).rejects.toThrow('Máy chủ gặp lỗi');
  });

  it('401 phải đá người dùng ra đăng nhập', async () => {
    const handler = vi.fn();
    onUnauthorized(handler);
    setAccessToken('token-het-han');
    fetchMock().mockResolvedValue(jsonResponse(401, {}));
    await expect(apiGet('/api/auth/me')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('không gộp huỷ request thành lỗi mất kết nối', async () => {
    const abort = new DOMException('The user aborted a request.', 'AbortError');
    fetchMock().mockRejectedValue(abort);
    await expect(apiGet('/api/thermal')).rejects.toBe(abort);
  });

  it('lỗi mạng thật thì báo rõ để người dùng biết kiểm tra backend', async () => {
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    const error = await apiGet('/api/thermal').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toContain('Không kết nối được tới máy chủ');
  });

  it('204 không có body thì trả undefined chứ không nổ JSON.parse', async () => {
    fetchMock().mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiPost('/api/auth/change-password', {})).resolves.toBeUndefined();
  });

  it('body không phải JSON vẫn đọc được thành detail', async () => {
    fetchMock().mockResolvedValue(
      new Response('<html>502 Bad Gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }),
    );
    const error = await apiGet('/api/health').catch((caught: unknown) => caught);
    expect((error as ApiError).message).toContain('502 Bad Gateway');
  });
});
