import React from 'react';
import { cn } from '../../lib/cn';
import { TONE_TEXT, type Tone } from '../../lib/tones';

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-xl border border-slate-800 bg-[#111827]', className)} {...props} />
  );
}

interface CardHeaderProps {
  title: string;
  icon?: React.ReactNode;
  tone?: Tone;
  action?: React.ReactNode;
}

export function CardHeader({ title, icon, tone = 'cyan', action }: CardHeaderProps) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
      <h2 className={cn('flex items-center gap-2 text-sm font-semibold uppercase tracking-wide', TONE_TEXT[tone])}>
        {icon}
        {title}
      </h2>
      {action ? <div className="shrink-0 text-xs text-slate-400">{action}</div> : null}
    </div>
  );
}

interface MetricTileProps {
  label: string;
  value: string;
  tone?: Tone;
  title?: string;
}

/** Ô số liệu nhỏ bên trong card thiết bị / hoá đơn. */
export function MetricTile({ label, value, tone = 'slate', title }: MetricTileProps) {
  return (
    <div className="rounded bg-slate-950/50 p-1.5 text-center" title={title}>
      <div className="text-[10px] leading-tight text-slate-400">{label}</div>
      <div className={cn('font-mono text-xs font-bold leading-tight', TONE_TEXT[tone])}>{value}</div>
    </div>
  );
}
