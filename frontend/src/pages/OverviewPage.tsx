import {
  AlertTriangle,
  ArrowDownRight,
  Bolt,
  CircleDollarSign,
  Flame,
  Gauge,
  Layers,
  Receipt,
  Snowflake,
  Wallet,
} from 'lucide-react';
import { AgingBar } from '../components/charts/AgingBar';
import { BandChart } from '../components/charts/BandChart';
import { TrendChart } from '../components/charts/TrendChart';
import { RecentOrders } from '../components/business/RecentOrders';
import { Card, CardHeader } from '../components/ui/Card';
import { MetricCard } from '../components/ui/MetricCard';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ErrorBlock, LoadingBlock } from '../components/ui/StateBlock';
import {
  formatCompactVND,
  formatNumber,
  formatPct,
  formatSignedPct,
  formatVND,
} from '../lib/format';
import { useAuth } from '../store/auth';
import { useDashboard } from '../store/dashboard';

/**
 * Trang Tổng quan cố tình ghép Nhiệt cạnh Kinh doanh: đây là điểm mà hai thế giới gặp
 * nhau — COP sụt làm chi phí điện tăng, và chi phí điện ăn thẳng vào biên lợi nhuận.
 * Mỗi khối chỉ hiện khi vai trò có scope tương ứng (backend cũng đã cắt section rồi).
 */
