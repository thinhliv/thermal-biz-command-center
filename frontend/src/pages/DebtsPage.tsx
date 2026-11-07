import { AlertTriangle, FileText, Percent, Receipt, Users, Wallet } from 'lucide-react';
import { AgingBar } from '../components/charts/AgingBar';
import { DebtorList } from '../components/debts/DebtorList';
import { InvoiceTable } from '../components/debts/InvoiceTable';
import { Card, CardHeader } from '../components/ui/Card';
import { MetricCard } from '../components/ui/MetricCard';
import { ProgressBar } from '../components/ui/ProgressBar';
import { EmptyBlock, ErrorBlock, LoadingBlock } from '../components/ui/StateBlock';
import { useApi } from '../hooks/useApi';
import { formatCompactVND, formatDateTime, formatPct, formatVND } from '../lib/format';
import { AGING_TONES } from '../lib/labels';
import { TONE_HEX } from '../lib/tones';
import { useDashboard } from '../store/dashboard';
import type { CreditBreach, CustomerInfo } from '../types/api';

interface BreachResponse {
  count: number;
  items: CreditBreach[];
}

interface CustomerResponse {
  count: number;
  items: CustomerInfo[];
}

/** Trên mức này thì tỷ lệ nợ quá hạn coi là báo động, cần siết điều khoản bán chịu. */
const OVERDUE_ALERT_PCT = 30;

