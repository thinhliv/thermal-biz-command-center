import { API_BASE } from './config';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Auth store gọi hàm này để đưa người dùng về trang đăng nhập khi token hết hạn (401). */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

function describeError(status: number, body: unknown): string {
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? (body as { detail: unknown }).detail
      : undefined;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (status === 401) return 'Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.';
  if (status === 403) return 'Vai trò của bạn không có quyền xem dữ liệu này.';
  if (status === 404) return 'Không tìm thấy dữ liệu.';
  if (status >= 500) return 'Máy chủ gặp lỗi, thử lại sau.';
  return `Yêu cầu thất bại (HTTP ${status}).`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (error) {
    // Huỷ request (đổi tab, unmount) không phải lỗi kết nối — để caller tự bỏ qua.
    if ((error as Error | undefined)?.name === 'AbortError') throw error;
    throw new ApiError(0, 'Không kết nối được tới máy chủ. Kiểm tra backend và VITE_API_URL.');
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const body: unknown = text ? safeParse(text) : null;

  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(response.status, describeError(response.status, body));
  }
  return body as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 200) };
  }
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: 'GET', signal });
}

export function apiPost<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
}
