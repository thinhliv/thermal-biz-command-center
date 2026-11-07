import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Gauge, Receipt, ShieldAlert, Snowflake, TrendingUp, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';
import { allowedRoutes, type RouteIcon } from '../../lib/scopes';
import { useAuth } from '../../store/auth';

const ICONS: Record<RouteIcon, LucideIcon> = {
  gauge: Gauge,
  snowflake: Snowflake,
  'shield-alert': ShieldAlert,
  'trending-up': TrendingUp,
  receipt: Receipt,
};

/**
 * Chỉ hiện mục mà vai trò có scope tương ứng. Backend đã cắt section theo vai trò nên
 * nếu hiện cả thì trang sẽ rỗng — ẩn hẳn ở đây là đúng và nhất quán hai đầu.
 */
export function NavBar() {
  const { user } = useAuth();
  const location = useLocation();
  const routes = allowedRoutes(user?.scopes);

  return (
    <nav
      aria-label="Điều hướng chính"
      className="flex gap-1 overflow-x-auto border-b border-slate-800 bg-[#0d1220] px-2 py-1.5 md:px-4"
    >
      {routes.map((route) => {
        const Icon = ICONS[route.icon];
        const active = location.pathname.startsWith(route.path);
        return (
          <Link
            key={route.path}
            to={route.path}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-medium transition',
              active
                ? 'bg-cyan-500/15 text-cyan-300'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            <span className="whitespace-nowrap">{route.short}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/** Đồng hồ chạy thật, dùng cho TV kiosk — cập nhật mỗi giây. */
export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <span className="font-mono text-xs text-slate-300 tabular-nums">
      {now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
    </span>
  );
}
