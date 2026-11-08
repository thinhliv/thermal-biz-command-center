import { describe, expect, it } from 'vitest';
import { AGING_TONES, agingTone } from './labels';
import { allowedRoutes, can, homePath, ROLE_HINTS, ROLE_LABELS, ROUTES } from './scopes';
import type { Role, Scope } from '../types/api';

/**
 * Bản sao của `ROLE_SCOPES` trong `backend/app/security.py` — đúng bằng scopes mà backend
 * trả về trong /api/auth/me cho từng vai trò. Nếu hai đầu lệch nhau thì menu sẽ hiện
 * trang mà API từ chối phục vụ, nên `test_frontend_role_scope_khop_backend` (pytest) đọc
 * chính file này và đối chiếu với enum Role + ALL_SCOPES thật.
 */
const ALL_SCOPES: Scope[] = [
  'overview',
  'thermal',
  'alerts',
  'business',
  'debts',
  'audit',
  'compliance',
  'ai',
  'sync',
];

const ROLE_SCOPES: Record<Role, Scope[]> = {
  BGD: ALL_SCOPES,
  VANHANH: ['thermal', 'alerts'],
  KETOAN: ['business', 'debts'],
  L1_CHAIRMAN: ALL_SCOPES,
  L2_CEO: ALL_SCOPES,
  L3_TECHNICAL_DIRECTOR: ['overview', 'thermal', 'alerts', 'audit', 'ai', 'sync'],
  L4_OPERATIONS_MANAGER: ['thermal', 'alerts', 'sync'],
  L5_MAINTENANCE_ENGINEER: ['thermal', 'alerts', 'ai'],
  L6_HACCP_AUDITOR: ['overview', 'thermal', 'alerts', 'compliance', 'audit'],
  L7_WAREHOUSE_DISPATCHER: ['thermal', 'alerts'],
  L8_CFO: ['overview', 'business', 'debts', 'audit', 'compliance'],
  L9_BILLING_SPECIALIST: ['business', 'debts'],
  L10_SALES_EXECUTIVE: ['business'],
};

/** Scope đã có trang thật trong `App.tsx`. Bốn scope còn lại chưa có page. */
const PAGED_SCOPES: Scope[] = ['overview', 'thermal', 'alerts', 'business', 'debts'];

describe('can()', () => {
  it('từ chối khi chưa biết scopes', () => {
    expect(can(undefined, 'overview')).toBe(false);
    expect(can([], 'thermal')).toBe(false);
  });

  it('chấp nhận đúng scope có trong danh sách', () => {
    expect(can(ROLE_SCOPES.VANHANH, 'alerts')).toBe(true);
    expect(can(ROLE_SCOPES.VANHANH, 'business')).toBe(false);
  });

  it('scope trụ mới cũng được nhận diện, không âm thầm coi là lạ', () => {
    expect(can(ROLE_SCOPES.L6_HACCP_AUDITOR, 'compliance')).toBe(true);
    expect(can(ROLE_SCOPES.L6_HACCP_AUDITOR, 'ai')).toBe(false);
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
    for (const route of ROUTES) {
      expect(route.label.length).toBeGreaterThan(0);
      expect(PAGED_SCOPES).toContain(route.scope);
    }
  });

  it('hai chiều: scope đã có page thì phải có route, và không route nào trỏ vào page chưa tồn tại', () => {
    /**
     * Lệch một trong hai chiều đều sinh ra UI chết: thiếu route thì page viết ra không ai
     * vào được, thừa route thì NavBar hiện tab dẫn thẳng tới NotFoundPage.
     */
    expect(ROUTES.map((route) => route.scope).sort()).toEqual([...PAGED_SCOPES].sort());
    expect(ROUTES.every((route) => route.path.startsWith('/'))).toBe(true);
    expect(new Set(ROUTES.map((route) => route.path)).size).toBe(ROUTES.length);
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

  it('mọi vai trò đều còn ít nhất một tab — không ai bị đá ngược về /login', () => {
    /**
     * Bất biến sống còn: `RequireScope` redirect về `homePath()` khi vào route bị cấm, còn
     * `homePath()` trả '/login' khi không có tab nào. Vai nào chỉ được cấp scope CHƯA có page
     * (audit / compliance / ai / sync) sẽ tạo vòng lặp đăng nhập-ngay-sau-khi-đăng-nhập.
     */
    for (const role of Object.keys(ROLE_SCOPES) as Role[]) {
      const landing = homePath(ROLE_SCOPES[role]);
      expect(landing, `${role} không có tab nào để đáp xuống`).not.toBe('/login');
      expect(allowedRoutes(ROLE_SCOPES[role]).length, role).toBeGreaterThan(0);
    }
  });
});

describe('ROLE_LABELS', () => {
  it('đủ tên tiếng Việt cho tất cả vai trò backend công bố', () => {
    expect(Object.keys(ROLE_LABELS).sort()).toEqual([
      'BGD',
      'KETOAN',
      'L10_SALES_EXECUTIVE',
      'L1_CHAIRMAN',
      'L2_CEO',
      'L3_TECHNICAL_DIRECTOR',
      'L4_OPERATIONS_MANAGER',
      'L5_MAINTENANCE_ENGINEER',
      'L6_HACCP_AUDITOR',
      'L7_WAREHOUSE_DISPATCHER',
      'L8_CFO',
      'L9_BILLING_SPECIALIST',
      'VANHANH',
    ]);
  });
});

describe('ROLE_HINTS', () => {
  it('đủ gợi ý cho tất cả vai trò backend công bố', () => {
    expect(Object.keys(ROLE_HINTS).sort()).toEqual(Object.keys(ROLE_LABELS).sort());
  });

  it('nhãn và gợi ý không rỗng — chip vai trò rỗng thì người dùng không biết mình là ai', () => {
    for (const role of Object.keys(ROLE_LABELS) as Role[]) {
      expect(ROLE_LABELS[role].trim().length, role).toBeGreaterThan(0);
      expect(ROLE_HINTS[role].trim().length, role).toBeGreaterThan(0);
    }
  });

  it('ma trận scope phủ đúng tập vai trò có nhãn', () => {
    expect(Object.keys(ROLE_SCOPES).sort()).toEqual(Object.keys(ROLE_LABELS).sort());
    for (const role of Object.keys(ROLE_SCOPES) as Role[]) {
      for (const scope of ROLE_SCOPES[role]) {
        expect(ALL_SCOPES, `${role} được cấp scope lạ ${scope}`).toContain(scope);
      }
    }
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
