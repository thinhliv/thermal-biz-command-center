import { Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from 'recharts';
import { formatKwh, formatNumber, formatVND } from '../../lib/format';
import { TARIFF_BAND_LABELS, TARIFF_BAND_ORDER, TARIFF_BAND_TONES } from '../../lib/labels';
import { TONE_HEX, TOOLTIP_STYLE } from '../../lib/tones';
import { AXIS_LINE, AXIS_TICK, ChartFrame, CURSOR_FILL, GRID_STROKE } from './ChartFrame';

interface BandChartProps {
  kwhByBand: Record<string, number> | undefined;
  prices: Record<string, number> | undefined;
  height?: number;
}

/** Sản lượng kWh theo 3 khung giờ TOU của EVN — nền tảng của bài toán dịch chuyển tải. */
export function BandChart({ kwhByBand, prices, height = 220 }: BandChartProps) {
  const rows = TARIFF_BAND_ORDER.map((band) => ({
    band,
    label: TARIFF_BAND_LABELS[band],
    kwh: kwhByBand?.[band] ?? 0,
    price: prices?.[band] ?? null,
  }));
  const hasData = rows.some((row) => row.kwh > 0);

  return (
    <ChartFrame height={height} empty={!hasData}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={AXIS_LINE} tickLine={false} interval={0} />
        <YAxis
          tickFormatter={(value: number) => formatNumber(value, 0)}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={56}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: CURSOR_FILL }}
          formatter={(value: number, _name: string, item) => {
            const price = (item?.payload as { price: number | null } | undefined)?.price;
            return [formatKwh(value), price === null ? 'kWh' : `kWh · ${formatVND(price)}/kWh`];
          }}
        />
        <Bar dataKey="kwh" radius={[3, 3, 0, 0]}>
          {rows.map((row) => (
            <Cell key={row.band} fill={TONE_HEX[TARIFF_BAND_TONES[row.band]]} />
          ))}
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}
