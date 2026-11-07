import { Check, ShieldAlert, X } from 'lucide-react';
import { cn } from '../../lib/cn';
import { formatDateTime, formatNumber, formatRelative } from '../../lib/format';
import { METRIC_LABELS, SEVERITY_TONES } from '../../lib/labels';
import { TONE_BORDER, TONE_TEXT } from '../../lib/tones';
import type { AlertRow } from '../../types/api';
import { SeverityBadge } from '../ui/Badge';
import { EmptyBlock } from '../ui/StateBlock';

interface AlertListProps {
  alerts: AlertRow[];
  /** Chỉ BGĐ và Vận hành được phép xác nhận/xoá cảnh báo. */
  canMutate: boolean;
  busyId: number | null;
  onAcknowledge: (alert: AlertRow) => void;
  onClear: (alert: AlertRow) => void;
}

export function AlertList({ alerts, canMutate, busyId, onAcknowledge, onClear }: AlertListProps) {
  if (alerts.length === 0) {
    return <EmptyBlock label="Không có cảnh báo nào trong bộ lọc này" />;
  }

  return (
    <ul className="space-y-2">
      {alerts.map((alert) => {
        const tone = SEVERITY_TONES[alert.severity];
        const closed = Boolean(alert.cleared_at);
        const busy = busyId === alert.id;
        return (
          <li
            key={alert.id}
            className={cn(
              'rounded-lg border bg-[#111827] p-3',
              closed ? 'border-slate-800 opacity-60' : TONE_BORDER[tone],
            )}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 items-start gap-2">
                <ShieldAlert className={cn('mt-0.5 h-4 w-4 shrink-0', TONE_TEXT[tone])} aria-hidden />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <SeverityBadge severity={alert.severity} />
                    {alert.is_haccp ? (
                      <span className="rounded border border-rose-700 bg-rose-950/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-rose-300">
                        HACCP
                      </span>
                    ) : null}
                    <span className="font-mono text-[10px] text-slate-500">{alert.equipment_code}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-200">{alert.message}</p>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    {METRIC_LABELS[alert.metric] ?? alert.metric}: đo được{' '}
                    <span className="font-mono text-slate-400">{formatNumber(alert.observed_value, 2)}</span> · ngưỡng{' '}
                    <span className="font-mono text-slate-400">{formatNumber(alert.threshold, 2)}</span>
                  </p>
                  <p className="mt-0.5 text-[10px] text-slate-500" title={formatDateTime(alert.raised_at)}>
                    Phát sinh {formatRelative(alert.raised_at)}
                    {alert.acknowledged_at ? ` · đã xác nhận bởi ${alert.acknowledged_by ?? '?'}` : ''}
                    {alert.cleared_at ? ` · đã xử lý ${formatRelative(alert.cleared_at)}` : ''}
                  </p>
                </div>
              </div>

              {canMutate && !closed ? (
                <div className="flex shrink-0 gap-1">
                  {!alert.acknowledged_at ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onAcknowledge(alert)}
                      className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition hover:border-cyan-600 hover:text-cyan-300 disabled:opacity-50"
                    >
                      <Check className="h-3 w-3" aria-hidden />
                      Xác nhận
                    </button>
                  ) : null}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onClear(alert)}
                    className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition hover:border-rose-600 hover:text-rose-300 disabled:opacity-50"
                  >
                    <X className="h-3 w-3" aria-hidden />
                    Đã xử lý
                  </button>
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
