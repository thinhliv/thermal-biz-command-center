import { Activity, Flame, Snowflake, Wind } from 'lucide-react';
import { cn } from '../../lib/cn';
import { formatClock, formatNumber, formatPct, formatSignedPct, formatTemp } from '../../lib/format';
import { EQUIPMENT_KIND_LABELS } from '../../lib/labels';
import { Card, MetricTile } from '../ui/Card';
import { StatusBadge } from '../ui/Badge';
import type { TelemetryRow } from '../../types/api';

/** Chênh lệch COP dưới mức này so với thiết kế thì coi là đáng chú ý (thiếu gas / bẩn giàn). */
const COP_GAP_WARN_PCT = -10;

interface EquipmentCardProps {
  row: TelemetryRow;
  selected?: boolean;
  onSelect?: (code: string) => void;
}

/**
 * Máy lạnh và lò hơi KHÔNG đo cùng một đại lượng: COP = Q_o/N_e cho thiết bị lạnh,
 * η (%) cho thiết bị đốt. Ghép chung hai thứ là sai nghiệp vụ, nên thẻ này rẽ nhánh
 * theo is_refrigeration / is_combustion và chỉ hiện đúng đại lượng của loại đó.
 */
export function EquipmentCard({ row, selected = false, onSelect }: EquipmentCardProps) {
  const critical = row.haccp_breach || row.vibration_critical || row.status === 'FAULT';
  const warning = !critical && (row.cop_gap_pct ?? 0) < COP_GAP_WARN_PCT;
  const Icon = row.is_combustion ? Flame : row.kind === 'BLAST_FREEZER' ? Wind : Snowflake;

  return (
    <Card
      className={cn(
        'cursor-pointer p-3 transition',
        selected && 'ring-1 ring-cyan-500',
        critical ? 'border-rose-700/70 bg-rose-950/20' : warning ? 'border-amber-700/60' : 'hover:border-slate-600',
      )}
      onClick={() => onSelect?.(row.equipment_code)}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onKeyDown={(event) => {
        if (!onSelect) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(row.equipment_code);
        }
      }}
      aria-label={`${row.equipment_name} (${row.equipment_code})`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <Icon
            className={cn(
              'mt-0.5 h-4 w-4 shrink-0',
              critical ? 'text-rose-400' : row.is_combustion ? 'text-amber-400' : 'text-cyan-400',
            )}
            aria-hidden
          />
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold text-slate-100">{row.equipment_name}</div>
            <div className="truncate font-mono text-[10px] text-slate-500">
              {row.equipment_code} · {EQUIPMENT_KIND_LABELS[row.kind]}
            </div>
          </div>
        </div>
        <StatusBadge status={row.status} />
      </div>

      <div className="mb-2 flex items-end justify-between gap-2">
        <div>
          <div
            className={cn(
              'font-mono text-2xl font-bold leading-none',
              row.haccp_breach ? 'text-rose-400' : 'text-slate-100',
            )}
          >
            {formatTemp(row.temperature_c)}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {row.is_combustion ? 'Nhiệt độ buồng đốt' : 'Nhiệt độ kho'} · {formatClock(row.ts)}
          </div>
        </div>
        {row.is_refrigeration ? (
          <div className="text-right">
            <div
              className={cn(
                'font-mono text-lg font-bold leading-none',
                (row.cop_gap_pct ?? 0) < COP_GAP_WARN_PCT ? 'text-amber-400' : 'text-emerald-400',
              )}
            >
              {formatNumber(row.cop, 2)}
            </div>
            <div className="text-[10px] text-slate-500">
              COP · thiết kế {formatNumber(row.design_cop, 1)}
            </div>
          </div>
        ) : null}
        {row.is_combustion ? (
          <div className="text-right">
            <div className="font-mono text-lg font-bold leading-none text-emerald-400">
              {formatPct(row.efficiency_pct)}
            </div>
            <div className="text-[10px] text-slate-500">
              η · thiết kế {formatPct(row.design_efficiency_pct, 0)}
            </div>
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-4 gap-1">
        <MetricTile label="Công suất" value={`${formatNumber(row.power_kw, 0)} kW`} />
        <MetricTile
          label={row.is_refrigeration ? 'Lạnh' : 'Áp suất'}
          value={row.is_refrigeration ? `${formatNumber(row.cooling_capacity_kw, 0)} kW` : `${formatNumber(row.pressure_bar, 1)} bar`}
        />
        <MetricTile
          label="Rung"
          value={`${formatNumber(row.vibration_mm_s, 2)}`}
          tone={row.vibration_critical ? 'rose' : 'slate'}
          title="Giới hạn ISO 10816-3: 4,5 mm/s"
        />
        <MetricTile
          label={row.is_refrigeration ? 'Δ COP' : 'HACCP'}
          value={row.is_refrigeration ? formatSignedPct(row.cop_gap_pct) : row.haccp_limit_c !== null ? formatTemp(row.haccp_limit_c, 0) : '—'}
          tone={
            row.is_refrigeration
              ? (row.cop_gap_pct ?? 0) < COP_GAP_WARN_PCT
                ? 'amber'
                : 'emerald'
              : row.haccp_breach
                ? 'rose'
                : 'slate'
          }
        />
      </div>

      {row.haccp_breach ? (
        <div className="mt-2 flex items-center gap-1 rounded border border-rose-800 bg-rose-950/50 px-2 py-1 text-[10px] font-semibold text-rose-300">
          <Activity className="h-3 w-3 shrink-0" aria-hidden />
          Vi phạm HACCP: vượt {formatTemp(row.haccp_limit_c, 0)} — nguy cơ mất an toàn thực phẩm
        </div>
      ) : null}
      {!row.haccp_breach && row.vibration_critical ? (
        <div className="mt-2 rounded border border-amber-800 bg-amber-950/40 px-2 py-1 text-[10px] font-semibold text-amber-300">
          Rung {formatNumber(row.vibration_mm_s, 2)} mm/s — vùng C/D theo ISO 10816-3, cần kiểm tra bạc đạn
        </div>
      ) : null}
    </Card>
  );
}
