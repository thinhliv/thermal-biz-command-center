import { useMemo, useState } from 'react';
import { AlertTriangle, Flame, Snowflake, Thermometer } from 'lucide-react';
import { SeriesChart } from '../components/charts/SeriesChart';
import { EquipmentCard } from '../components/thermal/EquipmentCard';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader } from '../components/ui/Card';
import { MetricCard } from '../components/ui/MetricCard';
import { ErrorBlock, LoadingBlock } from '../components/ui/StateBlock';
import { useApi } from '../hooks/useApi';
import { cn } from '../lib/cn';
import { formatNumber, formatPct, formatTemp } from '../lib/format';
import { METRIC_LABELS } from '../lib/labels';
import { useDashboard } from '../store/dashboard';
import type { AlarmRule, Comparator, SeriesResponse } from '../types/api';

type Filter = 'all' | 'cold' | 'heat' | 'issue';

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: 'Tất cả' },
  { key: 'cold', label: 'Hệ lạnh' },
  { key: 'heat', label: 'Lò hơi' },
  { key: 'issue', label: 'Có vấn đề' },
];

const COMPARATOR_LABELS: Record<Comparator, string> = {
  LT: '<',
  LTE: '≤',
  GT: '>',
  GTE: '≥',
};

export function ThermalPage() {
  const { thermal, loading, error, refresh } = useDashboard();
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<string | null>(null);

  const rows = thermal?.telemetry ?? [];
  const issues = useMemo(
    () =>
      rows.filter(
        (row) => row.haccp_breach || row.vibration_critical || row.status === 'FAULT' || (row.cop_gap_pct ?? 0) < -10,
      ),
    [rows],
  );

  const visible = useMemo(() => {
    if (filter === 'cold') return rows.filter((row) => row.is_refrigeration);
    if (filter === 'heat') return rows.filter((row) => row.is_combustion);
    if (filter === 'issue') {
      const codes = new Set(issues.map((row) => row.equipment_code));
      return rows.filter((row) => codes.has(row.equipment_code));
    }
    return rows;
  }, [rows, filter, issues]);

  // Chuỗi 24h chỉ nạp cho thiết bị đang chọn; selected = null thì useApi tự tắt.
  const seriesPath = selected ? `/api/thermal/${encodeURIComponent(selected)}/series?hours=24` : null;
  const series = useApi<SeriesResponse>(seriesPath);
  const rules = useApi<AlarmRule[]>('/api/thermal/rules');

  const selectedRow = rows.find((row) => row.equipment_code === selected) ?? null;

  if (loading) return <LoadingBlock label="Đang nạp dữ liệu nhiệt…" />;
  if (error) return <ErrorBlock message={error} onRetry={refresh} />;

  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <MetricCard
          label="Tổng công suất"
          value={`${formatNumber(thermal?.total_power_kw, 0)} kW`}
          icon={<Thermometer className="h-4 w-4" aria-hidden />}
          tone="cyan"
          hint={`${thermal?.running ?? 0} chạy · ${thermal?.warning ?? 0} cảnh báo · ${thermal?.fault ?? 0} lỗi`}
        />
        <MetricCard
          label="COP trung bình"
          value={formatNumber(thermal?.avg_cop, 2)}
          icon={<Snowflake className="h-4 w-4" aria-hidden />}
          tone="sky"
          hint="COP thấp kéo dài = thiếu gas hoặc giàn nóng bẩn"
        />
        <MetricCard
          label="η lò hơi trung bình"
          value={formatPct(thermal?.avg_boiler_efficiency_pct)}
          icon={<Flame className="h-4 w-4" aria-hidden />}
          tone="amber"
          hint="Hiệu suất cháy, không phải COP"
        />
        <MetricCard
          label="Thiết bị có vấn đề"
          value={String(issues.length)}
          icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
          tone={issues.length > 0 ? 'rose' : 'emerald'}
          hint={`Ngưỡng rung ${formatNumber(thermal?.vibration_limit_mm_s, 1)} mm/s · HACCP ${formatTemp(thermal?.haccp_seafood_limit_c)}`}
        />
      </section>

      <Card className="p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setFilter(item.key)}
                aria-pressed={filter === item.key}
                className={cn(
                  'rounded px-2 py-1 text-[11px] transition',
                  filter === item.key
                    ? 'bg-cyan-500/15 text-cyan-300'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
                )}
              >
                {item.label}
                {item.key === 'issue' && issues.length > 0 ? (
                  <span className="ml-1 rounded bg-rose-500/20 px-1 font-mono text-rose-300">{issues.length}</span>
                ) : null}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-slate-500">
            {visible.length}/{rows.length} thiết bị · chọn một thẻ để xem chuỗi 24 giờ
          </span>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {visible.map((row) => (
            <EquipmentCard key={row.equipment_code} row={row} selected={row.equipment_code === selected} onSelect={setSelected} />
          ))}
        </div>
        {visible.length === 0 ? (
          <p className="py-6 text-center text-xs text-slate-500">Không có thiết bị nào trong bộ lọc này.</p>
        ) : null}
      </Card>

      {selected ? (
        <Card className="p-3">
          <CardHeader
            title={`${selectedRow?.equipment_name ?? selected} — chuỗi 24 giờ`}
            icon={<Thermometer className="h-4 w-4" aria-hidden />}
            tone="sky"
            action={
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-[11px] text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline"
              >
                Bỏ chọn
              </button>
            }
          />
          {series.loading ? <LoadingBlock label="Đang nạp chuỗi đo…" /> : null}
          {series.error ? <ErrorBlock message={series.error} onRetry={series.refresh} /> : null}
          {!series.loading && !series.error ? <SeriesChart series={series.data} /> : null}
          <p className="mt-2 text-[10px] text-slate-600">
            Đường đứt đỏ là giới hạn HACCP (thuỷ sản ≤ −18 °C), xanh dương là setpoint, xanh lá là COP/η thiết kế.
            Vượt HACCP là sự cố an toàn thực phẩm, không chỉ là lệch thông số.
          </p>
        </Card>
      ) : null}

      <Card className="p-3">
        <CardHeader title="Ngưỡng cảnh báo đang áp dụng" icon={<AlertTriangle className="h-4 w-4" aria-hidden />} tone="amber" />
        {rules.loading ? <LoadingBlock label="Đang nạp danh sách ngưỡng…" /> : null}
        {rules.error ? <ErrorBlock message={rules.error} onRetry={rules.refresh} /> : null}
        {rules.data ? (
          <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {rules.data.map((rule) => (
              <li key={rule.id} className="rounded border border-slate-800 bg-slate-950/40 px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] text-slate-300">
                    {METRIC_LABELS[rule.metric] ?? rule.metric}{' '}
                    <span className="font-mono text-slate-400">
                      {COMPARATOR_LABELS[rule.comparator] ?? rule.comparator} {formatNumber(rule.threshold, 2)}
                    </span>
                  </span>
                  <Badge tone={rule.severity === 'CRITICAL' ? 'rose' : rule.severity === 'MAJOR' ? 'amber' : 'sky'}>
                    {rule.severity}
                  </Badge>
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-slate-600">
                  {rule.applies_to_kind ?? rule.equipment_id ?? 'mọi thiết bị'}
                  {rule.duration_minutes > 0 ? ` · kéo dài ${rule.duration_minutes} phút` : ''}
                  {rule.is_haccp ? ' · HACCP' : ''}
                  {rule.enabled ? '' : ' · TẮT'}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}