export function OverviewPage() {
  const { has } = useAuth();
  const { thermal, alerts, business, debts, energy, loadShift, loading, error, refresh } = useDashboard();

  if (loading) return <LoadingBlock label="Đang nạp bảng điều hành…" />;
  if (error) return <ErrorBlock message={error} onRetry={refresh} />;

  const openAlerts = (alerts ?? []).filter((alert) => !alert.cleared_at);
  const criticalCount = openAlerts.filter((alert) => alert.severity === 'CRITICAL').length;
  const haccpCount = openAlerts.filter((alert) => alert.is_haccp).length;

  return (
    <div className="space-y-3">
      {has('thermal') || has('alerts') ? (
        <section aria-label="Kỹ thuật nhiệt" className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <MetricCard
            label="Tổng công suất"
            value={`${formatNumber(thermal?.total_power_kw, 0)} kW`}
            icon={<Bolt className="h-4 w-4" aria-hidden />}
            tone="cyan"
            hint={`${thermal?.running ?? 0}/${thermal?.total_units ?? 0} thiết bị đang chạy`}
          />
          <MetricCard
            label="COP trung bình"
            value={formatNumber(thermal?.avg_cop, 2)}
            icon={<Snowflake className="h-4 w-4" aria-hidden />}
            tone="sky"
            hint="COP = Q_o / N_e của cụm lạnh"
          />
          <MetricCard
            label="η lò hơi TB"
            value={formatPct(thermal?.avg_boiler_efficiency_pct)}
            icon={<Flame className="h-4 w-4" aria-hidden />}
            tone="amber"
            hint="Hiệu suất cháy — khác đại lượng với COP"
          />
          <MetricCard
            label="Cảnh báo mở"
            value={String(openAlerts.length)}
            icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
            tone={criticalCount > 0 ? 'rose' : haccpCount > 0 ? 'amber' : 'emerald'}
            hint={`${criticalCount} nghiêm trọng · ${haccpCount} HACCP`}
          />
        </section>
      ) : null}

      {has('business') || has('debts') ? (
        <section aria-label="Kinh doanh và công nợ" className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {has('business') ? (
            <>
              <MetricCard
                label="Doanh thu hôm nay"
                value={formatCompactVND(business?.today_revenue)}
                icon={<CircleDollarSign className="h-4 w-4" aria-hidden />}
                tone="emerald"
                hint={`${business?.orders_today ?? 0} đơn · ${formatNumber(business?.today_volume_tons, 1)} tấn`}
              />
              <MetricCard
                label="Doanh thu tháng"
                value={formatCompactVND(business?.mtd_revenue)}
                icon={<Gauge className="h-4 w-4" aria-hidden />}
                tone="cyan"
                hint={`${formatPct(business?.target_progress_pct)} kế hoạch ${formatCompactVND(business?.target_revenue)}`}
              />
              <MetricCard
                label="Biên LN gộp"
                value={formatPct(business?.gross_margin_pct)}
                icon={<Layers className="h-4 w-4" aria-hidden />}
                tone={
                  business && business.gross_margin_pct < business.gross_margin_target_pct ? 'amber' : 'emerald'
                }
                hint={`Mục tiêu ${formatPct(business?.gross_margin_target_pct, 0)} · LN ${formatCompactVND(business?.mtd_gross_profit_vnd)}`}
              />
            </>
          ) : null}
          {has('debts') ? (
            <MetricCard
              label="Quá hạn / Phải thu"
              value={formatCompactVND(debts?.overdue_debt)}
              icon={<Receipt className="h-4 w-4" aria-hidden />}
              tone={debts && debts.overdue_pct > 30 ? 'rose' : 'amber'}
              hint={`Tổng phải thu ${formatCompactVND(debts?.total_receivables)} · ${formatPct(debts?.overdue_pct)} quá hạn`}
            />
          ) : null}
        </section>
      ) : null}

      {has('business') && business ? (
        <section className="grid gap-3 xl:grid-cols-3">
          <Card className="p-3 xl:col-span-2">
            <CardHeader
              title="Doanh thu & lợi nhuận gộp 30 ngày"
              icon={<Gauge className="h-4 w-4" aria-hidden />}
              tone="cyan"
              action={`MTD ${formatCompactVND(business.mtd_revenue)}`}
            />
            <TrendChart data={business.revenue_trend_30d} />
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between text-[11px] text-slate-400">
                <span>Tiến độ kế hoạch tháng</span>
                <span className="font-mono">{formatPct(business.target_progress_pct)}</span>
              </div>
              <ProgressBar
                value={business.target_progress_pct}
                tone={business.target_progress_pct >= 100 ? 'emerald' : 'cyan'}
                label="Tiến độ kế hoạch doanh thu tháng"
              />
            </div>
          </Card>

          <Card className="p-3">
            <CardHeader title="Đơn gần đây" icon={<Layers className="h-4 w-4" aria-hidden />} tone="violet" />
            <RecentOrders orders={business.recent_orders} marginTargetPct={business.gross_margin_target_pct} />
          </Card>
        </section>
      ) : null}

      <section className="grid gap-3 lg:grid-cols-2">
        {has('business') && energy ? (
          <Card className="p-3">
            <CardHeader
              title="Điện theo khung giờ TOU"
              icon={<Bolt className="h-4 w-4" aria-hidden />}
              tone="amber"
              action={`${formatNumber(energy.total_kwh, 0)} kWh · ${formatCompactVND(energy.total_cost_vnd)}`}
            />
            <BandChart kwhByBand={energy.kwh_by_band} prices={energy.prices_vnd_per_kwh} height={190} />
            {loadShift ? (
              <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-slate-950/50 p-1.5">
                  <div className="text-[10px] text-slate-500">Đã dịch chuyển</div>
                  <div className="font-mono text-xs font-bold text-emerald-400">
                    {formatNumber(loadShift.shifted_kwh, 0)} kWh
                  </div>
                </div>
                <div className="rounded bg-slate-950/50 p-1.5">
                  <div className="text-[10px] text-slate-500">Tiết kiệm</div>
                  <div className="font-mono text-xs font-bold text-emerald-400">
                    {formatCompactVND(loadShift.saving_vnd)}
                  </div>
                </div>
                <div className="rounded bg-slate-950/50 p-1.5">
                  <div className="text-[10px] text-slate-500">Chênh cao/thấp điểm</div>
                  <div className="font-mono text-xs font-bold text-slate-300">
                    {formatVND(loadShift.price_gap_vnd_per_kwh)}
                  </div>
                </div>
              </div>
            ) : null}
          </Card>
        ) : null}

        {has('debts') && debts ? (
          <Card className="p-3">
            <CardHeader
              title="Tuổi nợ phải thu"
              icon={<Wallet className="h-4 w-4" aria-hidden />}
              tone="rose"
              action={`${debts.open_invoice_count} hoá đơn mở`}
            />
            <AgingBar data={debts.aging_breakdown} height={190} />
            <ul className="mt-2 space-y-1">
              {debts.aging_breakdown.map((bucket) => (
                <li key={bucket.bracket} className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">{bucket.bracket}</span>
                  <span className="font-mono text-slate-300">{formatCompactVND(bucket.amount)}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </section>

      {has('business') && loadShift ? (
        <Card className="p-3">
          <CardHeader
            title="Hiệu quả dịch chuyển tải"
            icon={<ArrowDownRight className="h-4 w-4" aria-hidden />}
            tone="emerald"
            action={`${formatSignedPct(loadShift.saving_pct)} chi phí điện`}
          />
          <p className="text-xs text-slate-400">
            Đã chuyển <span className="font-mono text-emerald-400">{formatNumber(loadShift.shifted_kwh, 1)} kWh</span>{' '}
            ({formatPct(loadShift.shift_pct, 0)} sản lượng) từ giờ cao điểm{' '}
            <span className="font-mono text-rose-400">{formatVND(loadShift.peak_price_vnd_per_kwh)}</span> xuống giờ
            thấp điểm <span className="font-mono text-emerald-400">{formatVND(loadShift.off_peak_price_vnd_per_kwh)}</span>
            , tiết kiệm <span className="font-mono text-emerald-400">{formatVND(loadShift.saving_vnd)}</span> so với
            đường cơ sở {formatVND(loadShift.baseline_electricity_vnd)}.
          </p>
        </Card>
      ) : null}
    </div>
  );
}
