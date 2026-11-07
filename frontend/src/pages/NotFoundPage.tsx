import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { homePath } from '../lib/scopes';
import { useAuth } from '../store/auth';

export function NotFoundPage() {
  const { user } = useAuth();
  const home = user ? homePath(user.scopes) : '/login';

  return (
    <div className="grid min-h-[60vh] place-items-center px-4 text-center">
      <div>
        <Compass className="mx-auto mb-2 h-6 w-6 text-slate-600" aria-hidden />
        <h1 className="text-base font-semibold text-slate-200">Không tìm thấy trang này</h1>
        <p className="mt-1 text-xs text-slate-500">
          Đường dẫn không tồn tại, hoặc vai trò của bạn không có quyền xem.
        </p>
        <Link
          to={home}
          className="mt-3 inline-block rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-600 hover:text-cyan-300"
        >
          Về trang chính
        </Link>
      </div>
    </div>
  );
}
