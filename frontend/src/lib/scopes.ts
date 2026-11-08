import type { Role, Scope } from '../types/api';

export const ROLE_LABELS: Record<Role, string> = {
  BGD: 'Ban Giám Đốc',
  VANHANH: 'Vận hành',
  KETOAN: 'Kế toán',
  L1_CHAIRMAN: 'L1 · Chủ tịch HĐQT',
  L2_CEO: 'L2 · Tổng Giám đốc',
  L3_TECHNICAL_DIRECTOR: 'L3 · Giám đốc Kỹ thuật',
  L4_OPERATIONS_MANAGER: 'L4 · Quản lý Vận hành',
  L5_MAINTENANCE_ENGINEER: 'L5 · Kỹ sư Bảo trì',
  L6_HACCP_AUDITOR: 'L6 · Kiểm toán HACCP',
  L7_WAREHOUSE_DISPATCHER: 'L7 · Điều phối Kho lạnh',
  L8_CFO: 'L8 · Giám đốc Tài chính',
  L9_BILLING_SPECIALIST: 'L9 · Billing ESCO',
  L10_SALES_EXECUTIVE: 'L10 · Kinh doanh B2B',
};

export const ROLE_HINTS: Record<Role, string> = {
  BGD: 'Thấy toàn bộ Nhiệt, Cảnh báo, Kinh doanh và Công nợ',
  VANHANH: 'Chỉ thấy Kỹ thuật Nhiệt và Cảnh báo',
  KETOAN: 'Chỉ thấy Kinh doanh và Công nợ',
  L1_CHAIRMAN: 'Toàn quyền — dành cho cổ đông chiến lược',
  L2_CEO: 'Toàn quyền điều hành trên tất cả các trụ',
  L3_TECHNICAL_DIRECTOR: 'Nhiệt, Cảnh báo, AI chẩn đoán, Đồng bộ và Nhật ký kiểm toán',
  L4_OPERATIONS_MANAGER: 'Nhiệt, Cảnh báo và Đồng bộ trạm — không thấy tiền',
  L5_MAINTENANCE_ENGINEER: 'Nhiệt, Cảnh báo và lịch cắt đỉnh phụ tải',
  L6_HACCP_AUDITOR: 'Báo cáo HACCP, dấu chân ESG và nhật ký kiểm toán',
  L7_WAREHOUSE_DISPATCHER: 'Chỉ thấy Kỹ thuật Nhiệt và Cảnh báo',
  L8_CFO: 'Kinh doanh, Công nợ, ESG và Nhật ký kiểm toán',
  L9_BILLING_SPECIALIST: 'Chỉ thấy Kinh doanh và Công nợ',
  L10_SALES_EXECUTIVE: 'Chỉ thấy Kinh doanh',
};

export type RouteIcon = 'gauge' | 'snowflake' | 'shield-alert' | 'trending-up' | 'receipt';

export interface RouteDef {
  path: string;
  label: string;
  short: string;
  scope: Scope;
  icon: RouteIcon;
}

/**
 * Đường dẫn để dạng ASCII: Electron/Capacitor đọc từ file:// nên tránh ký tự có dấu.
 *
 * Chỉ 5 scope có trang thật. `audit` / `compliance` / `ai` / `sync` cố ý KHÔNG nằm ở đây:
 * thêm route mà chưa có page thì NavBar hiện ra một tab dẫn thẳng tới NotFoundPage.
 * `scopes.test.ts` khoá bất biến "mọi vai trò phải còn ít nhất một tab" để không ai
 * rơi vào vòng lặp `homePath() -> /login`.
 */
export const ROUTES: RouteDef[] = [
  { path: '/overview', label: 'Tổng quan', short: 'Tổng quan', scope: 'overview', icon: 'gauge' },
  { path: '/thermal', label: 'Kỹ thuật Nhiệt', short: 'Nhiệt', scope: 'thermal', icon: 'snowflake' },
  { path: '/alerts', label: 'Cảnh báo', short: 'Cảnh báo', scope: 'alerts', icon: 'shield-alert' },
  { path: '/business', label: 'Kinh doanh', short: 'Kinh doanh', scope: 'business', icon: 'trending-up' },
  { path: '/debts', label: 'Công nợ', short: 'Công nợ', scope: 'debts', icon: 'receipt' },
];

export function can(scopes: Scope[] | undefined, scope: Scope): boolean {
  return Boolean(scopes?.includes(scope));
}

export function allowedRoutes(scopes: Scope[] | undefined): RouteDef[] {
  return ROUTES.filter((route) => can(scopes, route.scope));
}

export function homePath(scopes: Scope[] | undefined): string {
  return allowedRoutes(scopes)[0]?.path ?? '/login';
}
