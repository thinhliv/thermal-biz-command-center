import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { cn } from '../../lib/cn';
import { formatRelative } from '../../lib/format';
import { SEVERITY_ORDER, SEVERITY_TONES } from '../../lib/labels';
import { TONE_TEXT } from '../../lib/tones';
import type { AlertRow, Severity } from '../../types/api';

function severityRank(severity: Severity): number {
  const index = SEVERITY_ORDER.indexOf(severity);
  return index < 0 ? 0 : index;
}

interface AlertTickerProps {
  alerts: AlertRow[] | null;
}

/**
 * Dải cảnh báo nóng chạy ngang đầu trang. Sắp theo mức nghiêm trọng rồi tới thời điểm
 * phát sinh — CRITICAL mới nhất luôn nằm đầu, đúng thứ tự người vận hành cần đọc.
 */
export function AlertTicker({ alerts }: AlertTickerProps) {
  const open = (alerts ?? []).filter((alert) => !alert.cleared_at);
  const hasCritical = open.some((alert) => alert.severity === 'CRITICAL');

  if (open.length === 0) {
    return (
      <div className="flex items-center gap-2 border-b border-emerald-900/40 bg-emerald-950/20 px-3 py-1 text-[11px] text-emerald-400 md:px-4">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>Toàn bộ thông số trong ngưỡng an toàn</span>
      </div>
    );
  }

  const sorted = [...open].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity) || b.raised_at.localeCompare(a.raised_at),
  );

  return (
    <div
      className={cn(
        'flex items-center gap-2 overflow-x-auto border-b px-3 py-1 text-[11px] md:px-4',
        hasCritical ? 'border-rose-900/50 bg-rose-950/25' : 'border-amber-900/40 bg-amber-950/15',
      )}
      role="status"
      aria-live="polite"
    >
      <AlertTriangle
        className={cn('h-3.5 w-3.5 shrink-0', hasCritical ? 'text-rose-400' : 'text-amber-400')}
        aria-hidden
      />
      <span className="shrink-0 font-semibold text-slate-300">{open.length} cảnh báo mở</span>
      <span className="shrink-0 text-slate-700">|</span>
      {sorted.slice(0, 6).map((alert) => (
        <Link
          key={alert.id}
          to="/alerts"
          className={cn('shrink-0 whitespace-nowrap underline-offset-2 hover:underline', TONE_TEXT[SEVERITY_TONES[alert.severity]])}
        >
          {alert.equipment_code}: {alert.message} ({formatRelative(alert.raised_at)})
        </Link>
      ))}
      {sorted.length > 6 ? <span className="shrink-0 text-slate-500">+{sorted.length - 6}</span> : null}
    </div>
  );
}
