import { cn } from '../../lib/cn';
import { formatCompactVND, formatNumber, formatPct, formatRelative } from '../../lib/format';
import { OrderStatusBadge } from '../ui/Badge';
import { EmptyBlock } from '../ui/StateBlock';
import type { RecentOrder } from '../../types/api';

interface RecentOrdersProps {
  orders: RecentOrder[];
  marginTargetPct?: number;
}

/** Danh sách gọn cho trang Tổng quan — bản đầy đủ có COGS nằm ở trang Kinh doanh. */
export function RecentOrders({ orders, marginTargetPct }: RecentOrdersProps) {
  if (orders.length === 0) return <EmptyBlock label="Chưa có đơn hàng nào" />;

  return (
    <ul className="divide-y divide-slate-800/70">
      {orders.map((order) => {
        const belowTarget = marginTargetPct !== undefined && order.margin < marginTargetPct;
        return (
          <li key={order.order_code} className="flex items-center justify-between gap-2 py-1.5">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[11px] text-slate-400">{order.order_code}</span>
                <OrderStatusBadge status={order.status} />
              </div>
              <div className="truncate text-xs text-slate-200">{order.customer}</div>
              <div className="truncate text-[10px] text-slate-500">
                {order.service} · {formatNumber(order.volume_tons, 2)} tấn · {formatRelative(order.started_at)}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-mono text-xs font-semibold text-slate-100">{formatCompactVND(order.amount)}</div>
              <div className={cn('font-mono text-[10px]', belowTarget ? 'text-rose-400' : 'text-emerald-400')}>
                {formatPct(order.margin)}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
