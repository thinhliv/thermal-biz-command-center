import { useState } from 'react';
import {
  Clock as ClockIcon,
  LogOut,
  Maximize2,
  Minimize2,
  Radio,
  RefreshCw,
  UserCog,
  WifiOff,
} from 'lucide-react';
import { cn } from '../../lib/cn';
import { ROLE_LABELS } from '../../lib/scopes';
import { useFullscreen } from '../../hooks/useFullscreen';
import type { SocketStatus } from '../../hooks/useTelemetrySocket';
import { useAuth } from '../../store/auth';
import { useDashboard } from '../../store/dashboard';
import { Clock } from './NavBar';

const LIVE_META: Record<SocketStatus, { label: string; className: string }> = {
  open: { label: 'LIVE', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' },
  connecting: { label: 'Đang kết nối', className: 'border-sky-500/40 bg-sky-500/10 text-sky-400' },
  reconnecting: { label: 'Mất kết nối', className: 'border-amber-500/40 bg-amber-500/10 text-amber-400' },
  disabled: { label: 'Không realtime', className: 'border-slate-700 bg-slate-800/40 text-slate-400' },
};

// Kênh mở không đồng nghĩa số liệu mới: nguồn Modbus/MQTT có thể ngừng gửi trong khi
// WebSocket vẫn sống. Quá ngưỡng này thì màn hình không được tự nhận là LIVE nữa.
const STALE_AFTER_MINUTES = 5;

const STALE_META = {
  label: 'Dữ liệu cũ',
  className: 'border-amber-500/40 bg-amber-500/10 text-amber-400',
};

// TV kiosk không có con trỏ nên không đọc được tooltip: số tuổi phải nằm ngay trên nhãn.
function describeAge(minutes: number): string {
  return minutes < 60 ? `${minutes} phút` : `${Math.round(minutes / 60)} giờ`;
}

interface LiveBadgeProps {
  status: SocketStatus;
  ageMinutes: number | null;
}

export function LiveBadge({ status, ageMinutes }: LiveBadgeProps) {
  // Chỉ kênh đang mở mới dám khẳng định dữ liệu cũ; các trạng thái khác đã tự nói lên sự cố.
  const staleAge =
    status === 'open' && ageMinutes != null && ageMinutes > STALE_AFTER_MINUTES ? ageMinutes : null;
  const meta = staleAge != null ? STALE_META : LIVE_META[status];
  const Icon = staleAge != null ? ClockIcon : status === 'open' ? Radio : status === 'disabled' ? WifiOff : RefreshCw;
  const title =
    staleAge != null
      ? `Kênh realtime vẫn mở nhưng phép đo mới nhất đã ${describeAge(staleAge)} trước — nguồn số liệu có thể đã ngừng gửi.`
      : 'WebSocket /ws/telemetry';
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
        meta.className,
      )}
      title={title}
    >
      <Icon className={cn('h-3 w-3', staleAge == null && status === 'open' && 'animate-pulse')} aria-hidden />
      {meta.label}
      {staleAge != null ? ` · ${describeAge(staleAge)}` : null}
    </span>
  );
}

interface TopBarProps {
  onChangePassword: () => void;
}

export function TopBar({ onChangePassword }: TopBarProps) {
  const { user, logout } = useAuth();
  const { socketStatus, dataAgeMinutes, refresh } = useDashboard();
  const { active, toggle } = useFullscreen();
  const [menuOpen, setMenuOpen] = useState(false);

  const roleLabel = user ? ROLE_LABELS[user.role] : '';

  return (
    <header className="flex items-center justify-between gap-3 border-b border-slate-800 bg-[#0b0f19] px-3 py-2 md:px-4">
      <div className="flex min-w-0 items-center gap-2">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded bg-gradient-to-br from-cyan-500/30 to-violet-500/30 text-cyan-300">
          <Radio className="h-4 w-4" aria-hidden />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-sm font-bold leading-tight text-slate-100 md:text-base">
            Trung tâm Nhiệt &amp; Kinh doanh
          </h1>
          <p className="truncate text-[10px] leading-tight text-slate-500">
            Giám sát COP · HACCP · EVN TOU · Công nợ
          </p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <LiveBadge status={socketStatus} ageMinutes={dataAgeMinutes} />
        <div className="hidden sm:block">
          <Clock />
        </div>

        <button
          type="button"
          onClick={refresh}
          className="rounded border border-slate-800 p-1.5 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
          title="Làm mới dữ liệu"
          aria-label="Làm mới dữ liệu"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          onClick={toggle}
          className="rounded border border-slate-800 p-1.5 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
          title={active ? 'Thoát toàn màn hình' : 'Toàn màn hình (TV kiosk)'}
          aria-label={active ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
        >
          {active ? <Minimize2 className="h-3.5 w-3.5" aria-hidden /> : <Maximize2 className="h-3.5 w-3.5" aria-hidden />}
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            className="flex items-center gap-1.5 rounded border border-slate-800 px-2 py-1 text-xs text-slate-300 transition hover:border-slate-600"
          >
            <UserCog className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden max-w-[8rem] truncate sm:block">{user?.full_name}</span>
          </button>

          {menuOpen ? (
            <>
              <button
                type="button"
                aria-label="Đóng menu người dùng"
                className="fixed inset-0 z-10 cursor-default"
                onClick={() => setMenuOpen(false)}
              />
              <div className="absolute right-0 z-20 mt-1 w-52 rounded-lg border border-slate-700 bg-[#0f172a] p-1.5 shadow-xl">
                <div className="px-2 py-1.5">
                  <div className="truncate text-xs font-semibold text-slate-200">{user?.full_name}</div>
                  <div className="text-[10px] uppercase tracking-wide text-cyan-400">{roleLabel}</div>
                </div>
                <div className="my-1 border-t border-slate-800" />
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    onChangePassword();
                  }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-slate-800"
                >
                  <UserCog className="h-3.5 w-3.5" aria-hidden />
                  Đổi mật khẩu
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                  }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-rose-300 transition hover:bg-rose-500/10"
                >
                  <LogOut className="h-3.5 w-3.5" aria-hidden />
                  Đăng xuất
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}
