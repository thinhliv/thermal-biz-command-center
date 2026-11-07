import type { ReactNode } from 'react';
import { ResponsiveContainer } from 'recharts';
import { EmptyBlock } from '../ui/StateBlock';

/** Trục + lưới dùng chung cho toàn bộ biểu đồ, giữ màu tối đồng nhất với theme. */
export const AXIS_TICK = { fill: '#64748b', fontSize: 10 } as const;
export const AXIS_LINE = { stroke: '#1e293b' } as const;
export const GRID_STROKE = '#1e293b';
export const CURSOR_FILL = 'rgba(148,163,184,0.08)';

interface ChartFrameProps {
  height?: number;
  empty?: boolean;
  emptyLabel?: string;
  /** Không bắt buộc vì nhánh `empty` trả về EmptyBlock và không dùng tới children. */
  children?: ReactNode;
}

/**
 * Recharts cần cha có kích thước xác định; nếu không ResponsiveContainer đo ra 0 và
 * biểu đồ biến mất. Khung này cố định chiều cao để mọi nơi dùng giống nhau.
 */
export function ChartFrame({ height = 220, empty = false, emptyLabel, children }: ChartFrameProps) {
  if (empty) return <EmptyBlock label={emptyLabel ?? 'Chưa có dữ liệu để vẽ biểu đồ'} />;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children as never}
      </ResponsiveContainer>
    </div>
  );
}
