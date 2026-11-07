import type { CSSProperties } from 'react';

/**
 * Tailwind JIT chỉ sinh class xuất hiện NGUYÊN VĂN trong mã nguồn, nên không được ghép
 * chuỗi kiểu `text-${tone}-400`. Mọi biến thể màu phải nằm sẵn trong các bảng dưới đây.
 */
export type Tone = 'cyan' | 'emerald' | 'amber' | 'rose' | 'sky' | 'violet' | 'slate';

export const TONE_HEX: Record<Tone, string> = {
  cyan: '#22d3ee',
  emerald: '#34d399',
  amber: '#fbbf24',
  rose: '#fb7185',
  sky: '#38bdf8',
  violet: '#a78bfa',
  slate: '#94a3b8',
};

export const TONE_TEXT: Record<Tone, string> = {
  cyan: 'text-cyan-400',
  emerald: 'text-emerald-400',
  amber: 'text-amber-400',
  rose: 'text-rose-400',
  sky: 'text-sky-400',
  violet: 'text-violet-400',
  slate: 'text-slate-400',
};

export const TONE_BORDER: Record<Tone, string> = {
  cyan: 'border-cyan-500/40',
  emerald: 'border-emerald-500/40',
  amber: 'border-amber-500/40',
  rose: 'border-rose-500/40',
  sky: 'border-sky-500/40',
  violet: 'border-violet-500/40',
  slate: 'border-slate-700',
};

export const TONE_BG_SOFT: Record<Tone, string> = {
  cyan: 'bg-cyan-500/10',
  emerald: 'bg-emerald-500/10',
  amber: 'bg-amber-500/10',
  rose: 'bg-rose-500/10',
  sky: 'bg-sky-500/10',
  violet: 'bg-violet-500/10',
  slate: 'bg-slate-700/20',
};

export const TONE_BG_BAR: Record<Tone, string> = {
  cyan: 'bg-cyan-500',
  emerald: 'bg-emerald-500',
  amber: 'bg-amber-500',
  rose: 'bg-rose-500',
  sky: 'bg-sky-500',
  violet: 'bg-violet-500',
  slate: 'bg-slate-500',
};

export const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
};
