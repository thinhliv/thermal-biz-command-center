import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Lock, Radio, User } from 'lucide-react';
import { homePath, ROLE_HINTS, ROLE_LABELS } from '../lib/scopes';
import { describeAuthError, useAuth } from '../store/auth';
import type { Role } from '../types/api';

/**
 * Suy ra từ `ROLE_LABELS` thay vì liệt kê tay. Phép suy ra này chỉ đúng nhờ hai test backend:
 * `test_seed_du_moi_vai_tro_trong_role_enum` (mọi Role đều có trong `DEMO_USERS`) và
 * `test_username_demo_suy_ra_duoc_tu_ten_vai` (username = tên vai viết thường).
 */
const DEMO_ACCOUNTS: Array<{ username: string; role: Role }> = (Object.keys(ROLE_LABELS) as Role[]).map(
  (role) => ({ username: role.toLowerCase(), role }),
);

export function LoginPage() {
  const { status, user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Đã đăng nhập thì không giữ người dùng ở trang login, kể cả khi họ gõ URL tay.
  if (status === 'authenticated' && user) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from ?? homePath(user.scopes)} replace />;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const me = await login(username.trim(), password);
      navigate(homePath(me.scopes), { replace: true });
    } catch (caught) {
      setError(describeAuthError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[#0b0f19] px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-5 flex flex-col items-center text-center">
          <div className="mb-2 grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 text-cyan-300">
            <Radio className="h-5 w-5" aria-hidden />
          </div>
          <h1 className="text-lg font-bold text-slate-100">Trung tâm Nhiệt &amp; Kinh doanh</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Giám sát COP · HACCP · Điện TOU · Công nợ — một màn hình duy nhất
          </p>
        </div>

        <form
          onSubmit={submit}
          className="rounded-xl border border-slate-800 bg-[#111827] p-4 shadow-xl"
          aria-label="Đăng nhập"
        >
          <label className="mb-3 block text-xs">
            <span className="mb-1 block text-slate-400">Tên đăng nhập</span>
            <div className="relative">
              <User className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" aria-hidden />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoFocus
                required
                minLength={2}
                className="w-full rounded border border-slate-700 bg-slate-950 py-1.5 pl-7 pr-2 text-slate-100 outline-none focus:border-cyan-500"
              />
            </div>
          </label>

          <label className="mb-3 block text-xs">
            <span className="mb-1 block text-slate-400">Mật khẩu</span>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" aria-hidden />
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded border border-slate-700 bg-slate-950 py-1.5 pl-7 pr-2 text-slate-100 outline-none focus:border-cyan-500"
              />
            </div>
          </label>

          {error ? (
            <p role="alert" className="mb-3 rounded border border-rose-900 bg-rose-950/40 px-2 py-1.5 text-[11px] text-rose-300">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full rounded bg-cyan-600 py-2 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </form>

        <div className="mt-4 rounded-xl border border-slate-800 bg-[#0d1220] p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            {DEMO_ACCOUNTS.length} vai trò — quyền khác nhau
          </div>
          <ul className="max-h-60 space-y-1.5 overflow-y-auto pr-1">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.username} className="flex items-start gap-2 text-[11px]">
                <button
                  type="button"
                  onClick={() => setUsername(account.username)}
                  className="shrink-0 rounded border border-slate-700 px-1.5 py-0.5 font-mono text-cyan-300 transition hover:border-cyan-600"
                  title={`Điền tên đăng nhập ${account.username}`}
                >
                  {account.username}
                </button>
                <span className="min-w-0 text-slate-500">
                  <span className="text-slate-300">{ROLE_LABELS[account.role]}</span> — {ROLE_HINTS[account.role]}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[10px] text-slate-600">
            Mật khẩu demo nằm trong biến <code className="text-slate-500">SEED_DEMO_PASSWORD</code> của file{' '}
            <code className="text-slate-500">.env</code> phía server. Đổi ngay sau lần đăng nhập đầu.
          </p>
        </div>
      </div>
    </div>
  );
}
