declare global {
  interface Window {
    /**
     * Capacitor bơm object này vào WebView từ phía native, kể cả khi web app không
     * import @capacitor/core. Đây là tín hiệu duy nhất phân biệt được bản Android
     * (androidScheme: https → https://localhost) với một trang web thật cũng chạy
     * ở localhost, nên không thể chỉ nhìn protocol.
     */
    Capacitor?: { isNativePlatform?: () => boolean };
  }
}

/**
 * Ở trình duyệt thì base để trống: dev nhờ Vite proxy, prod nhờ reverse proxy cùng origin.
 *
 * Bản đóng gói không có origin cùng máy chủ với backend nên bắt buộc đặt VITE_API_URL
 * lúc build. Các giá trị fallback bên dưới chỉ để bản đóng gói mặc định vẫn gọi được
 * backend chạy trên chính máy dev/emulator, thay vì chết lặng không lời giải thích.
 */
export function resolveApiBase(protocol: string = window.location.protocol): string {
  const configured = (import.meta.env.VITE_API_URL ?? '').trim();
  if (configured) return configured.replace(/\/+$/, '');

  // Electron (file://) và iOS simulator (capacitor://) dùng chung mạng với máy chạy app.
  if (protocol === 'file:' || protocol === 'capacitor:') return 'http://localhost:8080';

  // Android: origin là https://localhost của WebView, còn máy host phải đi qua alias 10.0.2.2.
  if (window.Capacitor?.isNativePlatform?.() === true) return 'http://10.0.2.2:8080';

  return '';
}

export const API_BASE = resolveApiBase();

export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

export const TOKEN_STORAGE_KEY = 'thermal-biz.token';

export const WS_TELEMETRY_PATH = '/ws/telemetry';
