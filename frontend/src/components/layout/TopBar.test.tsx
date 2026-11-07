import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LiveBadge } from './TopBar';
import type { SocketStatus } from '../../hooks/useTelemetrySocket';

function badge(status: SocketStatus, ageMinutes: number | null) {
  const { container } = render(<LiveBadge status={status} ageMinutes={ageMinutes} />);
  return {
    text: (container.textContent ?? '').replace(/\s+/g, ' ').trim(),
    title: container.querySelector('span')?.getAttribute('title') ?? '',
  };
}

describe('LiveBadge', () => {
  it('kênh mở và số liệu mới thì báo LIVE', () => {
    expect(badge('open', 0).text).toBe('LIVE');
    expect(badge('open', 5).text).toBe('LIVE');
  });

  it('kênh mở nhưng số liệu cũ thì không được nhận là LIVE', () => {
    const stale = badge('open', 6);
    expect(stale.text).toBe('Dữ liệu cũ · 6 phút');
    expect(stale.title).toContain('nguồn số liệu có thể đã ngừng gửi');
  });

  it('đổi sang giờ khi quá 60 phút để nhãn không tràn trên TV', () => {
    expect(badge('open', 185).text).toBe('Dữ liệu cũ · 3 giờ');
  });

  it('không kết luận dữ liệu cũ khi kênh chưa mở', () => {
    expect(badge('reconnecting', 185).text).toBe('Mất kết nối');
    expect(badge('connecting', 185).text).toBe('Đang kết nối');
    expect(badge('disabled', 185).text).toBe('Không realtime');
  });

  it('không có tuổi dữ liệu (vai trò không xem phần Nhiệt) thì vẫn báo LIVE', () => {
    expect(badge('open', null).text).toBe('LIVE');
  });
});
