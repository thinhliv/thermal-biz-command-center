import { describe, expect, it } from 'vitest';
import {
  DASH,
  clamp,
  formatCompactVND,
  formatDayMonth,
  formatKwh,
  formatNumber,
  formatPct,
  formatRelative,
  formatSignedPct,
  formatTemp,
  formatVND,
  parseInstant,
} from './format';

describe('parseInstant — backend gửi naive-UTC, không có "Z"', () => {
  it('hiểu chuỗi không múi giờ là UTC chứ không phải giờ local', () => {
    expect(parseInstant('2026-11-07T10:28:00')?.toISOString()).toBe('2026-11-07T10:28:00.000Z');
  });

  it('giữ nguyên chuỗi đã có offset', () => {
    expect(parseInstant('2026-11-07T10:28:00Z')?.toISOString()).toBe('2026-11-07T10:28:00.000Z');
    expect(parseInstant('2026-11-07T10:28:00+07:00')?.toISOString()).toBe('2026-11-07T03:28:00.000Z');
  });

  it('trả null cho giá trị rỗng hoặc rác', () => {
    expect(parseInstant(null)).toBeNull();
    expect(parseInstant('')).toBeNull();
    expect(parseInstant('không phải ngày')).toBeNull();
  });
});

describe('formatDayMonth — ngày thuần, không được dịch múi giờ', () => {
  it('không đổi ngày kể cả khi local lệch khỏi UTC', () => {
    expect(formatDayMonth('2026-10-09')).toBe('09/10');
    expect(formatDayMonth('2026-01-01')).toBe('01/01');
  });

  it('giữ nguyên chuỗi lạ thay vì trả về ngày sai', () => {
    expect(formatDayMonth('Q4')).toBe('Q4');
    expect(formatDayMonth(null)).toBe(DASH);
  });
});

describe('formatVND / formatCompactVND', () => {
  it('in đủ số đồng khi còn nhỏ', () => {
    expect(formatVND(850_000)).toBe('850.000 ₫');
  });

  it('rút gọn thành triệu và tỷ cho màn TV', () => {
    expect(formatCompactVND(108_070_000)).toBe('108,1 tr ₫');
    expect(formatCompactVND(3_480_000_000)).toBe('3,48 tỷ ₫');
  });

  it('giữ dấu âm của nợ', () => {
    expect(formatCompactVND(-1_500_000_000)).toBe('-1,5 tỷ ₫');
  });

  it('không bịa số khi thiếu dữ liệu', () => {
    expect(formatVND(null)).toBe(DASH);
    expect(formatCompactVND(undefined)).toBe(DASH);
    expect(formatVND(Number.NaN)).toBe(DASH);
  });
});

describe('Định dạng đại lượng kỹ thuật', () => {
  it('COP và hiệu suất là hai đơn vị khác nhau', () => {
    expect(formatNumber(2.42, 2)).toBe('2,42');
    expect(formatPct(77.97)).toBe('78,0%');
    expect(formatPct(42, 0)).toBe('42%');
  });

  it('nhiệt độ âm của kho đông', () => {
    expect(formatTemp(-18.4)).toBe('-18,4°C');
    expect(formatTemp(-18, 0)).toBe('-18°C');
    expect(formatTemp(null)).toBe(DASH);
  });

  it('kWh và số có dấu', () => {
    expect(formatKwh(3149.27)).toBe('3.149,3 kWh');
    expect(formatSignedPct(2.53)).toBe('+2,5%');
    expect(formatSignedPct(-21.94)).toBe('-21,9%');
    expect(formatSignedPct(0)).toBe('0,0%');
  });
});

describe('formatRelative', () => {
  const now = new Date('2026-11-07T12:00:00Z');

  it('đếm ngược theo khoảng cách thật', () => {
    expect(formatRelative('2026-11-07T11:59:30', now)).toBe('30s trước');
    expect(formatRelative('2026-11-07T11:15:00', now)).toBe('45 phút trước');
    expect(formatRelative('2026-11-07T05:00:00', now)).toBe('7 giờ trước');
    expect(formatRelative('2026-11-05T12:00:00', now)).toBe('2 ngày trước');
  });

  it('không âm khi mốc thời gian nằm ở tương lai (lệch đồng hồ)', () => {
    expect(formatRelative('2026-11-07T12:05:00', now)).toBe('0s trước');
  });
});

describe('clamp', () => {
  it('kẹp vào 0..100 để thanh tiến độ không tràn khung', () => {
    expect(clamp(-12)).toBe(0);
    expect(clamp(48.6)).toBe(48.6);
    expect(clamp(167)).toBe(100);
  });
});
