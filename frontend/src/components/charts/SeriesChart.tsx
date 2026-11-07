import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatClock, formatNumber, formatTemp } from '../../lib/format';
import { TONE_HEX, TOOLTIP_STYLE } from '../../lib/tones';
import type { SeriesResponse } from '../../types/api';
import { AXIS_LINE, AXIS_TICK, ChartFrame, GRID_STROKE } from './ChartFrame';

interface SeriesChartProps {
  series: SeriesResponse | undefined | null;
  height?: number;
}

/**
 * Máy lạnh và lò hơi là HAI đại lượng khác nhau: COP = Q/N và η = hiệu suất cháy.
 * Không bao giờ vẽ chung một trục — thiết bị đốt chỉ có η, thiết bị lạnh chỉ có COP.
 */
export function SeriesChart({ series, height = 260 }: SeriesChartProps) {
  if (!series || series.points.length === 0) {
    return <ChartFrame height={height} empty emptyLabel="Chưa có chuỗi đo cho thiết bị này" />;
  }

  const isCombustion = series.is_combustion;
  const efficiencyKey = isCombustion ? 'efficiency_pct' : 'cop';
  const efficiencyLabel = isCombustion ? 'Hiệu suất η (%)' : 'COP';
  const designValue = isCombustion ? series.design_efficiency_pct : series.design_cop;

  return (
    <ChartFrame height={height}>
      <LineChart data={series.points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ts"
          tickFormatter={(value: string) => formatClock(value)}
          tick={AXIS_TICK}
          axisLine={AXIS_LINE}
          tickLine={false}
          minTickGap={40}
        />
        <YAxis
          yAxisId="temp"
          tickFormatter={(value: number) => formatNumber(value, 0)}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={44}
          domain={['auto', 'auto']}
        />
        <YAxis
          yAxisId="eff"
          orientation="right"
          tickFormatter={(value: number) => formatNumber(value, isCombustion ? 0 : 1)}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={44}
          domain={['auto', 'auto']}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(value: string) => formatClock(value)}
          formatter={(value: number, name: string) => [
            name === 'Nhiệt độ' ? formatTemp(value) : formatNumber(value, isCombustion ? 2 : 2),
            name,
          ]}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />

        {series.haccp_limit_c !== null ? (
          <ReferenceLine
            yAxisId="temp"
            y={series.haccp_limit_c}
            stroke={TONE_HEX.rose}
            strokeDasharray="4 4"
            label={{ value: `HACCP ${formatTemp(series.haccp_limit_c, 0)}`, fill: TONE_HEX.rose, fontSize: 10, position: 'insideBottomLeft' }}
          />
        ) : null}
        {series.setpoint_c !== null ? (
          <ReferenceLine
            yAxisId="temp"
            y={series.setpoint_c}
            stroke={TONE_HEX.sky}
            strokeDasharray="2 4"
            label={{ value: `Setpoint ${formatTemp(series.setpoint_c, 0)}`, fill: TONE_HEX.sky, fontSize: 10, position: 'insideTopLeft' }}
          />
        ) : null}
        {designValue !== null ? (
          <ReferenceLine
            yAxisId="eff"
            y={designValue}
            stroke={TONE_HEX.emerald}
            strokeDasharray="4 4"
            label={{ value: `Thiết kế ${formatNumber(designValue, isCombustion ? 0 : 1)}`, fill: TONE_HEX.emerald, fontSize: 10, position: 'insideTopRight' }}
          />
        ) : null}

        <Line
          yAxisId="temp"
          type="monotone"
          dataKey="temperature_c"
          name="Nhiệt độ"
          stroke={TONE_HEX.cyan}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
        <Line
          yAxisId="eff"
          type="monotone"
          dataKey={efficiencyKey}
          name={efficiencyLabel}
          stroke={TONE_HEX.amber}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
      </LineChart>
    </ChartFrame>
  );
}
