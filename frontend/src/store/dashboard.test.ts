import { describe, expect, it } from 'vitest';
import { newestMeasurementAge } from './dashboard';
import type { TelemetryRow, ThermalSummary } from '../types/api';

function row(ts: string): TelemetryRow {
  return {
    equipment_code: 'CAP_DONG_01',
    equipment_name: 'Cụm máy nén cấp đông',
    kind: 'DEEP_FREEZER',
    status: 'RUNNING',
    temperature_c: -32.4,
    pressure_bar: 4.1,
    power_kw: 92,
    cooling_capacity_kw: 280,
    cop: 3.0,
    design_cop: 3.1,
    cop_gap_pct: -3.23,
    efficiency_pct: null,
    design_efficiency_pct: null,
    vibration_mm_s: 2.1,
    vibration_critical: false,
    haccp_limit_c: -18,
    haccp_breach: false,
    is_refrigeration: true,
    is_combustion: false,
    ts,
  };
}

function thermal(rows: TelemetryRow[]): ThermalSummary {
  return {
    total_power_kw: 326.11,
    avg_cop: 3.1,
    avg_boiler_efficiency_pct: null,
    total_units: rows.length,
    running: rows.length,
    warning: 0,
    fault: 0,
    telemetry: rows,
    alerts: [],
    vibration_limit_mm_s: 4.5,
    haccp_seafood_limit_c: -18,
  };
}

/** Backend trả UTC naive (không 'Z'), nên phải dựng chuỗi đúng dạng đó. */
function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString().slice(0, 19);
}

describe('newestMeasurementAge', () => {
  it('null khi vai trò không có phần Nhiệt', () => {
    expect(newestMeasurementAge(null)).toBeNull();
  });

  it('lấy phép đo mới nhất chứ không phải bản đầu tiên', () => {
    const age = newestMeasurementAge(
      thermal([row(isoMinutesAgo(120)), row(isoMinutesAgo(2)), row(isoMinutesAgo(60))]),
    );
    expect(age).toBe(2);
  });

  it('đọc được chuỗi UTC không kèm Z', () => {
    expect(newestMeasurementAge(thermal([row(isoMinutesAgo(9))]))).toBe(9);
  });

  it('null khi không có mốc thời gian nào đọc được', () => {
    expect(newestMeasurementAge(thermal([]))).toBeNull();
    expect(newestMeasurementAge(thermal([row(''), row('khong-phai-ngay')]))).toBeNull();
  });

  it('không âm khi đồng hồ máy chủ chạy trước trình duyệt', () => {
    expect(newestMeasurementAge(thermal([row(isoMinutesAgo(-30))]))).toBe(0);
  });
});
