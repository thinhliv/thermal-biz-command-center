import React from 'react';
import { cn } from '../../lib/cn';
import { TONE_TEXT, type Tone } from '../../lib/tones';
import { Card } from './Card';

interface MetricCardProps {
  label: string;
  value: string;
  icon?: React.ReactNode;
  tone?: Tone;
  hint?: React.ReactNode;
  className?: string;
}

/** Thẻ KPI hàng trên cùng của mỗi trang. */
export function MetricCard({ label, value, icon, tone = 'cyan', hint, className }: MetricCardProps) {
  return (
    <Card className={cn('p-4 transition hover:border-slate-600', className)}>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs text-slate-400">
        <span className="truncate uppercase tracking-wide">{label}</span>
        {icon ? <span className={cn('shrink-0', TONE_TEXT[tone])}>{icon}</span> : null}
      </div>
      <div
        className={cn('font-mono text-lg font-bold leading-tight sm:text-2xl', TONE_TEXT[tone])}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-slate-400">{hint}</div> : null}
    </Card>
  );
}
