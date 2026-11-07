import { formatCompactVND, formatPct } from '../../lib/format';
import { agingTone } from '../../lib/labels';
import type { TopDebtor } from '../../types/api';
import { AgingBadge } from '../ui/Badge';
import { ProgressBar } from '../ui/ProgressBar';
import { EmptyBlock } from '../ui/StateBlock';

export function DebtorList({ debtors }: { debtors: TopDebtor[] }) {
  if (debtors.length === 0) return <EmptyBlock label="Không có khách hàng nào đang có số dư" />;

  return (
    <ul className="space-y-2.5">
      {debtors.map((debtor) => {
        const tone = agingTone(debtor.overdue_days);
        return (
          <li key={debtor.customer_id} className="rounded-lg border border-slate-800 bg-slate-950/40 p-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-xs font-semibold text-slate-100">{debtor.customer}</div>
                <div className="text-[10px] text-slate-500">
                  {debtor.invoices} hoá đơn · quá hạn {debtor.overdue_days} ngày
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="font-mono text-sm font-bold text-slate-100">{formatCompactVND(debtor.amount)}</div>
                <div className="mt-0.5 flex justify-end gap-1">
                  <AgingBadge bracket={debtor.bracket} tone={tone} />
                  {debtor.over_limit ? <AgingBadge bracket="Vượt hạn mức" tone="rose" /> : null}
                </div>
              </div>
            </div>

            <div className="mt-2">
              <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
                <span>Hạn mức {formatCompactVND(debtor.credit_limit_vnd)}</span>
                <span className="font-mono text-slate-400">{formatPct(debtor.credit_utilization_pct)}</span>
              </div>
              <ProgressBar
                value={debtor.credit_utilization_pct}
                tone={tone}
                overLimit={debtor.over_limit}
                label={`Sử dụng hạn mức của ${debtor.customer}`}
              />
              {debtor.over_limit ? (
                <div className="mt-1 text-[10px] font-semibold text-rose-400">
                  Đã vượt hạn mức tín dụng — cần chặn xuất hàng mới
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
