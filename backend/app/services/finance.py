"""Tai chinh: doanh thu, lai gop (COGS day du), cong no va phan tich tuoi no.

Nguyen tac:
- Lai gop = Doanh thu - TONG COGS (dien + gas lanh + nhan cong + bao tri + chi phi chung).
  Ban cu chi tinh tru chi phi dien nen lai gop bi thoi phong - da sua o day.
- "Qua han" KHONG luu thanh trang thai; no suy ra tu due_at vs thoi diem hien tai.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Customer,
    MonthlyTarget,
    OrderStatus,
    Receivable,
    ReceivableStatus,
    ServiceOrder,
)
from ..timeutil import day_bounds, month_bounds, utcnow

#: Cac thang tuoi no theo thong le ke toan Viet Nam
AGING_BRACKETS: list[tuple[str, int | None, int | None]] = [
    ("Trong hạn", None, 0),
    ("1-30 ngày", 1, 30),
    ("31-60 ngày", 31, 60),
    ("61-90 ngày", 61, 90),
    ("Trên 90 ngày", 91, None),
]


def _bracket_for(overdue_days: int) -> str:
    for label, low, high in AGING_BRACKETS:
        if low is None:
            if overdue_days <= (high or 0):
                return label
        elif high is None:
            if overdue_days >= low:
                return label
        elif low <= overdue_days <= high:
            return label
    return AGING_BRACKETS[-1][0]


def monthly_target(session: Session, moment: datetime | None = None) -> MonthlyTarget | None:
    moment = moment or utcnow()
    return session.scalars(
        select(MonthlyTarget).where(MonthlyTarget.year == moment.year, MonthlyTarget.month == moment.month)
    ).first()


def revenue_series(session: Session, days: int = 30) -> list[dict]:
    """Doanh thu + lai gop theo ngay, de ve bieu do."""
    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    orders = list(
        session.scalars(
            select(ServiceOrder).where(
                ServiceOrder.started_at >= start,
                ServiceOrder.status != OrderStatus.CANCELLED.value,
            )
        )
    )

    buckets: dict[str, dict] = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        buckets[day.strftime("%Y-%m-%d")] = {
            "date": day.strftime("%Y-%m-%d"),
            "revenue_vnd": 0,
            "gross_profit_vnd": 0,
            "orders": 0,
        }

    for order in orders:
        key = order.started_at.strftime("%Y-%m-%d")
        if key not in buckets:
            continue
        buckets[key]["revenue_vnd"] += order.revenue_vnd
        buckets[key]["gross_profit_vnd"] += order.gross_profit_vnd
        buckets[key]["orders"] += 1

    return list(buckets.values())


def business_summary(session: Session, electricity_cost_today_vnd: int = 0) -> dict:
    now = utcnow()
    today_start, today_end = day_bounds(now)
    month_start, month_end = month_bounds(now)

    def _range_revenue(start: datetime, end: datetime) -> tuple[int, int, float]:
        orders = list(
            session.scalars(
                select(ServiceOrder).where(
                    ServiceOrder.started_at >= start,
                    ServiceOrder.started_at < end,
                    ServiceOrder.status != OrderStatus.CANCELLED.value,
                )
            )
        )
        revenue = sum(o.revenue_vnd for o in orders)
        cogs = sum(o.total_cogs_vnd for o in orders)
        volume = sum((o.volume_tons or 0) for o in orders)
        return revenue, cogs, volume

    today_revenue, today_cogs, today_volume = _range_revenue(today_start, today_end)
    mtd_revenue, mtd_cogs, mtd_volume = _range_revenue(month_start, month_end)

    target = monthly_target(session, now)
    target_revenue = target.revenue_target_vnd if target else 0

    recent = list(
        session.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.status != OrderStatus.CANCELLED.value)
            .order_by(ServiceOrder.started_at.desc())
            .limit(8)
        )
    )
    recent_orders = [
        {
            "order_code": order.code,
            "customer": order.customer.name if order.customer else "",
            "amount": order.revenue_vnd,
            "service": order.service_type,
            "volume_tons": order.volume_tons,
            # Lai gop that: tru het COGS, khong chi tru tien dien
            "cogs_vnd": order.total_cogs_vnd,
            "gross_profit_vnd": order.gross_profit_vnd,
            "margin": order.gross_margin_pct,
            "started_at": order.started_at.isoformat(),
            "status": order.status,
        }
        for order in recent
    ]

    revenue_by_service_rows = list(
        session.execute(
            select(
                ServiceOrder.service_type,
                func.sum(ServiceOrder.revenue_vnd),
                func.count(ServiceOrder.id),
            )
            .where(ServiceOrder.started_at >= month_start, ServiceOrder.started_at < month_end)
            .where(ServiceOrder.status != OrderStatus.CANCELLED.value)
            .group_by(ServiceOrder.service_type)
            .order_by(func.sum(ServiceOrder.revenue_vnd).desc())
        )
    )

    mtd_gross_profit = mtd_revenue - mtd_cogs

    return {
        "today_revenue": today_revenue,
        "mtd_revenue": mtd_revenue,
        "target_revenue": target_revenue,
        "target_progress_pct": round(mtd_revenue / target_revenue * 100, 2) if target_revenue else None,
        "electricity_cost_today": electricity_cost_today_vnd,
        # COGS day du (dien + gas + nhan cong + bao tri + chi phi chung)
        "mtd_cogs_vnd": mtd_cogs,
        "mtd_gross_profit_vnd": mtd_gross_profit,
        "gross_margin_pct": round(mtd_gross_profit / mtd_revenue * 100, 2) if mtd_revenue else None,
        "gross_margin_target_pct": target.gross_margin_target_pct if target else None,
        "total_volume_tons": round(mtd_volume, 2),
        "today_volume_tons": round(today_volume, 2),
        "orders_today": len([o for o in recent if today_start <= o.started_at < today_end]),
        "recent_orders": recent_orders,
        "revenue_by_service": [
            {"service": row[0], "revenue_vnd": int(row[1] or 0), "orders": int(row[2])}
            for row in revenue_by_service_rows
        ],
        "revenue_trend_30d": revenue_series(session, days=30),
        "as_of": now.isoformat(),
    }


def debt_summary(session: Session) -> dict:
    now = utcnow()
    open_receivables = list(
        session.scalars(
            select(Receivable).where(
                Receivable.status.in_([ReceivableStatus.OPEN.value, ReceivableStatus.PARTIAL.value])
            )
        )
    )

    buckets = {label: 0 for label, _, _ in AGING_BRACKETS}
    total_outstanding = 0
    total_overdue = 0

    for item in open_receivables:
        outstanding = item.outstanding_vnd
        if outstanding <= 0:
            continue
        total_outstanding += outstanding
        overdue_days = item.overdue_days(now)
        if overdue_days > 0:
            total_overdue += outstanding
        buckets[_bracket_for(overdue_days)] += outstanding

    debtor_totals: dict[int, dict] = {}
    for item in open_receivables:
        outstanding = item.outstanding_vnd
        overdue_days = item.overdue_days(now)
        if outstanding <= 0 or overdue_days <= 0:
            continue
        entry = debtor_totals.setdefault(
            item.customer_id,
            {
                "customer_id": item.customer_id,
                "customer": item.customer.name if item.customer else "",
                "amount": 0,
                "overdue_days": 0,
                "invoices": 0,
                "credit_limit_vnd": item.customer.credit_limit_vnd if item.customer else None,
            },
        )
        entry["amount"] += outstanding
        entry["overdue_days"] = max(entry["overdue_days"], overdue_days)
        entry["invoices"] += 1

    top_debtors = sorted(debtor_totals.values(), key=lambda d: d["amount"], reverse=True)[:10]
    for debtor in top_debtors:
        days = debtor["overdue_days"]
        debtor["status"] = "CRITICAL" if days > 60 else ("WARNING" if days > 30 else "WATCH")
        debtor["bracket"] = _bracket_for(days)
        limit = debtor["credit_limit_vnd"]
        debtor["credit_utilization_pct"] = (
            round(debtor["amount"] / limit * 100, 2) if limit else None
        )
        debtor["over_limit"] = bool(limit and debtor["amount"] > limit)

    invoices = [
        {
            "id": item.id,
            "invoice_number": item.invoice_number,
            "customer": item.customer.name if item.customer else "",
            "amount_vnd": item.amount_vnd,
            "paid_amount_vnd": item.paid_amount_vnd,
            "outstanding_vnd": item.outstanding_vnd,
            "issued_at": item.issued_at.isoformat(),
            "due_at": item.due_at.isoformat(),
            "overdue_days": item.overdue_days(now),
            "bracket": _bracket_for(item.overdue_days(now)),
            "status": item.status,
        }
        for item in sorted(open_receivables, key=lambda r: r.due_at)
        if item.outstanding_vnd > 0
    ]

    return {
        "total_receivables": total_outstanding,
        "overdue_debt": total_overdue,
        "overdue_pct": round(total_overdue / total_outstanding * 100, 2) if total_outstanding else 0.0,
        "aging_breakdown": [{"bracket": label, "amount": buckets[label]} for label, _, _ in AGING_BRACKETS],
        "top_debtors": top_debtors,
        "open_invoices": invoices[:50],
        "open_invoice_count": len(invoices),
        "as_of": now.isoformat(),
    }


def credit_limit_breaches(session: Session) -> list[dict]:
    """Khach hang vuot han muc tin dung - nguon canh bao cong no."""
    rows = session.execute(
        select(
            Customer.id,
            Customer.code,
            Customer.name,
            Customer.credit_limit_vnd,
            func.coalesce(func.sum(Receivable.amount_vnd - Receivable.paid_amount_vnd), 0),
        )
        .join(Receivable, Receivable.customer_id == Customer.id)
        .where(
            Customer.is_active.is_(True),
            Customer.credit_limit_vnd.is_not(None),
            Receivable.status.in_([ReceivableStatus.OPEN.value, ReceivableStatus.PARTIAL.value]),
        )
        .group_by(Customer.id, Customer.code, Customer.name, Customer.credit_limit_vnd)
    ).all()

    breaches = []
    for customer_id, code, name, limit, outstanding in rows:
        if limit and outstanding > limit:
            breaches.append(
                {
                    "customer_id": customer_id,
                    "customer_code": code,
                    "customer": name,
                    "credit_limit_vnd": int(limit),
                    "outstanding_vnd": int(outstanding),
                    "excess_vnd": int(outstanding) - int(limit),
                    "utilization_pct": round(outstanding / limit * 100, 2),
                }
            )
    return sorted(breaches, key=lambda b: b["excess_vnd"], reverse=True)
