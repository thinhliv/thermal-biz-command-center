/**
 * Electron đọc từ `file://`, Capacitor đọc từ `capacitor://` — hai trường hợp đó
 * không có origin cùng máy chủ nên PHẢI đặt VITE_API_URL lúc build.
 * Ở trình duyệt thì để trống: dev nhờ Vite proxy, prod nhờ reverse proxy cùng origin.
 */
function resolveApiBase(): string {
  const configured = (import.meta.env.VITE_API_URL ?? '').trim();
  if (configured) return configured.replace(/\/+$/, '');
  if (window.location.protocol === 'file:') return 'http://localhost:8080';
  return '';
}

export const API_BASE = resolveApiBase();

export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

export const TOKEN_STORAGE_KEY = 'thermal-biz.token';

export const WS_TELEMETRY_PATH = '/ws/telemetry';
