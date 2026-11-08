/**
 * Kiểu dữ liệu sinh ra từ contract thật của backend (GET /api/*).
 * Backend CẮT dữ liệu theo vai trò trước khi trả về, nên mỗi section đều optional:
 * KETOAN sẽ không bao giờ nhận được `thermal_summary`.
 */

/**
 * 13 vai: 3 vai truyen thong + ma tran L1-L10 Enterprise. Phai trung khop voi
 * `class Role` trong `backend/app/models.py`; `test_frontend_role_scope_khop_backend`
 * (backend) doc chinh file nay de bat lech.
 */
export type Role =
  | 'BGD'
  | 'VANHANH'
  | 'KETOAN'
  | 'L1_CHAIRMAN'
  | 'L2_CEO'
  | 'L3_TECHNICAL_DIRECTOR'
  | 'L4_OPERATIONS_MANAGER'
  | 'L5_MAINTENANCE_ENGINEER'
  | 'L6_HACCP_AUDITOR'
  | 'L7_WAREHOUSE_DISPATCHER'
  | 'L8_CFO'
  | 'L9_BILLING_SPECIALIST'
  | 'L10_SALES_EXECUTIVE';

/**
 * 9 scope, trung khop voi `ALL_SCOPES` trong `backend/app/security.py`.
 * `audit` / `compliance` / `ai` / `sync` da co endpoint nhung CHUA co trang rieng:
 * chung duoc dung de gate o `RequireScope` khi them page, con `ROUTES` chi liet ke
 * 5 tab da co man hinh that.
 */
export type Scope =
  | 'overview'
  | 'thermal'
  | 'alerts'
  | 'business'
  | 'debts'
  | 'audit'
  | 'compliance'
  | 'ai'
  | 'sync';

export type Severity = 'CRITICAL' | 'MAJOR' | 'WARNING' | 'INFO';

export type EquipmentStatus = 'RUNNING' | 'STANDBY' | 'DEFROST' | 'FAULT' | 'STOPPED';

export type EquipmentKind =
  | 'DEEP_FREEZER'
  | 'COLD_ROOM'
  | 'BLAST_FREEZER'
  | 'CHILLER'
  | 'COMPRESSOR'
  | 'BOILER';

export type TariffBand = 'PEAK' | 'NORMAL' | 'OFF_PEAK';

export type OrderStatus = 'DRAFT' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';

export type ReceivableStatus = 'OPEN' | 'PARTIAL' | 'PAID' | 'CANCELLED';

export type Metric =
  | 'temperature_c'
  | 'cop'
  | 'efficiency_pct'
  | 'vibration_mm_s'
  | 'pressure_bar'
  | 'power_kw';

export type Comparator = 'LT' | 'LTE' | 'GT' | 'GTE';

/** Quy tắc ngưỡng cảnh báo. `equipment_id` null + `applies_to_kind` = áp dụng theo loại. */
export interface AlarmRule {
  id: number;
  equipment_id: number | null;
  applies_to_kind: EquipmentKind | null;
  metric: Metric;
  comparator: Comparator;
  threshold: number;
  duration_minutes: number;
  severity: Severity;
  message_template: string;
  is_haccp: boolean;
  enabled: boolean;
}

export interface UserPublic {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  scopes: Scope[];
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in_minutes: number;
  user: UserPublic;
}

