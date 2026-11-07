import { Bolt, CircleDollarSign, Gauge, Layers, PieChart as PieIcon, Weight } from 'lucide-react';
import { ServicePie } from '../components/charts/ServicePie';
import { TrendChart } from '../components/charts/TrendChart';
import { OrderTable } from '../components/business/OrderTable';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader } from '../components/ui/Card';
import { MetricCard } from '../components/ui/MetricCard';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ErrorBlock, LoadingBlock } from '../components/ui/StateBlock';
import { useApi } from '../hooks/useApi';
import { formatCompactVND, formatNumber, formatPct, formatVND } from '../lib/format';
import { TARIFF_BAND_LABELS, TARIFF_BAND_ORDER, TARIFF_BAND_TONES } from '../lib/labels';
import { useDashboard } from '../store/dashboard';
import type { OrderDetail, TariffResponse } from '../types/api';

interface OrdersResponse {
  count: number;
  items: OrderDetail[];
}

export function BusinessPage() {
  const { business, loading, error, refresh } = useDashboard();
  const orders = useApi<OrdersResponse>('/api/business/orders?limit=25');
  const tariff = useApi<TariffResponse>('/api/business/tariff');

  if (loading) return <LoadingBlock label="Đang nạp số liệu kinh doanh…" />;
  if (error) return <ErrorBlock message={error} onRetry={refresh} />;
  if (!business) return <ErrorBlock message="Không có dữ liệu kinh doanh cho vai trò này." />;

  const marginBelowTarget = business.gross_margin_pct < business.gross_margin_target_pct;
  // Gán ra biến cục bộ: TS mất narrowing trên `tariff.data` bên trong callback của .map().
  const tariffData = tariff.data;

  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 gap-2 lg:grid-cols-3 xl:grid-cols-6">
        <MetricCard
          label="Doanh thu hôm nay"
          value={formatCompactVND(business.today_revenue)}
          icon={<CircleDollarSign className="h-4 w-4" aria-hidden />}
          tone="emerald"
          hint={`${business.orders_today} đơn · ${formatNumber(business.today_volume_tons, 1)} tấn`}
        />
        <MetricCard
          label="Doanh thu tháng"
          value={formatCompactVND(business.mtd_revenue)}
          icon={<Gauge className="h-4 w-4" aria-hidden />}
          tone="cyan"
          hint={`Kế hoạch ${formatCompactVND(business.target_revenue)}`}
        />
        <MetricCard
          label="Lợi nhuận gộp"
          value={formatCompactVND(business.mtd_gross_profit_vnd)}
          icon={<Layers className="h-4 w-4" aria-hidden />}
          tone={marginBelowTarget ? 'amber' : 'emerald'}
          hint={`COGS ${formatCompactVND(business.mtd_cogs_vnd)}`}
        />
        <MetricCard
          label="Biên LN gộp"
          value={formatPct(business.gross_margin_pct)}
          tone={marginBelowTarget ? 'amber' : 'emerald'}
          hint={`Mục tiêu ${formatPct(business.gross_margin_target_pct, 0)}`}
        />
        <MetricCard
          label="Chi phí điện hôm nay"
          value={formatCompactVND(business.electricity_cost_today)}
          icon={<Bolt className="h-4 w-4" aria-hidden />}
          tone="amber"
          hint="Tính theo ΔkWh × giá TOU"
        />
        <MetricCard
          label="Sản lượng"
          value={`${formatNumber(business.total_volume_tons, 1)} tấn`}
          icon={<Weight className="h-4 w-4" aria-hidden />}
          tone="sky"
          hint="Luỹ kế tháng"
        />
      </section>

      <Card className="p-3">
        <CardHeader
          title="Tiến độ kế hoạch tháng"
          icon={<Gauge className="h-4 w-4" aria-hidden />}
          tone="cyan"
          action={formatPct(business.target_progress_pct)}
        />
        <ProgressBar
          value={business.target_progress_pct}
          tone={business.target_progress_pct >= 100 ? 'emerald' : 'cyan'}
          label="Tiến độ doanh thu so với kế hoạch tháng"
          className="h-2.5"
        />
        <p className="mt-2 text-[11px] text-slate-500">
          {formatCompactVND(business.mtd_revenue)} trên kế hoạch {formatCompactVND(business.target_revenue)}.{' '}
          {marginBelowTarget
            ? `Biên LN gộp ${formatPct(business.gross_margin_pct)} đang THẤP HƠN mục tiêu ${formatPct(business.gross_margin_target_pct, 0)} — kiểm tra lại giá điện giờ cao điểm và hao hụt môi chất lạnh trong COGS.`
            : `Biên LN gộp ${formatPct(business.gross_margin_pct)} đạt mục tiêu ${formatPct(business.gross_margin_target_pct, 0)}.`}
        </p>
      </Card>

      <section className="grid gap-3 xl:grid-cols-3">
        <Card className="p-3 xl:col-span-2">
          <CardHeader title="Doanh thu & lợi nhuận gộp 30 ngày" tone="cyan" />
          <TrendChart data={business.revenue_trend_30d} />
        </Card>

        <Card className="p-3">
          <CardHeader title="Cơ cấu theo dịch vụ" icon={<PieIcon className="h-4 w-4" aria-hidden />} tone="violet" />
          <ServicePie data={business.revenue_by_service} height={200} />
          <ul className="mt-2 space-y-1">
            {business.revenue_by_service.map((item) => (
              <li key={item.service} className="flex items-center justify-between text-[11px]">
                <span className="text-slate-400">{item.service}</span>
                <span className="font-mono text-slate-300">
                  {formatCompactVND(item.revenue_vnd)} · {item.orders} đơn
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      <Card className="p-3">
        <CardHeader
          title="Đơn hàng & cấu thành COGS"
          icon={<Layers className="h-4 w-4" aria-hidden />}
          tone="emerald"
          action={orders.data ? `${orders.data.count} đơn` : undefined}
        />
        {orders.loading && !orders.data ? <LoadingBlock label="Đang nạp đơn hàng…" /> : null}
        {orders.error ? <ErrorBlock message={orders.error} onRetry={orders.refresh} /> : null}
        {orders.data ? <OrderTable orders={orders.data.items} marginTargetPct={business.gross_margin_target_pct} /> : null}
        <p className="mt-2 text-[10px] text-slate-600">
          Bấm một dòng để bung COGS: điện (theo TOU), môi chất lạnh, nhân công, bảo trì, khấu hao & quản lý.
          Biên LN gộp dưới mục tiêu sẽ hiện đỏ.
        </p>
      </Card>

      <Card className="p-3">
        <CardHeader title="Biểu giá điện EVN đang áp dụng" icon={<Bolt className="h-4 w-4" aria-hidden />} tone="amber" />
        {tariff.loading && !tariff.data ? <LoadingBlock label="Đang nạp biểu giá…" /> : null}
        {tariff.error ? <ErrorBlock message={tariff.error} onRetry={tariff.refresh} /> : null}
        {tariffData ? (
          <>
            <div className="mb-3 grid gap-2 sm:grid-cols-3">
              {TARIFF_BAND_ORDER.map((band) => (
                <div key={band} className="rounded border border-slate-800 bg-slate-950/40 p-2 text-center">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500">
                    {TARIFF_BAND_LABELS[band]}
                  </div>
                  <div className="font-mono text-sm font-bold text-slate-100">
                    {formatVND(tariffData.prices_vnd_per_kwh[band])}
                  </div>
                  <div className="text-[10px] text-slate-600">/kWh</div>
                </div>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-[11px]">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-wide text-slate-500">
                    <th className="px-2 py-1 font-medium">Khung giờ</th>
                    <th className="px-2 py-1 font-medium">Khoảng thời gian</th>
                    <th className="px-2 py-1 font-medium">Áp dụng</th>
                    <th className="px-2 py-1 text-right font-medium">Giá (₫/kWh)</th>
                    <th className="px-2 py-1 font-medium">Hiệu lực từ</th>
                  </tr>
                </thead>
                <tbody>
                  {tariffData.bands.map((band, index) => (
                    <tr key={`${band.code}-${band.start_minute}-${index}`} className="border-b border-slate-800/50">
                      <td className="px-2 py-1">
                        <Badge tone={TARIFF_BAND_TONES[band.code]}>{TARIFF_BAND_LABELS[band.code] ?? band.name_vn}</Badge>
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-300">{band.window}</td>
                      <td className="px-2 py-1 text-slate-400">{band.days === '*' ? 'Mọi ngày' : band.days}</td>
                      <td className="px-2 py-1 text-right font-mono text-slate-200">
                        {formatNumber(band.price_vnd_per_kwh, 0)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-500">{band.effective_from}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[10px] text-slate-600">{tariffData.note}</p>
          </>
        ) : null}
      </Card>
    </div>
  );
}
