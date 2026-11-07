import { useCallback, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { AlertList } from '../components/alerts/AlertList';
import { Card, CardHeader } from '../components/ui/Card';
import { MetricCard } from '../components/ui/MetricCard';
import { ErrorBlock, LoadingBlock } from '../components/ui/StateBlock';
import { useApi } from '../hooks/useApi';
import { apiPost, ApiError } from '../lib/api';
import { cn } from '../lib/cn';
import { SEVERITY_LABELS, SEVERITY_ORDER } from '../lib/labels';
import { useAuth } from '../store/auth';
import type { AlertRow, AlertStats, Severity } from '../types/api';

type State = 'open' | 'cleared' | 'all';

const STATES: Array<{ key: State; label: string }> = [
  { key: 'open', label: 'Đang mở' },
  { key: 'cleared', label: 'Đã xử lý' },
  { key: 'all', label: 'Tất cả' },
];

const LIMIT = 100;

export function AlertsPage() {
  const { has } = useAuth();
  const [state, setState] = useState<State>('open');
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [haccpOnly, setHaccpOnly] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const params = new URLSearchParams({ state, limit: String(LIMIT) });
  if (severity) params.set('severity', severity);
  if (haccpOnly) params.set('haccp_only', 'true');
  const path = `/api/alerts?${params.toString()}`;

  const list = useApi<AlertRow[]>(path);
  const stats = useApi<AlertStats>('/api/alerts/stats');

  const canMutate = has('alerts');

  const run = useCallback(
    async (alert: AlertRow, action: 'acknowledge' | 'clear') => {
      setBusyId(alert.id);
      setActionError(null);
      try {
        await apiPost<AlertRow>(`/api/alerts/${alert.id}/${action}`, action === 'acknowledge' ? {} : undefined);
        list.refresh();
        stats.refresh();
      } catch (caught) {
        // 409 nghĩa là người khác đã xử lý trước — báo rõ thay vì âm thầm bỏ qua.
        setActionError(caught instanceof ApiError ? caught.message : 'Không thực hiện được thao tác.');
        list.refresh();
      } finally {
        setBusyId(null);
      }
    },
    [list, stats],
  );

  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <MetricCard
          label="Cảnh báo đang mở"
          value={String(stats.data?.open_total ?? 0)}
          icon={<ShieldAlert className="h-4 w-4" aria-hidden />}
          tone={(stats.data?.open_total ?? 0) > 0 ? 'amber' : 'emerald'}
          hint={`Chưa xác nhận: ${stats.data?.unacknowledged_open ?? 0}`}
        />
        <MetricCard
          label="Nghiêm trọng"
          value={String(stats.data?.open_by_severity.CRITICAL ?? 0)}
          tone={(stats.data?.open_by_severity.CRITICAL ?? 0) > 0 ? 'rose' : 'emerald'}
          hint={`Nặng: ${stats.data?.open_by_severity.MAJOR ?? 0}`}
        />
        <MetricCard
          label="Vi phạm HACCP"
          value={String(stats.data?.haccp_open ?? 0)}
          tone={(stats.data?.haccp_open ?? 0) > 0 ? 'rose' : 'emerald'}
          hint="Thuỷ sản phải ≤ −18 °C"
        />
        <MetricCard
          label="Cảnh báo / Thông tin"
          value={`${stats.data?.open_by_severity.WARNING ?? 0} / ${stats.data?.open_by_severity.INFO ?? 0}`}
          tone="sky"
          hint="Đang mở theo mức"
        />
      </section>

      <Card className="p-3">
        <CardHeader
          title="Nhật ký cảnh báo"
          icon={<ShieldAlert className="h-4 w-4" aria-hidden />}
          tone="amber"
          action={`${list.data?.length ?? 0} dòng (tối đa ${LIMIT})`}
        />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {STATES.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setState(item.key)}
                aria-pressed={state === item.key}
                className={cn(
                  'rounded px-2 py-1 text-[11px] transition',
                  state === item.key
                    ? 'bg-cyan-500/15 text-cyan-300'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-1">
            {SEVERITY_ORDER.map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setSeverity(severity === level ? null : level)}
                aria-pressed={severity === level}
                className={cn(
                  'rounded border px-2 py-1 text-[11px] transition',
                  severity === level
                    ? 'border-cyan-600 bg-cyan-500/10 text-cyan-300'
                    : 'border-slate-800 text-slate-400 hover:border-slate-600 hover:text-slate-200',
                )}
              >
                {SEVERITY_LABELS[level]}
              </button>
            ))}
          </div>

          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-400">
            <input
              type="checkbox"
              checked={haccpOnly}
              onChange={(event) => setHaccpOnly(event.target.checked)}
              className="h-3 w-3 accent-rose-500"
            />
            Chỉ HACCP
          </label>
        </div>

        {actionError ? (
          <p role="alert" className="mb-2 rounded border border-amber-800 bg-amber-950/40 px-2 py-1.5 text-[11px] text-amber-300">
            {actionError}
          </p>
        ) : null}

        {list.loading && !list.data ? <LoadingBlock label="Đang nạp cảnh báo…" /> : null}
        {list.error ? <ErrorBlock message={list.error} onRetry={list.refresh} /> : null}
        {list.data ? (
          <AlertList
            alerts={list.data}
            canMutate={canMutate}
            busyId={busyId}
            onAcknowledge={(alert) => void run(alert, 'acknowledge')}
            onClear={(alert) => void run(alert, 'clear')}
          />
        ) : null}
      </Card>
    </div>
  );
}
