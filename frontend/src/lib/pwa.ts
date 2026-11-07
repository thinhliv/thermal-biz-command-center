export interface ServiceWorkerSupport {
  protocol: string;
  hasServiceWorker: boolean;
  isProd: boolean;
  isNative: boolean;
}

/**
 * Service worker chỉ dành cho bản PWA chạy trên trình duyệt.
 *
 * - Electron (`file://`) và iOS (`capacitor://`): scheme không có origin hợp lệ cho SW.
 * - Android: `androidScheme: https` nên origin là `https://localhost` — nhìn giống hệt một
 *   trang web thật, chỉ bridge native mới phân biệt được. Không loại trừ thì Android và iOS
 *   chạy hai đường khác nhau, và SW đi cache đúng những file Capacitor đã đặt sẵn trên máy.
 * - Dev server: SW cache asset sẽ phục vụ bản cũ đè lên hot-reload.
 */
export function canRegisterServiceWorker({
  protocol,
  hasServiceWorker,
  isProd,
  isNative,
}: ServiceWorkerSupport): boolean {
  if (isNative) return false;
  return hasServiceWorker && isProd && (protocol === 'http:' || protocol === 'https:');
}

export function registerServiceWorker(): void {
  const supported = canRegisterServiceWorker({
    protocol: window.location.protocol,
    hasServiceWorker: 'serviceWorker' in navigator,
    isProd: import.meta.env.PROD,
    isNative: window.Capacitor?.isNativePlatform?.() === true,
  });
  if (!supported) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      // BASE_URL là './' (vite.config) nên đường dẫn này đúng cả khi deploy dưới thư mục con.
      .register(`${import.meta.env.BASE_URL}sw.js`)
      .catch((error: unknown) => {
        console.warn('Không đăng ký được service worker; app vẫn chạy, chỉ mất chế độ offline.', error);
      });
  });
}
