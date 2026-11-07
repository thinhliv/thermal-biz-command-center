import { Cell, Legend, Pie, PieChart, Tooltip } from 'recharts';
import { formatCompactVND } from '../../lib/format';
import { TONE_HEX, TOOLTIP_STYLE, type Tone } from '../../lib/tones';
import type { RevenueByService } from '../../types/api';
import { ChartFrame } from './ChartFrame';

/** Màu cố định theo vị trí — backend không gửi màu, và thứ tự service có thể đổi theo doanh thu. */
const SLICE_TONES: Tone[] = ['cyan', 'emerald', 'amber', 'violet', 'sky', 'rose', 'slate'];

interface ServicePieProps {
  data: RevenueByService[] | undefined;
  height?: number;
}

export function ServicePie({ data, height = 240 }: ServicePieProps) {
  const rows = (data ?? []).filter((item) => item.revenue_vnd > 0);
  return (
    <ChartFrame height={height} empty={rows.length === 0}>
      <PieChart>
        <Pie
          data={rows}
          dataKey="revenue_vnd"
          nameKey="service"
          innerRadius="52%"
          outerRadius="78%"
          paddingAngle={2}
          stroke="#0b0f19"
        >
          {rows.map((row, index) => (
            <Cell key={row.service} fill={TONE_HEX[SLICE_TONES[index % SLICE_TONES.length]]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => [formatCompactVND(value), name]}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
      </PieChart>
    </ChartFrame>
  );
}
