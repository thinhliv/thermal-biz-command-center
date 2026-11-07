import { useState } from 'react';
import { X } from 'lucide-react';
import { ApiError } from '../../lib/api';
import { useAuth } from '../../store/auth';

interface ChangePasswordDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Mật khẩu mới phải khớp luật của backend (ChangePasswordRequest): >= 8 ký tự, có chữ
 * VÀ có số/ký tự đặc biệt, không nằm trong danh sách yếu. Kiểm tra ở đây chỉ để báo
 * lỗi sớm; quyết định cuối vẫn thuộc về server.
 */
const WEAK = new Set(['password', '12345678', 'changeme', 'admin123']);

function validate(next: string): string | null {
  if (next.length < 8) return 'Mật khẩu mới phải có ít nhất 8 ký tự.';
  if (WEAK.has(next.toLowerCase())) return 'Mật khẩu này quá yếu, chọn mật khẩu khác.';
  if (!/[A-Za-z]/.test(next)) return 'Mật khẩu phải chứa ít nhất một chữ cái.';
  if (!/[^A-Za-z]/.test(next)) return 'Mật khẩu phải chứa số hoặc ký tự đặc biệt.';
  return null;
}

export function ChangePasswordDialog({ open, onClose }: ChangePasswordDialogProps) {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const localProblem = validate(next);
  const mismatch = next !== confirm;
  const canSubmit = current.length > 0 && !localProblem && !mismatch && !busy;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không đổi được mật khẩu, thử lại sau.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" role="dialog" aria-modal="true">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-xl border border-slate-700 bg-[#0f172a] p-4 shadow-2xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-100">Đổi mật khẩu</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="rounded p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="space-y-2.5 text-xs">
          <label className="block">
            <span className="mb-1 block text-slate-400">Mật khẩu hiện tại</span>
            <input
              type="password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              autoComplete="current-password"
              className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-slate-400">Mật khẩu mới</span>
            <input
              type="password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              autoComplete="new-password"
              className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 outline-none focus:border-cyan-500"
            />
            {next && localProblem ? <span className="mt-1 block text-rose-400">{localProblem}</span> : null}
          </label>

          <label className="block">
            <span className="mb-1 block text-slate-400">Nhập lại mật khẩu mới</span>
            <input
              type="password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              autoComplete="new-password"
              className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 outline-none focus:border-cyan-500"
            />
            {confirm && mismatch ? <span className="mt-1 block text-rose-400">Hai lần nhập không khớp.</span> : null}
          </label>

          {error ? <p className="rounded border border-rose-900 bg-rose-950/40 px-2 py-1.5 text-rose-300">{error}</p> : null}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-slate-500"
          >
            Huỷ
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            {busy ? 'Đang lưu…' : 'Lưu mật khẩu'}
          </button>
        </div>
      </form>
    </div>
  );
}
