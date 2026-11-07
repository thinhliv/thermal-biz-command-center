const vndWhole = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 });
const compactBillion = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 });
const compactMillion = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });

const numberFormatters = new Map<number, Intl.NumberFormat>();

function numberFormatter(digits: number): Intl.NumberFormat {
  let formatter = numberFormatters.get(digits);
  if (!formatter) {
    formatter = new Intl.NumberFormat('vi-VN', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    numberFormatters.set(digits, formatter);
  }
  return formatter;
}

export const DASH = '—';

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

/** Tiền tệ nguyên đồng. */
export function formatVND(value: number | null | undefined): string {
  if (isMissing(value)) return DASH;
  return `${vndWhole.format(value)} ₫`;
}

/** Bản gọn cho TV/kiosk: 3.480.000.000 → "3,48 tỷ ₫", 108.070.000 → "108,1 tr ₫". */
export function formatCompactVND(value: number | null | undefined): string {
  if (isMissing(value)) return DASH;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${compactBillion.format(value / 1e9)} tỷ ₫`;
  if (abs >= 1e6) return `${compactMillion.format(value / 1e6)} tr ₫`;
  return `${vndWhole.format(value)} ₫`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return DASH;
  return numberFormatter(digits).format(value);
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return DASH;
  return `${numberFormatter(digits).format(value)}%`;
}

export function formatSignedPct(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return DASH;
  const sign = value > 0 ? '+' : '';
  return `${sign}${numberFormatter(digits).format(value)}%`;
}

export function formatTemp(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return DASH;
  return `${numberFormatter(digits).format(value)}°C`;
}

export function formatKwh(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return DASH;
  return `${numberFormatter(digits).format(value)} kWh`;
}

/**
 * Backend lưu thời gian dạng naive-UTC (không có "Z"). JS sẽ hiểu nhầm chuỗi đó là
 * GIỜ LOCAL và lệch 7 tiếng ở Việt Nam, nên phải tự gán múi giờ UTC trước khi parse.
 */
export function parseInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  const date = new Date(hasOffset ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatClock(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  return date ? date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : DASH;
}

export function formatDateTime(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return DASH;
  return date.toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  const date = parseInstant(iso);
  if (!date) return DASH;
  const seconds = Math.max(0, Math.round((now.getTime() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s trước`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  return `${Math.round(hours / 24)} ngày trước`;
}

/**
 * Chuỗi "YYYY-MM-DD" (revenue_trend_30d) là NGÀY thuần, không phải thời điểm.
 * Đừng dùng parseInstant ở đây: nó sẽ bị dịch 1 ngày khi local lệch khỏi UTC.
 */
export function formatDayMonth(dateOnly: string | null | undefined): string {
  if (!dateOnly) return DASH;
  const [year, month, day] = dateOnly.split('-');
  return year && month && day ? `${day}/${month}` : dateOnly;
}

export function clamp(value: number, min = 0, max = 100): number {
  return Math.min(max, Math.max(min, value));
}
