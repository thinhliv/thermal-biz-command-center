import React, { createContext, useContext, useMemo } from 'react';
import { useApi } from '../hooks/useApi';
import { useTelemetrySocket, type SocketStatus } from '../hooks/useTelemetrySocket';
import { parseInstant } from '../lib/format';
import { useAuth } from './auth';
import type {
  AlertRow,
  BusinessSummary,
  DashboardSummary,
  DebtSummary,
  EnergyCostReport,
  LoadShiftAnalysis,
  ThermalSummary,
} from '../types/api';

const REST_POLL_MS = 30_000;

interface DashboardContextValue {
  summary: DashboardSummary | null;
  thermal: ThermalSummary | null;
  alerts: AlertRow[] | null;
  business: BusinessSummary | null;
  debts: DebtSummary | null;
  energy: EnergyCostReport | null;
  loadShift: LoadShiftAnalysis | null;
  loading: boolean;
  error: string | null;
  socketStatus: SocketStatus;
  dataAgeMinutes: number | null;
  refresh: () => void;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

/**
 * Tuổi dữ liệu lấy từ phép đo mới nhất chứ không phải từ lúc gọi API: REST vẫn có thể
 * trả 200 với số đo cũ (nguồn Modbus/MQTT ngừng gửi), và đó mới là điều người vận hành
 * cần biết trước khi tin vào một màn hình HACCP.
 */
export function newestMeasurementAge(thermal: ThermalSummary | null): number | null {
  if (!thermal) return null;
  let newest = 0;
  for (const row of thermal.telemetry) {
    const at = parseInstant(row.ts);
    if (at) newest = Math.max(newest, at.getTime());
  }
  if (!newest) return null;
  return Math.max(0, Math.round((Date.now() - newest) / 60_000));
}

/**
 * Provider duy nhất cho cả shell: một WebSocket, một lần gọi REST, đổi tab không nạp lại.
 * REST trả dữ liệu theo chu kỳ (đủ cả 6 section của vai trò), WebSocket chỉ đẩy phần
 * Nhiệt + Cảnh báo nên được ghép chồng lên — bản live luôn thắng khi có.
 */
export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const { token, has } = useAuth();
  const liveAllowed = has('thermal') || has('alerts');

  const rest = useApi<DashboardSummary>('/api/dashboard-summary', { pollMs: REST_POLL_MS });
  const { snapshot, status } = useTelemetrySocket(token, liveAllowed);

  const value = useMemo<DashboardContextValue>(() => {
    const base = rest.data;
    const thermal = snapshot?.thermal_summary ?? base?.thermal_summary ?? null;
    const alerts = snapshot?.alerts ?? base?.alerts ?? null;
    return {
      summary: base,
      thermal,
      alerts,
      business: base?.business ?? null,
      debts: base?.debts ?? null,
      energy: base?.energy ?? null,
      loadShift: base?.load_shift ?? null,
      loading: rest.loading && !base,
      error: rest.error,
      socketStatus: status,
      dataAgeMinutes: newestMeasurementAge(thermal),
      refresh: rest.refresh,
    };
  }, [rest.data, rest.loading, rest.error, rest.refresh, snapshot, status]);

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(DashboardContext);
  if (!context) throw new Error('useDashboard phải nằm trong <DashboardProvider>');
  return context;
}
