import React from 'react';
import { cn } from '../../lib/cn';
import { TONE_BG_SOFT, TONE_BORDER, TONE_TEXT, type Tone } from '../../lib/tones';
import {
  EQUIPMENT_STATUS_LABELS,
  EQUIPMENT_STATUS_TONES,
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TONES,
  SEVERITY_LABELS,
  SEVERITY_TONES,
} from '../../lib/labels';
import type { EquipmentStatus, OrderStatus, Severity } from '../../types/api';

interface BadgeProps {
  tone?: Tone;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ tone = 'slate', icon, children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
        TONE_BG_SOFT[tone],
        TONE_BORDER[tone],
        TONE_TEXT[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONES[severity]}>{SEVERITY_LABELS[severity]}</Badge>;
}

export function StatusBadge({ status }: { status: EquipmentStatus }) {
  return <Badge tone={EQUIPMENT_STATUS_TONES[status]}>{EQUIPMENT_STATUS_LABELS[status]}</Badge>;
}

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  return <Badge tone={ORDER_STATUS_TONES[status]}>{ORDER_STATUS_LABELS[status]}</Badge>;
}

/** Nhãn phân loại tuổi nợ — backend trả sẵn chuỗi tiếng Việt không dấu nên hiển thị nguyên văn. */
export function AgingBadge({ bracket, tone }: { bracket: string; tone: Tone }) {
  return <Badge tone={tone}>{bracket}</Badge>;
}
