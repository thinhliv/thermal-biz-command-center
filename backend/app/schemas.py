"""Pydantic schemas. Moi INPUT deu duoc validate o day (khong tin du lieu ben goi)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Comparator, EquipmentStatus, Metric, Severity

ENTITY_ID_PATTERN = r"^[a-z0-9_]+\.[a-z0-9_]+$"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int
    user: "UserPublic"


class UserPublic(ORMModel):
    id: int
    username: str
    full_name: str
    role: str
    scopes: list[str] = Field(default_factory=list)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _not_too_simple(cls, value: str) -> str:
        if value.strip().lower() in {"password", "12345678", "changeme", "admin123"}:
            raise ValueError("Mat khau qua pho bien.")
        if not any(c.isalpha() for c in value) or not any(c.isdigit() or not c.isalnum() for c in value):
            raise ValueError("Mat khau can co ca chu va so/ky tu dac biet.")
        return value


LoginResponse.model_rebuild()


# --------------------------------------------------------------------------- #
# Ingest: telemetry (may goi may)
# --------------------------------------------------------------------------- #
class TelemetryIn(BaseModel):
    """Mot mau telemetry day len. `energy_kwh_cumulative` la CHI SO TICH LUY cua cong to."""

    equipment_code: str = Field(min_length=1, max_length=48)
    ts: datetime | None = None
    temperature_c: float | None = Field(default=None, ge=-120, le=600)
    pressure_bar: float | None = Field(default=None, ge=0, le=200)
    power_kw: float | None = Field(default=None, ge=0, le=100000)
    cooling_capacity_kw: float | None = Field(default=None, ge=0, le=200000)
    efficiency_pct: float | None = Field(default=None, ge=0, le=100)
    vibration_mm_s: float | None = Field(default=None, ge=0, le=200)
    energy_kwh_cumulative: float | None = Field(default=None, ge=0)
    status: EquipmentStatus | None = None

    @model_validator(mode="after")
    def _at_least_one_reading(self) -> "TelemetryIn":
        fields = (
            self.temperature_c,
            self.pressure_bar,
            self.power_kw,
            self.cooling_capacity_kw,
            self.efficiency_pct,
            self.vibration_mm_s,
            self.energy_kwh_cumulative,
        )
        if all(f is None for f in fields) and self.status is None:
            raise ValueError("Mau telemetry rong: can it nhat mot chi so hoac trang thai.")
        return self


class TelemetryIngestResult(BaseModel):
    accepted: int
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    alerts_raised: list["AlertPublic"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Ingest: billing
# --------------------------------------------------------------------------- #
class BillingRequest(BaseModel):
    """Xuat hoa don dien theo ky. Nhan CHI SO TICH LUY, backend tu tinh delta kWh.

    `client_id` CO Y KHONG nam trong model nay: connector/backend phai tu map
    tenant_code -> client, neu khong nguoi goi co the xuat hoa don cho khach hang bat ky.
    """

    tenant_code: str = Field(min_length=1, max_length=60)
    entity_id: str | None = Field(default=None, max_length=200, pattern=ENTITY_ID_PATTERN)
    period_start: datetime
    period_end: datetime
    previous_reading_kwh: float | None = Field(default=None, ge=0)
    current_reading_kwh: float = Field(ge=0)
    source: Literal["HA", "MANUAL", "SIMULATION", "MODBUS"] = "MANUAL"

    @model_validator(mode="after")
    def _period_order(self) -> "BillingRequest":
        if self.period_end <= self.period_start:
            raise ValueError("period_end phai sau period_start.")
        if (self.period_end - self.period_start).days > 400:
            raise ValueError("Ky billing qua dai (toi da 400 ngay).")
        return self


class BillingResponse(BaseModel):
    id: int
    tenant_code: str
    period_start: str
    period_end: str
    total_kwh: float
    kwh_by_band: dict[str, float]
    electricity_vnd: int
    service_fee_vnd: int
    total_vnd: int
    external_invoice_id: str | None = None
    breakdown: dict[str, Any] | None = None
    issued_at: str | None = None
    duplicated_call: bool = False


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
class AlertPublic(ORMModel):
    id: int
    severity: str
    message: str
    metric: str | None = None
    observed_value: float | None = None
    threshold: float | None = None
    is_haccp: bool = False
    equipment_code: str | None = None
    raised_at: datetime
    cleared_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


class AcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=400)


class AlarmRuleIn(BaseModel):
    equipment_code: str | None = Field(default=None, max_length=48)
    applies_to_kind: str | None = Field(default=None, max_length=32)
    metric: Metric
    comparator: Comparator
    threshold: float
    duration_minutes: int = Field(default=0, ge=0, le=10080)
    severity: Severity = Severity.WARNING
    message_template: str = Field(default="", max_length=400)
    is_haccp: bool = False
    enabled: bool = True


class AlarmRulePublic(ORMModel):
    id: int
    equipment_id: int | None = None
    applies_to_kind: str | None = None
    metric: str
    comparator: str
    threshold: float
    duration_minutes: int
    severity: str
    message_template: str
    is_haccp: bool
    enabled: bool


# --------------------------------------------------------------------------- #
# Tra loi cho frontend
# --------------------------------------------------------------------------- #
class TelemetryRow(BaseModel):
    equipment_code: str
    equipment_name: str
    kind: str
    status: str
    temperature_c: float | None = None
    pressure_bar: float | None = None
    power_kw: float | None = None
    cooling_capacity_kw: float | None = None
    cop: float | None = None
    design_cop: float | None = None
    cop_gap_pct: float | None = None
    efficiency_pct: float | None = None
    design_efficiency_pct: float | None = None
    vibration_mm_s: float | None = None
    vibration_critical: bool = False
    haccp_limit_c: float | None = None
    haccp_breach: bool = False
    is_refrigeration: bool = False
    is_combustion: bool = False
    ts: str | None = None


class ThermalSummary(BaseModel):
    total_power_kw: float
    avg_cop: float | None = None
    avg_boiler_efficiency_pct: float | None = None
    total_units: int
    running: int
    warning: int
    fault: int
    telemetry: list[TelemetryRow]
    alerts: list[AlertPublic] = Field(default_factory=list)
    vibration_limit_mm_s: float
    haccp_seafood_limit_c: float


class HealthResponse(BaseModel):
    """Dung cho `GET /api/health`. Giu khop 1-1 voi payload that o `main.health_check`."""

    status: Literal["ok", "degraded"]
    system: str
    version: str
    database: str
    backend: Literal["sqlite", "postgres"]


TelemetryIngestResult.model_rebuild()
