import React from 'react';
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react';
import { cn } from '../../lib/cn';

export function LoadingBlock({ label = 'Đang tải dữ liệu…', className }: { label?: string; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 py-10 text-slate-400', className)}>
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
      <span className="text-xs">{label}</span>
    </div>
  );
}

interface ErrorBlockProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorBlock({ message, onRetry, className }: ErrorBlockProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 py-10 text-center', className)}>
      <AlertTriangle className="h-5 w-5 text-rose-400" aria-hidden />
      <p className="max-w-md text-xs text-rose-300">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 transition hover:border-slate-500 hover:text-white"
        >
          <RefreshCw className="h-3 w-3" aria-hidden />
          Thử lại
        </button>
      ) : null}
    </div>
  );
}

export function EmptyBlock({
  label = 'Chưa có dữ liệu',
  className,
  children,
}: {
  label?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-1 py-8 text-center text-slate-500', className)}>
      <Inbox className="h-5 w-5" aria-hidden />
      <p className="text-xs">{label}</p>
      {children}
    </div>
  );
}
