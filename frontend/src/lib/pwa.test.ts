import { afterEach, describe, expect, it, vi } from 'vitest';
import { canRegisterServiceWorker, registerServiceWorker } from './pwa';

const web = { protocol: 'https:', hasServiceWorker: true, isProd: true, isNative: false };

/** Chạy phần `window.addEventListener('load', ...)` mà registerServiceWorker đăng ký. */
function fireLoad() {
  window.dispatchEvent(new Event('load'));
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  delete window.Capacitor;
});

describe('canRegisterServiceWorker', () => {
  it('đăng ký khi chạy PWA thật trên http/https', () => {
    expect(canRegisterServiceWorker(web)).toBe(true);
    expect(canRegisterServiceWorker({ ...web, protocol: 'http:' })).toBe(true);
  });

  it('không đăng ký trên file:// của Electron', () => {
    expect(canRegisterServiceWorker({ ...web, protocol: 'file:' })).toBe(false);
  });

  it('không đăng ký trên capacitor:// của bản iOS', () => {
    expect(canRegisterServiceWorker({ ...web, protocol: 'capacitor:' })).toBe(false);
  });

  it('không đăng ký trên Android dù origin https://localhost giống hệt web', () => {
    expect(canRegisterServiceWorker({ ...web, isNative: true })).toBe(false);
  });

  it('không đăng ký ở dev server để hot-reload không bị cache đè', () => {
    expect(canRegisterServiceWorker({ ...web, isProd: false })).toBe(false);
  });

  it('không đăng ký khi trình duyệt không có serviceWorker', () => {
    expect(canRegisterServiceWorker({ ...web, hasServiceWorker: false })).toBe(false);
  });
});

describe('registerServiceWorker', () => {
  it('không gọi register khi đang ở trong vỏ native', () => {
    vi.stubEnv('PROD', true);
    window.Capacitor = { isNativePlatform: () => true };
    const register = vi.fn().mockResolvedValue({});
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { register },
    });

    registerServiceWorker();
    fireLoad();

    expect(register).not.toHaveBeenCalled();
  });
});
