import { cn } from '../../lib/cn';
import { formatCompactVND, formatDateTime } from '../../lib/format';
import { agingTone } from '../../lib/labels';
import type { OpenInvoice } from '../../types/api';
import { AgingBadge, Badge } from '../ui/Badge';
import { EmptyBlock } from '../ui/StateBlock';

export function InvoiceTable({ invoices }: { invoices: OpenInvoice[] }) {
  if (invoices.length === 0) return <EmptyBlock label="Không còn hoá đơn chưa thu" />;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-wide text-slate-500">
            <th className="px-2 py-1.5 font-medium">Hoá đơn</th>
            <th className="px-2 py-1.5 font-medium">Khách hàng</th>
            <th className="px-2 py-1.5 text-right font-medium">Giá trị</th>
            <th className="px-2 py-1.5 text-right font-medium">Đã thu</th>
            <th className="px-2 py-1.5 text-right font-medium">Còn lại</th>
            <th className="px-2 py-1.5 font-medium">Hạn thanh toán</th>
            <th className="px-2 py-1.5 font-medium">Tuổi nợ</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => {
            const overdue = invoice.overdue_days > 0;
            const paidRatio =
              invoice.amount_vnd > 0 ? Math.round((invoice.paid_amount_vnd / invoice.amount_vnd) * 100) : 0;
            return (
              <tr
                key={invoice.id}
                className={cn(
                  'border-b border-slate-800/60 transition hover:bg-slate-800/30',
                  overdue && 'bg-rose-950/10',
                )}
              >
                <td className="px-2 py-1.5 font-mono text-slate-300">{invoice.invoice_number}</td>
                <td className="px-2 py-1.5 text-slate-200">{invoice.customer}</td>
                <td className="px-2 py-1.5 text-right font-mono text-slate-300">{formatCompactVND(invoice.amount_vnd)}</td>
                <td className="px-2 py-1.5 text-right font-mono text-slate-500">
                  {formatCompactVND(invoice.paid_amount_vnd)}
                  {paidRatio > 0 ? <span className="ml-1 text-[10px] text-emerald-500">({paidRatio}%)</span> : null}
                </td>
                <td className="px-2 py-1.5 text-right font-mono font-semibold text-slate-100">
                  {formatCompactVND(invoice.outstanding_vnd)}
                </td>
                <td className="px-2 py-1.5 text-slate-400">
                  {formatDateTime(invoice.due_at)}
                  {overdue ? (
                    <span className="ml-1 font-mono text-[10px] text-rose-400">trễ {invoice.overdue_days}n</span>
                  ) : null}
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex flex-wrap items-center gap-1">
                    <AgingBadge bracket={invoice.bracket} tone={agingTone(invoice.overdue_days)} />
                    <Badge tone={invoice.status === 'PARTIAL' ? 'sky' : 'slate'}>
                      {invoice.status === 'PARTIAL' ? 'Đã thu một phần' : 'Chưa thu'}
                    </Badge>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
