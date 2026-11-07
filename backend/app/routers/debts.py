"""Cong no: phai thu, tuoi no, han muc tin dung, ghi nhan thanh toan."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import Customer, Receivable, ReceivableStatus, User
from ..security import FinanceRoles
from ..services import finance
from ..timeutil import utcnow

router = APIRouter(prefix="/api/debts", tags=["debts"])


class PaymentIn(BaseModel):
    amount_vnd: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=400)


@router.get("")
def debts(session: Session = Depends(get_session), _: User = Depends(FinanceRoles)) -> dict:
    return finance.debt_summary(session)


@router.get("/credit-breaches")
def credit_breaches(session: Session = Depends(get_session), _: User = Depends(FinanceRoles)) -> dict:
    breaches = finance.credit_limit_breaches(session)
    return {"count": len(breaches), "items": breaches}


@router.get("/customers")
def customers(session: Session = Depends(get_session), _: User = Depends(FinanceRoles)) -> dict:
    rows = list(session.scalars(select(Customer).order_by(Customer.name)))
    return {
        "count": len(rows),
        "items": [
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "tax_id": c.tax_id,
                "contact_name": c.contact_name,
                "contact_phone": c.contact_phone,
                "email": c.email,
                "credit_limit_vnd": c.credit_limit_vnd,
                "payment_term_days": c.payment_term_days,
                "is_active": c.is_active,
            }
            for c in rows
        ],
    }


@router.post("/{receivable_id}/payments", status_code=status.HTTP_200_OK)
def record_payment(
    receivable_id: int,
    payload: PaymentIn,
    session: Session = Depends(get_session),
    user: User = Depends(FinanceRoles),
) -> dict:
    item = session.get(Receivable, receivable_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khong tim thay khoan phai thu.")
    if item.status == ReceivableStatus.CANCELLED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hoa don da bi huy.")

    remaining = item.outstanding_vnd
    if payload.amount_vnd > remaining:
        raise HTTPException(
            status_code=422,
            detail=f"So tien thanh toan ({payload.amount_vnd:,}) vuot so con phai thu ({remaining:,}).",
        )

    item.paid_amount_vnd += payload.amount_vnd
    if item.outstanding_vnd == 0:
        item.status = ReceivableStatus.PAID.value
        item.paid_at = utcnow()
    else:
        item.status = ReceivableStatus.PARTIAL.value
    if payload.note:
        suffix = f"[{user.username}] {payload.note}"
        item.note = f"{item.note}\n{suffix}" if item.note else suffix

    session.commit()
    session.refresh(item)
    return {
        "id": item.id,
        "invoice_number": item.invoice_number,
        "amount_vnd": item.amount_vnd,
        "paid_amount_vnd": item.paid_amount_vnd,
        "outstanding_vnd": item.outstanding_vnd,
        "status": item.status,
        "paid_at": item.paid_at.isoformat() if item.paid_at else None,
    }
