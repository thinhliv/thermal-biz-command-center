import { cn } from '../../lib/cn';
import { clamp } from '../../lib/format';
import { TONE_BG_BAR, TONE_HEX, type Tone } from '../../lib/tones';

interface ProgressBarProps {
  /** 0-100. Giá trị ngoài khoảng sẽ bị kẹp lại, không tràn khung. */
  value: number;
  tone?: Tone;
  /** Màu cảnh báo khi vượt 100% (ví dụ vượt hạn mức tín dụng). */
  overLimit?: boolean;
  label?: string;
  className?: string;
}

export function ProgressBar({
  value,
  tone = 'cyan',
  overLimit = false,
  label,
  className,
}: ProgressBarProps) {
  const width = clamp(value, 0, 100);
  const barTone: Tone = overLimit ? 'rose' : tone;
  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-slate-800', className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={cn('h-full rounded-full transition-all duration-500', TONE_BG_BAR[barTone])} style={{ width: `${width}%` }} />
    </div>
  );
}

export interface StackedSegment {
  key: string;
  value: number;
  tone: Tone;
  label: string;
}

interface StackedBarProps {
  segments: StackedSegment[];
  className?: string;
}

/**
 * Thanh tuổi nợ công nợ: mỗi bracket một khúc. Đoạn nào = 0 thì bỏ hẳn để không tạo
 * khoảng trắng 1px làm sai tỷ lệ thị giác.
 */
export function StackedBar({ segments, className }: StackedBarProps) {
  const total = segments.reduce((sum, segment) => sum + Math.max(0, segment.value), 0);
  if (total <= 0) {
    return <div className={cn('h-2 w-full rounded-full bg-slate-800', className)} />;
  }
  return (
    <div className={cn('flex h-2 w-full overflow-hidden rounded-full bg-slate-800', className)}>
      {segments
        .filter((segment) => segment.value > 0)
        .map((segment) => (
          <div
            key={segment.key}
            className="h-full"
            style={{ width: `${(segment.value / total) * 100}%`, backgroundColor: TONE_HEX[segment.tone] }}
            title={`${segment.label}: ${Math.round((segment.value / total) * 100)}%`}
          />
        ))}
    </div>
  );
}
