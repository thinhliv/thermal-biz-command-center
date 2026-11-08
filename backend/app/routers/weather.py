"""Router Khi tuong & Chuan hoa Dien nang theo Thoi tiet (A4 / IPMVP Option B/C).

Cung cap cac endpoint phuc vu quan trac nhiet do moi truong ngoai troi va
chuan hoa nang luong theo tieu chuan IPMVP EVO 10000-1:2012:
  - GET  /api/weather/sites/{site_code}/samples: Lay chuoi so lieu nhiet do ngoai troi do duoc.
  - POST /api/weather/samples: Day mau quan trac khi tuong (on-site sensor hoac weather station).
  - POST /api/weather/normalize: Chuan hoa dien nang ky bao cao theo duong co so CDD.
  - GET  /api/weather/carnot-lift: Tinh ton that COP Carnot va phat sinh cong suat may nen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import OutdoorWeatherSample, Site
from ..schemas import (
    OutdoorWeatherSampleCreate,
    OutdoorWeatherSamplePublic,
    WeatherNormalizationRequest,
    WeatherNormalizationResultPublic,
)
from ..security import ThermalRoles
from ..services import weather_normalization

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get(
    "/sites/{site_code}/samples",
    response_model=List[OutdoorWeatherSamplePublic],
    dependencies=[Depends(ThermalRoles)],
)
def get_site_weather_samples(
    site_code: str,
    start_ts: Optional[datetime] = Query(default=None, description="Moc bat dau (ISO 8601)"),
    end_ts: Optional[datetime] = Query(default=None, description="Moc ket thuc (ISO 8601)"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> List[OutdoorWeatherSample]:
    """Lay chuoi du lieu nhiet do moi truong ngoai troi thuc te cua co so."""
    site = session.scalars(select(Site).where(Site.code == site_code)).first()
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Khong tim thay co so voi ma '{site_code}'",
        )

    stmt = select(OutdoorWeatherSample).where(OutdoorWeatherSample.site_id == site.id)
    if start_ts is not None:
        stmt = stmt.where(OutdoorWeatherSample.ts >= start_ts)
    if end_ts is not None:
        stmt = stmt.where(OutdoorWeatherSample.ts <= end_ts)

    stmt = stmt.order_by(OutdoorWeatherSample.ts.desc()).limit(limit)
    return list(session.scalars(stmt))


@router.post(
    "/samples",
    response_model=OutdoorWeatherSamplePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ThermalRoles)],
)
def ingest_weather_sample(
    payload: OutdoorWeatherSampleCreate,
    session: Session = Depends(get_session),
) -> OutdoorWeatherSample:
    """Ghi nhan mot mau do nhiet do moi truong ngoai troi."""
    site = session.scalars(select(Site).where(Site.code == payload.site_code)).first()
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Khong tim thay co so voi ma '{payload.site_code}' de gan cam bien thoi tiet",
        )

    existing = session.scalars(
        select(OutdoorWeatherSample).where(
            OutdoorWeatherSample.site_id == site.id,
            OutdoorWeatherSample.ts == payload.ts,
        )
    ).first()

    if existing:
        # Idempotent update
        existing.ambient_temperature_c = payload.ambient_temperature_c
        existing.relative_humidity_pct = payload.relative_humidity_pct
        existing.source = payload.source
        existing.station_id = payload.station_id
        existing.is_measured = payload.is_measured
        session.commit()
        session.refresh(existing)
        return existing

    sample = OutdoorWeatherSample(
        site_id=site.id,
        site_code=site.code,
        ts=payload.ts,
        ambient_temperature_c=payload.ambient_temperature_c,
        relative_humidity_pct=payload.relative_humidity_pct,
        source=payload.source,
        station_id=payload.station_id,
        is_measured=payload.is_measured,
    )
    session.add(sample)
    session.commit()
    session.refresh(sample)
    return sample


@router.post(
    "/normalize",
    response_model=WeatherNormalizationResultPublic,
    dependencies=[Depends(ThermalRoles)],
)
def normalize_weather_energy(
    payload: WeatherNormalizationRequest,
) -> Dict[str, Any]:
    """Hoi quy duong co so va chuan hoa dien nang tiet kiem theo IPMVP."""
    try:
        model = weather_normalization.fit_weather_baseline_model(
            payload.baseline_daily_data,
            granularity="daily",
        )
    except weather_normalization.InvalidBaselineDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    result = weather_normalization.normalize_and_calculate_savings(
        baseline_model=model,
        reporting_days=payload.reporting_days,
        reporting_cdd=payload.reporting_cdd,
        reporting_actual_kwh=payload.reporting_actual_kwh,
        baseline_days=payload.baseline_days,
        baseline_cdd=payload.baseline_cdd,
        baseline_actual_kwh=payload.baseline_actual_kwh,
        base_temp_c=payload.base_temp_c,
    )

    return {
        "site_code": payload.site_code,
        "baseline_days": result.baseline_days,
        "reporting_days": result.reporting_days,
        "base_temp_c": result.base_temp_c,
        "baseline_cdd": result.baseline_cdd,
        "reporting_cdd": result.reporting_cdd,
        "baseline_actual_kwh": result.baseline_actual_kwh,
        "reporting_actual_kwh": result.reporting_actual_kwh,
        "adjusted_baseline_kwh": result.adjusted_baseline_kwh,
        "normalized_savings_kwh": result.normalized_savings_kwh,
        "normalized_savings_pct": result.normalized_savings_pct,
        "weather_effect_kwh": result.weather_effect_kwh,
        "unadjusted_savings_kwh": result.unadjusted_savings_kwh,
        "model_r_squared": model.r_squared,
        "model_cv_rmse_pct": model.cv_rmse_pct,
        "is_savings_statistically_valid": result.is_savings_statistically_valid,
        "explanation": result.explanation,
        "assumptions": model.assumptions,
    }


@router.get(
    "/carnot-lift",
    dependencies=[Depends(ThermalRoles)],
)
def get_carnot_lift_penalty(
    evap_temp_c: float = Query(description="Nhiet do bay hoi (deg C)"),
    ambient_temp_c: float = Query(description="Nhiet do ngoai troi thuc te (deg C)"),
    condenser_approach_k: float = Query(default=8.0, ge=1.0, le=25.0),
    reference_ambient_c: float = Query(default=30.0, ge=10.0, le=45.0),
) -> Dict[str, Any]:
    """Tinh toan do suy giam COP va phat sinh dien nang do nhiet do moi truong tang."""
    try:
        return weather_normalization.carnot_ambient_lift_penalty(
            evap_temp_c=evap_temp_c,
            ambient_temp_c=ambient_temp_c,
            condenser_approach_k=condenser_approach_k,
            reference_ambient_c=reference_ambient_c,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