export function DebtsPage() {
  const { debts, loading, error, refresh } = useDashboard();
  const breaches = useApi<BreachResponse>('/api/debts/credit-breaches');
  const customers = useApi<CustomerResponse>('/api/debts/customers');

  if (loading) return <LoadingBlock label="Đang nạp số liệu công nợ…" />;
  if (error) return <ErrorBlock message={error} onRetry={refresh} />;
  if (!debts) return <ErrorBlock message="Không có dữ liệu công nợ cho vai trò này." />;

  const overdueCritical = debts.overdue_pct >= OVERDUE_ALERT_PCT;
  const breachItems = breaches.data?.items ?? [];
  const totalAging = debts.aging_breakdown.reduce((sum, bucket) => sum + bucket.amount, 0);

  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <MetricCard
          label="Tổng phải thu"
          value={formatCompactVND(debts.total_receivables)}
          icon={<Wallet className="h-4 w-4" aria-hidden />}
          tone="cyan"
          hint={`${debts.open_invoice_count} hoá đơn chưa thu`}
        />
        <MetricCard
          label="Nợ quá hạn"
          value={formatCompactVND(debts.overdue_debt)}
          icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
          tone={overdueCritical ? 'rose' : 'amber'}
          hint="Tính theo hạn thanh toán trên từng hoá đơn"
        />
        <MetricCard
          label="Tỷ lệ quá hạn"
          value={formatPct(debts.overdue_pct)}
          icon={<Percent className="h-4 w-4" aria-hidden />}
          tone={overdueCritical ? 'rose' : 'emerald'}
          hint={overdueCritical ? `Vượt ngưỡng cảnh báo ${OVERDUE_ALERT_PCT}%` : 'Trong ngưỡng chấp nhận'}
        />
        <MetricCard
          label="Vượt hạn mức"
          value={`${breaches.data?.count ?? 0}`}
          icon={<Users className="h-4 w-4" aria-hidden />}
          tone={breachItems.length > 0 ? 'rose' : 'slate'}
          hint="Khách hàng cần chặn xuất hàng mới"
        />
      </section>

      {breachItems.length > 0 ? (
        <Card className="border-rose-900/60 bg-rose-950/10 p-3">
          <CardHeader
            title="Vượt hạn mức tín dụng"
            icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
            tone="rose"
            action={`${breachItems.length} khách hàng`}
          />
          <ul className="space-y-1.5">
            {breachItems.map((breach) => (
              <li key={breach.customer_id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="text-xs font-semibold text-slate-100">
                  {breach.customer}
                  <span className="ml-2 font-mono text-[10px] font-normal text-slate-500">{breach.customer_code}</span>
                </span>
                <span className="font-mono text-[11px] text-rose-300">
                  Dư {formatCompactVND(breach.outstanding_vnd)} / hạn mức {formatCompactVND(breach.credit_limit_vnd)} ·
                  vượt {formatCompactVND(breach.excess_vnd)} ({formatPct(breach.utilization_pct, 0)})
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <section className="grid gap-3 xl:grid-cols-2">
        <Card className="p-3">
          <CardHeader title="Tuổi nợ theo bracket" icon={<FileText className="h-4 w-4" aria-hidden />} tone="amber" />
          <AgingBar data={debts.aging_breakdown} />
          <ul className="mt-2 space-y-1">
            {debts.aging_breakdown.map((bucket) => (
              <li key={bucket.bracket} className="flex items-center justify-between text-[11px]">
                <span className="text-slate-400">{bucket.bracket}</span>
                <span className="font-mono text-slate-300">
                  {formatVND(bucket.amount)}
                  {totalAging > 0 ? (
                    <span className="ml-1 text-slate-500">({formatPct((bucket.amount / totalAging) * 100, 0)})</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-3">
          <CardHeader title="Khách hàng nợ nhiều nhất" icon={<Users className="h-4 w-4" aria-hidden />} tone="rose" />
          <DebtorList debtors={debts.top_debtors} />
        </Card>
      </section>

      <Card className="p-3">
        <CardHeader
          title="Hoá đơn chưa thu"
          icon={<Receipt className="h-4 w-4" aria-hidden />}
          tone="cyan"
          action={`${debts.open_invoice_count} hoá đơn · chốt lúc ${formatDateTime(debts.as_of)}`}
        />
        <InvoiceTable invoices={debts.open_invoices} />
      </Card>

      <Card className="p-3">
        <CardHeader
          title="Hạn mức & điều khoản thanh toán"
          icon={<Users className="h-4 w-4" aria-hidden />}
          tone="slate"
          action={customers.data ? `${customers.data.count} khách hàng` : undefined}
        />
        {customers.loading && !customers.data ? <LoadingBlock label="Đang nạp danh sách khách hàng…" /> : null}
        {customers.error ? <ErrorBlock message={customers.error} onRetry={customers.refresh} /> : null}
        {customers.data && customers.data.items.length === 0 ? (
          <EmptyBlock label="Chưa có khách hàng nào trong hệ thống" />
        ) : null}
        {customers.data && customers.data.items.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-wide text-slate-500">
                  <th className="px-2 py-1.5 font-medium">Mã</th>
                  <th className="px-2 py-1.5 font-medium">Khách hàng</th>
                  <th className="px-2 py-1.5 font-medium">Liên hệ</th>
                  <th className="px-2 py-1.5 text-right font-medium">Hạn mức tín dụng</th>
                  <th className="px-2 py-1.5 font-medium">Điều khoản</th>
                  <th className="px-2 py-1.5 font-medium">Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {customers.data.items.map((customer) => (
                  <tr key={customer.id} className="border-b border-slate-800/60 hover:bg-slate-800/20">
                    <td className="px-2 py-1.5 font-mono text-slate-500">{customer.code}</td>
                    <td className="px-2 py-1.5 text-slate-200">
                      {customer.name}
                      {customer.tax_id ? (
                        <div className="font-mono text-[10px] text-slate-500">MST {customer.tax_id}</div>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-slate-400">
                      {customer.contact_name ?? '—'}
                      {customer.contact_phone ? (
                        <div className="font-mono text-[10px] text-slate-500">{customer.contact_phone}</div>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-300">
                      {customer.credit_limit_vnd === null ? 'Không giới hạn' : formatVND(customer.credit_limit_vnd)}
                    </td>
                    <td className="px-2 py-1.5 text-slate-400">{customer.payment_term_days} ngày</td>
                    <td className="px-2 py-1.5">
                      <span className={customer.is_active ? 'text-emerald-400' : 'text-slate-500'}>
                        {customer.is_active ? 'Đang hoạt động' : 'Ngưng'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      <Card className="p-3">
        <CardHeader title="Cơ cấu nợ" tone="cyan" />
        <ProgressBar
          value={debts.overdue_pct}
          tone={overdueCritical ? 'rose' : 'amber'}
          label="Tỷ lệ nợ quá hạn trên tổng phải thu"
          className="h-2.5"
        />
        <p className="mt-2 text-[11px] text-slate-500">
          {formatCompactVND(debts.overdue_debt)} trong tổng số {formatCompactVND(debts.total_receivables)} phải thu đã
          quá hạn. Bracket càng về phải thì khả năng thu hồi càng thấp — ưu tiên đòi nhóm{' '}
          {debts.aging_breakdown[debts.aging_breakdown.length - 1]?.bracket ?? 'quá hạn nặng nhất'} trước.
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
          {debts.aging_breakdown.map((bucket, index) => (
            <span key={bucket.bracket} className="flex items-center gap-1">
              <span
                aria-hidden
                className="inline-block h-2 w-2 rounded-sm"
                style={{ backgroundColor: TONE_HEX[AGING_TONES[index % AGING_TONES.length]] }}
              />
              {bucket.bracket}
            </span>
          ))}
        </div>
      </Card>
    </div>
  );
}
