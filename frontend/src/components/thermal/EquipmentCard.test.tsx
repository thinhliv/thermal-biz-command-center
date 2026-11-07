import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EquipmentCard } from './EquipmentCard';
import type { TelemetryRow } from '../../types/api';

function row(overrides: Partial<TelemetryRow> = {}): TelemetryRow {
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
    ts: '2026-11-07T10:28:00',
    ...overrides,
  };
}

const BOILER = row({
  equipment_code: 'LO_HOI_01',
  equipment_name: 'Lò hơi biomass 10 tấn',
  kind: 'BOILER',
  temperature_c: 172.5,
  pressure_bar: 8.2,
  power_kw: 45,
  cooling_capacity_kw: null,
  cop: null,
  design_cop: null,
  cop_gap_pct: null,
  efficiency_pct: 84.79,
  design_efficiency_pct: 85,
  haccp_limit_c: null,
  is_refrigeration: false,
  is_combustion: true,
});

describe('EquipmentCard — COP và η là hai đại lượng khác nhau', () => {
  it('thiết bị lạnh hiện COP, tuyệt đối không hiện hiệu suất cháy', () => {
    render(<EquipmentCard row={row()} />);
    expect(screen.getByText(/COP · thiết kế/)).toBeInTheDocument();
    expect(screen.queryByText(/η/)).not.toBeInTheDocument();
  });

  it('thiết bị đốt hiện η, tuyệt đối không hiện COP', () => {
    render(<EquipmentCard row={BOILER} />);
    expect(screen.getByText(/η · thiết kế/)).toBeInTheDocument();
    expect(screen.queryByText(/COP/)).not.toBeInTheDocument();
  });

  it('ô số liệu thứ hai đổi đơn vị theo loại thiết bị', () => {
    const cold = render(<EquipmentCard row={row()} />);
    expect(cold.getByText('Lạnh')).toBeInTheDocument();
    cold.unmount();

    render(<EquipmentCard row={BOILER} />);
    expect(screen.getByText('Áp suất')).toBeInTheDocument();
  });
});

describe('EquipmentCard — an toàn thực phẩm và cơ khí', () => {
  it('vượt ngưỡng HACCP thì báo rõ nguy cơ', () => {
    render(<EquipmentCard row={row({ temperature_c: -12.6, haccp_breach: true })} />);
    expect(screen.getByText(/Vi phạm HACCP/)).toBeInTheDocument();
    expect(screen.getByText(/nguy cơ mất an toàn thực phẩm/)).toBeInTheDocument();
  });

  it('rung vượt ISO 10816-3 thì nhắc kiểm tra bạc đạn', () => {
    render(<EquipmentCard row={row({ vibration_mm_s: 4.76, vibration_critical: true })} />);
    expect(screen.getByText(/vùng C\/D theo ISO 10816-3/)).toBeInTheDocument();
  });

  it('vi phạm HACCP lấn át cảnh báo rung để không hiện hai banner cùng lúc', () => {
    render(
      <EquipmentCard row={row({ temperature_c: -10, haccp_breach: true, vibration_mm_s: 5.2, vibration_critical: true })} />,
    );
    expect(screen.getByText(/Vi phạm HACCP/)).toBeInTheDocument();
    expect(screen.queryByText(/vùng C\/D theo ISO 10816-3/)).not.toBeInTheDocument();
  });

  it('máy chạy bình thường thì không có banner nào', () => {
    render(<EquipmentCard row={row()} />);
    expect(screen.queryByText(/Vi phạm HACCP/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ISO 10816-3, cần kiểm tra/)).not.toBeInTheDocument();
  });

  it('COP tụt sâu so với thiết kế thì hiện số âm', () => {
    render(<EquipmentCard row={row({ cop: 2.42, design_cop: 3.1, cop_gap_pct: -21.94 })} />);
    expect(screen.getByText('-21,9%')).toBeInTheDocument();
  });
});

describe('EquipmentCard — tương tác chọn thiết bị', () => {
  it('không phải nút bấm khi không có onSelect', () => {
    render(<EquipmentCard row={row()} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('bấm chuột thì báo mã thiết bị', async () => {
    const onSelect = vi.fn();
    render(<EquipmentCard row={row()} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith('CAP_DONG_01');
  });

  it('bàn phím cũng chọn được (TV kiosk dùng remote)', async () => {
    const onSelect = vi.fn();
    render(<EquipmentCard row={BOILER} onSelect={onSelect} />);
    const card = screen.getByRole('button');
    card.focus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('LO_HOI_01');
  });
});
