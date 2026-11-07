import { describe, expect, it } from 'vitest';
import { AGING_TONES, agingTone } from './labels';
import { allowedRoutes, can, homePath, ROLE_LABELS, ROUTES } from './scopes';
import type { Scope } from '../types/api';

/**
 * Đúng bằng scopes mà backend trả về trong /api/auth/me cho từng vai trò.
 * Nếu hai đầu lệch nhau thì menu sẽ hiện trang mà API từ chối phục vụ.
 */
const ROLE_SCOPES: Record<string, Scope[]> = {
  BGD: ['overview', 'thermal', 'alerts', 'business', 'debts'],
  VANHANH: ['thermal', 'alerts'],
  KETOAN: ['business', 'debts'],
};

describe('can()', () => {
  it('từ chối khi chưa biết scopes', () => {
    expect(can(undefined, 'overview')).toBe(false);
    expect(can([], 'thermal')).toBe(false);
  });

  it('chấp nhận đúng scope có trong danh sách', () => {
    expect(can(ROLE_SCOPES.VANHANH, 'alerts')).toBe(true);
    expect(can(ROLE_SCOPES.VANHANH, 'business')).toBe(false);
  });
});

describe('allowedRoutes() — menu phải khớp quyền', () => {
  it('BGĐ thấy cả 5 trang', () => {
    expect(allowedRoutes(ROLE_SCOPES.BGD).map((route) => route.path)).toEqual([
      '/overview',
      '/thermal',
      '/alerts',
      '/business',
      '/debts',
    ]);
  });

  it('Vận hành chỉ thấy Nhiệt và Cảnh báo, không thấy tiền', () => {
    const paths = allowedRoutes(ROLE_SCOPES.VANHANH).map((route) => route.path);
    expect(paths).toEqual(['/thermal', '/alerts']);
    expect(paths).not.toContain('/business');
    expect(paths).not.toContain('/debts');
  });

  it('Kế toán chỉ thấy Kinh doanh và Công nợ', () => {
    expect(allowedRoutes(ROLE_SCOPES.KETOAN).map((route) => route.path)).toEqual(['/business', '/debts']);
  });

  it('mọi route đều có nhãn tiếng Việt và scope hợp lệ', () => {
    const validScopes: Scope[] = ['overview', 'thermal', 'alerts', 'business', 'debts'];
    for (const route of ROUTES) {
      expect(route.label.length).toBeGreaterThan(0);
      expect(validScopes).toContain(route.scope);
    }
  });
});

describe('homePath() — trang đích sau đăng nhập', () => {
  it('lấy trang đầu tiên mà vai trò xem được', () => {
    expect(homePath(ROLE_SCOPES.BGD)).toBe('/overview');
    expect(homePath(ROLE_SCOPES.VANHANH)).toBe('/thermal');
    expect(homePath(ROLE_SCOPES.KETOAN)).toBe('/business');
  });

  it('không có quyền gì thì về trang đăng nhập thay vì trang trắng', () => {
    expect(homePath([])).toBe('/login');
    expect(homePath(undefined)).toBe('/login');
  });
});

describe('ROLE_LABELS', () => {
  it('đủ tên tiếng Việt cho cả ba vai backend công bố', () => {
    expect(Object.keys(ROLE_LABELS).sort()).toEqual(['BGD', 'KETOAN', 'VANHANH']);
  });
});

describe('agingTone() — suy bậc màu từ số ngày quá hạn', () => {
  it('khớp các mốc bracket của backend', () => {
    expect(agingTone(0)).toBe(AGING_TONES[0]);
    expect(agingTone(-5)).toBe(AGING_TONES[0]);
    expect(agingTone(12)).toBe(AGING_TONES[1]);
    expect(agingTone(30)).toBe(AGING_TONES[1]);
    expect(agingTone(31)).toBe(AGING_TONES[2]);
    expect(agingTone(55)).toBe(AGING_TONES[2]);
    expect(agingTone(61)).toBe(AGING_TONES[3]);
    expect(agingTone(90)).toBe(AGING_TONES[3]);
    expect(agingTone(112)).toBe(AGING_TONES[4]);
  });

  it('nợ càng lâu màu càng gắt, không bao giờ đảo ngược', () => {
    const order = [0, 20, 50, 80, 200].map((days) => AGING_TONES.indexOf(agingTone(days)));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});
