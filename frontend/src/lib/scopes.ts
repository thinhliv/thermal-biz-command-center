import type { Role, Scope } from '../types/api';

export const ROLE_LABELS: Record<Role, string> = {
  BGD: 'Ban Giám Đốc',
  VANHANH: 'Vận hành',
  KETOAN: 'Kế toán',
};

export const ROLE_HINTS: Record<Role, string> = {
  BGD: 'Thấy toàn bộ Nhiệt, Cảnh báo, Kinh doanh và Công nợ',
  VANHANH: 'Chỉ thấy Kỹ thuật Nhiệt và Cảnh báo',
  KETOAN: 'Chỉ thấy Kinh doanh và Công nợ',
};

export type RouteIcon = 'gauge' | 'snowflake' | 'shield-alert' | 'trending-up' | 'receipt';

export interface RouteDef {
  path: string;
  label: string;
  short: string;
  scope: Scope;
  icon: RouteIcon;
}

/** Đường dẫn để dạng ASCII: Electron/Capacitor đọc từ file:// nên tránh ký tự có dấu. */
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
