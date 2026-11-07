import { Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from 'recharts';
import { formatCompactVND } from '../../lib/format';
import { AGING_TONES } from '../../lib/labels';
import { TONE_HEX, TOOLTIP_STYLE } from '../../lib/tones';
import type { AgingBucket } from '../../types/api';
import { AXIS_LINE, AXIS_TICK, ChartFrame, CURSOR_FILL, GRID_STROKE } from './ChartFrame';

interface AgingBarProps {
  data: AgingBucket[] | undefined;
  height?: number;
}

/** Tuổi nợ theo bracket. Màu tăng dần từ xanh (trong hạn) sang đỏ (trên 90 ngày). */
export function AgingBar({ data, height = 220 }: AgingBarProps) {
  const rows = data ?? [];
  return (
    <ChartFrame height={height} empty={rows.length === 0}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="bracket" tick={AXIS_TICK} axisLine={AXIS_LINE} tickLine={false} interval={0} />
        <YAxis
          tickFormatter={(value: number) => formatCompactVND(value)}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={70}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: CURSOR_FILL }}
          formatter={(value: number) => [formatCompactVND(value), 'Số dư']}
        />
        <Bar dataKey="amount" radius={[3, 3, 0, 0]}>
          {rows.map((row, index) => (
            <Cell key={row.bracket} fill={TONE_HEX[AGING_TONES[index % AGING_TONES.length]]} />
          ))}
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}
