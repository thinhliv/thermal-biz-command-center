import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/cn';
import { formatCompactVND, formatDateTime, formatNumber, formatPct } from '../../lib/format';
import { OrderStatusBadge } from '../ui/Badge';
import { EmptyBlock } from '../ui/StateBlock';
import type { OrderDetail } from '../../types/api';

/** Thứ tự cố định: không phụ thuộc key JSON để bảng luôn đọc được theo cùng một cách. */
const COGS_ROWS: Array<{ key: keyof OrderDetail['cogs_breakdown']; label: string }> = [
  { key: 'electricity_vnd', label: 'Điện (TOU)' },
  { key: 'refrigerant_vnd', label: 'Môi chất lạnh' },
  { key: 'labor_vnd', label: 'Nhân công' },
  { key: 'maintenance_vnd', label: 'Bảo trì' },
  { key: 'overhead_vnd', label: 'Khấu hao & QL' },
];

interface OrderTableProps {
  orders: OrderDetail[];
  marginTargetPct?: number;
}

export function OrderTable({ orders, marginTargetPct }: OrderTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (orders.length === 0) return <EmptyBlock label="Chưa có đơn hàng" />;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-wide text-slate-500">
            <th className="px-2 py-1.5 font-medium">Đơn</th>
            <th className="px-2 py-1.5 font-medium">Khách hàng</th>
            <th className="px-2 py-1.5 font-medium">Dịch vụ</th>
            <th className="px-2 py-1.5 text-right font-medium">Tấn</th>
            <th className="px-2 py-1.5 text-right font-medium">Doanh thu</th>
            <th className="px-2 py-1.5 text-right font-medium">COGS</th>
            <th className="px-2 py-1.5 text-right font-medium">LN gộp</th>
            <th className="px-2 py-1.5 text-right font-medium">Biên</th>
            <th className="px-2 py-1.5 font-medium">Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const open = expanded === order.order_code;
            const belowTarget = marginTargetPct !== undefined && order.margin_pct < marginTargetPct;
            return (
              <Fragment key={order.order_code}>
                <tr
                  className={cn(
                    'cursor-pointer border-b border-slate-800/60 transition hover:bg-slate-800/30',
                    open && 'bg-slate-800/30',
                  )}
                  onClick={() => setExpanded(open ? null : order.order_code)}
                >
                  <td className="px-2 py-1.5">
                    <span className="inline-flex items-center gap-1 font-mono text-slate-300">
                      {open ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3" aria-hidden />}
                      {order.order_code}
                    </span>
                    <div className="ml-4 text-[10px] text-slate-600">{formatDateTime(order.started_at)}</div>
                  </td>
                  <td className="px-2 py-1.5 text-slate-300">{order.customer}</td>
                  <td className="px-2 py-1.5 text-slate-400">{order.service}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-300">{formatNumber(order.volume_tons, 2)}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-200">{formatCompactVND(order.revenue_vnd)}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-400">{formatCompactVND(order.cogs_vnd)}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-emerald-400">{formatCompactVND(order.gross_profit_vnd)}</td>
                  <td
                    className={cn(
                      'px-2 py-1.5 text-right font-mono font-semibold',
                      belowTarget ? 'text-rose-400' : 'text-slate-200',
                    )}
                  >
                    {formatPct(order.margin_pct)}
                  </td>
                  <td className="px-2 py-1.5">
                    <OrderStatusBadge status={order.status} />
                  </td>
                </tr>
                {open ? (
                  <tr className="border-b border-slate-800/60 bg-slate-950/40">
                    <td colSpan={9} className="px-3 py-2">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3 lg:grid-cols-5">
                        {COGS_ROWS.map(({ key, label }) => (
                          <div key={key} className="flex items-center justify-between gap-2">
                            <span className="text-[10px] text-slate-500">{label}</span>
                            <span className="font-mono text-[11px] text-slate-300">
                              {formatCompactVND(order.cogs_breakdown[key])}
                            </span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
