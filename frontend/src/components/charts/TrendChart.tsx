import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatCompactVND, formatDayMonth } from '../../lib/format';
import { TONE_HEX, TOOLTIP_STYLE } from '../../lib/tones';
import type { RevenueTrendPoint } from '../../types/api';
import { AXIS_LINE, AXIS_TICK, ChartFrame, CURSOR_FILL, GRID_STROKE } from './ChartFrame';

interface TrendChartProps {
  data: RevenueTrendPoint[] | undefined;
  height?: number;
}

/** Doanh thu + lợi nhuận gộp 30 ngày. Trục Y nén về tỷ/triệu để TV đọc được từ xa. */
export function TrendChart({ data, height = 240 }: TrendChartProps) {
  const rows = data ?? [];
  return (
    <ChartFrame height={height} empty={rows.length === 0}>
      <AreaChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="gradRevenue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={TONE_HEX.cyan} stopOpacity={0.35} />
            <stop offset="100%" stopColor={TONE_HEX.cyan} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={(value: string) => formatDayMonth(value)}
          tick={AXIS_TICK}
          axisLine={AXIS_LINE}
          tickLine={false}
          minTickGap={24}
        />
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
          labelFormatter={(value: string) => `Ngày ${formatDayMonth(value)}`}
          formatter={(value: number, name: string) => [formatCompactVND(value), name]}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
        <Area
          type="monotone"
          dataKey="revenue_vnd"
          name="Doanh thu"
          stroke={TONE_HEX.cyan}
          strokeWidth={2}
          fill="url(#gradRevenue)"
        />
        <Line
          type="monotone"
          dataKey="gross_profit_vnd"
          name="Lợi nhuận gộp"
          stroke={TONE_HEX.emerald}
          strokeWidth={2}
          dot={false}
        />
      </AreaChart>
    </ChartFrame>
  );
}
