import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveApiBase } from './config';

afterEach(() => {
  vi.unstubAllEnvs();
  delete window.Capacitor;
});

describe('resolveApiBase', () => {
  it('VITE_API_URL thắng mọi suy luận và bị cắt dấu / cuối', () => {
    vi.stubEnv('VITE_API_URL', 'https://api.example.com/');
    expect(resolveApiBase('https:')).toBe('https://api.example.com');
    expect(resolveApiBase('file:')).toBe('https://api.example.com');
  });

  it('web cùng origin thì để trống cho proxy lo', () => {
    vi.stubEnv('VITE_API_URL', '');
    expect(resolveApiBase('https:')).toBe('');
    expect(resolveApiBase('http:')).toBe('');
  });

  it('Electron (file://) fallback về backend trên chính máy đó', () => {
    vi.stubEnv('VITE_API_URL', '');
    expect(resolveApiBase('file:')).toBe('http://localhost:8080');
  });

  it('iOS simulator (capacitor://) cũng dùng chung mạng với máy host', () => {
    vi.stubEnv('VITE_API_URL', '');
    expect(resolveApiBase('capacitor:')).toBe('http://localhost:8080');
  });

  it('Android chạy ở https://localhost nên phải nhận ra qua bridge native', () => {
    vi.stubEnv('VITE_API_URL', '');
    expect(resolveApiBase('https:')).toBe('');
    window.Capacitor = { isNativePlatform: () => true };
    expect(resolveApiBase('https:')).toBe('http://10.0.2.2:8080');
  });

  it('coi chuỗi toàn khoảng trắng là chưa cấu hình', () => {
    vi.stubEnv('VITE_API_URL', '   ');
    expect(resolveApiBase('file:')).toBe('http://localhost:8080');
  });
});