export interface AlertRow {
  id: number;
  severity: Severity;
  message: string;
  metric: string;
  observed_value: number | null;
  threshold: number | null;
  is_haccp: boolean;
  equipment_code: string;
  raised_at: string;
  cleared_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

export interface AlertStats {
  open_total: number;
  open_by_severity: Record<Severity, number>;
  haccp_open: number;
  unacknowledged_open: number;
  as_of: string;
}

/** Một dòng telemetry. Lò hơi có `efficiency_pct` và `cop = null`; máy lạnh ngược lại. */
export interface TelemetryRow {
  equipment_code: string;
  equipment_name: string;
  kind: EquipmentKind;
  status: EquipmentStatus;
  temperature_c: number | null;
  pressure_bar: number | null;
  power_kw: number | null;
  cooling_capacity_kw: number | null;
  cop: number | null;
  design_cop: number | null;
  cop_gap_pct: number | null;
  efficiency_pct: number | null;
  design_efficiency_pct: number | null;
  vibration_mm_s: number | null;
  vibration_critical: boolean;
  haccp_limit_c: number | null;
  haccp_breach: boolean;
  is_refrigeration: boolean;
  is_combustion: boolean;
  ts: string;
}

export interface ThermalSummary {
  total_power_kw: number;
  avg_cop: number | null;
  avg_boiler_efficiency_pct: number | null;
  total_units: number;
  running: number;
  warning: number;
  fault: number;
  telemetry: TelemetryRow[];
  alerts: AlertRow[];
  vibration_limit_mm_s: number;
  haccp_seafood_limit_c: number;
}

export interface EquipmentInfo {
  code: string;
  name: string;
  kind: EquipmentKind;
  location: string | null;
  refrigerant: string | null;
  rated_power_kw: number;
  setpoint_c: number | null;
  haccp_limit_c: number | null;
  design_cop: number | null;
  design_efficiency_pct: number | null;
  tenant_code: string | null;
  meter_entity_id: string | null;
  is_active: boolean;
  is_refrigeration: boolean;
  is_combustion: boolean;
}

export interface SeriesPoint {
  ts: string;
  temperature_c: number | null;
  pressure_bar: number | null;
  power_kw: number | null;
  cooling_capacity_kw: number | null;
  cop: number | null;
  efficiency_pct: number | null;
  vibration_mm_s: number | null;
  energy_kwh_cumulative: number | null;
  status: EquipmentStatus;
}

export interface SeriesResponse {
  equipment_code: string;
  equipment_name: string;
  kind: EquipmentKind;
  is_refrigeration: boolean;
  is_combustion: boolean;
  setpoint_c: number | null;
  haccp_limit_c: number | null;
  design_cop: number | null;
  design_efficiency_pct: number | null;
  points: SeriesPoint[];
}

export interface RecentOrder {
  order_code: string;
  customer: string;
  amount: number;
  service: string;
  volume_tons: number;
  cogs_vnd: number;
  gross_profit_vnd: number;
  margin: number;
  started_at: string;
  status: OrderStatus;
}

export interface RevenueByService {
  service: string;
  revenue_vnd: number;
  orders: number;
}

export interface RevenueTrendPoint {
  date: string;
  revenue_vnd: number;
  gross_profit_vnd: number;
  orders: number;
}

export interface BusinessSummary {
  today_revenue: number;
  mtd_revenue: number;
  target_revenue: number;
  target_progress_pct: number;
  electricity_cost_today: number;
  mtd_cogs_vnd: number;
  mtd_gross_profit_vnd: number;
  gross_margin_pct: number;
  gross_margin_target_pct: number;
  total_volume_tons: number;
  today_volume_tons: number;
  orders_today: number;
  recent_orders: RecentOrder[];
  revenue_by_service: RevenueByService[];
  revenue_trend_30d: RevenueTrendPoint[];
  as_of: string;
}

export interface CogsBreakdown {
  electricity_vnd: number;
  refrigerant_vnd: number;
  labor_vnd: number;
  maintenance_vnd: number;
  overhead_vnd: number;
}

export interface OrderDetail {
  order_code: string;
  customer: string;
  service: string;
  volume_tons: number;
  revenue_vnd: number;
  cogs_vnd: number;
  cogs_breakdown: CogsBreakdown;
  gross_profit_vnd: number;
  margin_pct: number;
  started_at: string;
  ended_at: string | null;
  status: OrderStatus;
}

export interface AgingBucket {
  bracket: string;
  amount: number;
}

export interface TopDebtor {
  customer_id: number;
  customer: string;
  amount: number;
  overdue_days: number;
  invoices: number;
  credit_limit_vnd: number;
  status: string;
  bracket: string;
  credit_utilization_pct: number;
  over_limit: boolean;
}

export interface OpenInvoice {
  id: number;
  invoice_number: string;
  customer: string;
  amount_vnd: number;
  paid_amount_vnd: number;
  outstanding_vnd: number;
  issued_at: string;
  due_at: string;
  overdue_days: number;
  bracket: string;
  status: ReceivableStatus;
}

export interface DebtSummary {
  total_receivables: number;
  overdue_debt: number;
  overdue_pct: number;
  aging_breakdown: AgingBucket[];
  top_debtors: TopDebtor[];
  open_invoices: OpenInvoice[];
  open_invoice_count: number;
  as_of: string;
}

/** Khách hàng có số dư nợ vượt hạn mức tín dụng — nguồn cảnh báo chặn xuất hàng. */
export interface CreditBreach {
  customer_id: number;
  customer_code: string;
  customer: string;
  credit_limit_vnd: number;
  outstanding_vnd: number;
  excess_vnd: number;
  utilization_pct: number;
}

export interface CustomerInfo {
  id: number;
  code: string;
  name: string;
  tax_id: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  email: string | null;
  credit_limit_vnd: number | null;
  payment_term_days: number;
  is_active: boolean;
}

export interface LoadShiftAnalysis {
  shift_pct: number;
  shifted_kwh: number;
  saving_vnd: number;
  baseline_electricity_vnd: number;
  saving_pct: number;
  peak_price_vnd_per_kwh: number;
  off_peak_price_vnd_per_kwh: number;
  price_gap_vnd_per_kwh: number;
}

export interface TopConsumer {
  equipment_code: string;
  equipment_name: string;
  kwh: number;
  cost_vnd: number;
  method: string;
}

export interface EnergyCostReport {
  period_start: string;
  period_end: string;
  total_kwh: number;
  total_cost_vnd: number;
  kwh_by_band: Partial<Record<TariffBand, number>>;
  prices_vnd_per_kwh: Partial<Record<TariffBand, number>>;
  method: string;
  shift_analysis: LoadShiftAnalysis;
  top_consumers: TopConsumer[];
}

export interface TariffBandInfo {
  code: TariffBand;
  name_vn: string;
  start_minute: number;
  end_minute: number;
  window: string;
  days: string;
  price_vnd_per_kwh: number;
  effective_from: string;
}

export interface TariffResponse {
  bands: TariffBandInfo[];
  prices_vnd_per_kwh: Partial<Record<TariffBand, number>>;
  note: string;
}

export interface DashboardMeta {
  role: Role;
  scopes: Scope[];
  sections: string[];
  as_of: string;
}

/** Chỉ có section mà vai trò được phép thấy. Đừng bao giờ giả sử đầy đủ. */
export interface DashboardSummary {
  thermal_summary?: ThermalSummary;
  alerts?: AlertRow[];
  business?: BusinessSummary;
  debts?: DebtSummary;
  energy?: EnergyCostReport;
  load_shift?: LoadShiftAnalysis;
  _meta: DashboardMeta;
}

/** Bản nhẹ của WebSocket: chỉ Nhiệt + Cảnh báo. */
export interface StreamSnapshot {
  thermal_summary?: ThermalSummary;
  alerts?: AlertRow[];
}

export interface SystemConfig {
  app_name: string;
  version: string;
  roles: Role[];
  scopes: Record<Role, Scope[]>;
  ws_interval_seconds: number;
  vibration_limit_mm_s: number;
  haccp_seafood_limit_c: number;
}
