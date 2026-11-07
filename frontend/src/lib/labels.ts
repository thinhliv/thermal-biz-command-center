import type { Tone } from './tones';
import type { EquipmentKind, EquipmentStatus, OrderStatus, Severity } from '../types/api';

export const SEVERITY_LABELS: Record<Severity, string> = {
  CRITICAL: 'Nghiêm trọng',
  MAJOR: 'Nặng',
  WARNING: 'Cảnh báo',
  INFO: 'Thông tin',
};

export const SEVERITY_TONES: Record<Severity, Tone> = {
  CRITICAL: 'rose',
  MAJOR: 'amber',
  WARNING: 'sky',
  INFO: 'slate',
};

export const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'MAJOR', 'WARNING', 'INFO'];

export const EQUIPMENT_STATUS_LABELS: Record<EquipmentStatus, string> = {
  RUNNING: 'Đang chạy',
  STANDBY: 'Chờ',
  DEFROST: 'Rã đông',
  FAULT: 'Lỗi',
  STOPPED: 'Dừng',
};

export const EQUIPMENT_STATUS_TONES: Record<EquipmentStatus, Tone> = {
  RUNNING: 'emerald',
  STANDBY: 'slate',
  DEFROST: 'sky',
  FAULT: 'rose',
  STOPPED: 'slate',
};

export const EQUIPMENT_KIND_LABELS: Record<EquipmentKind, string> = {
  DEEP_FREEZER: 'Kho đông sâu',
  COLD_ROOM: 'Kho mát',
  BLAST_FREEZER: 'Hầm cấp đông gió',
  CHILLER: 'Chiller',
  COMPRESSOR: 'Cụm máy nén',
  BOILER: 'Lò hơi',
};

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  DRAFT: 'Nháp',
  IN_PROGRESS: 'Đang thực hiện',
  COMPLETED: 'Hoàn thành',
  CANCELLED: 'Huỷ',
};

export const ORDER_STATUS_TONES: Record<OrderStatus, Tone> = {
  DRAFT: 'slate',
  IN_PROGRESS: 'cyan',
  COMPLETED: 'emerald',
  CANCELLED: 'rose',
};

export const METRIC_LABELS: Record<string, string> = {
  temperature_c: 'Nhiệt độ',
  cop: 'COP',
  efficiency_pct: 'Hiệu suất η',
  vibration_mm_s: 'Rung động',
  pressure_bar: 'Áp suất',
  power_kw: 'Công suất',
};

export const TARIFF_BAND_LABELS: Record<string, string> = {
  PEAK: 'Giờ cao điểm',
  NORMAL: 'Giờ bình thường',
  OFF_PEAK: 'Giờ thấp điểm',
};

export const TARIFF_BAND_TONES: Record<string, Tone> = {
  PEAK: 'rose',
  NORMAL: 'amber',
  OFF_PEAK: 'emerald',
};

/** Thứ tự cố định: biểu đồ/đồ thị phải luôn xếp đúng ba khung giờ, không phụ thuộc key của JSON. */
export const TARIFF_BAND_ORDER = ['PEAK', 'NORMAL', 'OFF_PEAK'] as const;

/** Màu theo thứ tự bracket aging trả về từ backend (trong hạn → quá hạn nặng nhất). */
export const AGING_TONES: Tone[] = ['emerald', 'sky', 'amber', 'rose', 'rose'];

/**
 * Backend trả `bracket` dạng chuỗi tiếng Việt không dấu, không kèm chỉ số. Suy ra bậc
 * từ số ngày quá hạn để chọn màu — các mốc khớp đúng với bracket backend đang dùng.
 */
export function agingTone(overdueDays: number): Tone {
  if (overdueDays <= 0) return AGING_TONES[0];
  if (overdueDays <= 30) return AGING_TONES[1];
  if (overdueDays <= 60) return AGING_TONES[2];
  if (overdueDays <= 90) return AGING_TONES[3];
  return AGING_TONES[4];
}
