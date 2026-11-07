"""Mo hinh du lieu nghiep vu: Nhiet lanh x Tai chinh.

Quy uoc:
- Tien te luu BigInteger (VND nguyen dong). VND khong dung phan le den xu trong thuc te,
  va BigInteger chay giong nhau tren SQLite lan Postgres (Numeric tren SQLite bi mat chinh xac).
- Nhiet do / COP / hieu suat luu Float.
- Moi datetime la naive-UTC (xem app/timeutil.py).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .timeutil import utcnow

# SQLite can INTEGER (khong phai BIGINT) cho cot rowid autoincrement
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
Money = BigInteger


# --------------------------------------------------------------------------- #
# Enum nghiep vu
# --------------------------------------------------------------------------- #
class Role(str, Enum):
    """RBAC 3 vai."""

    BGD = "BGD"  # Ban giam doc: thay tat ca
    VANHANH = "VANHANH"  # Van hanh: chi Nhiet + xac nhan canh bao
    KETOAN = "KETOAN"  # Ke toan: chi Kinh doanh + Cong no


class EquipmentKind(str, Enum):
    DEEP_FREEZER = "DEEP_FREEZER"  # Kho dong sau (-25..-35 C)
    COLD_ROOM = "COLD_ROOM"  # Kho mat (+-0..+8 C)
    BLAST_FREEZER = "BLAST_FREEZER"  # Ham cap dong gio nhanh
    CHILLER = "CHILLER"
    COMPRESSOR = "COMPRESSOR"
    BOILER = "BOILER"  # Lo hoi: dung HIEU SUAT eta, KHONG dung COP


#: Thiet bi lanh -> danh gia bang COP = Q_o / N_e
REFRIGERATION_KINDS = frozenset(
    {
        EquipmentKind.DEEP_FREEZER,
        EquipmentKind.COLD_ROOM,
        EquipmentKind.BLAST_FREEZER,
        EquipmentKind.CHILLER,
        EquipmentKind.COMPRESSOR,
    }
)

#: Thiet bi dot -> danh gia bang hieu suat nhiet eta (%)
COMBUSTION_KINDS = frozenset({EquipmentKind.BOILER})


class EquipmentStatus(str, Enum):
    RUNNING = "RUNNING"
    STANDBY = "STANDBY"
    DEFROST = "DEFROST"
    FAULT = "FAULT"
    STOPPED = "STOPPED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    WARNING = "WARNING"
    INFO = "INFO"


SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.MAJOR: 2,
    Severity.CRITICAL: 3,
}


class Metric(str, Enum):
    """Ten cot trong TelemetrySample ma mot AlarmRule co the bam theo."""

    TEMPERATURE_C = "temperature_c"
    COP = "cop"
    EFFICIENCY_PCT = "efficiency_pct"
    VIBRATION_MM_S = "vibration_mm_s"
    PRESSURE_BAR = "pressure_bar"
    POWER_KW = "power_kw"


class Comparator(str, Enum):
    LT = "LT"  # canh bao khi gia tri < nguong
    LTE = "LTE"
    GT = "GT"  # canh bao khi gia tri > nguong
    GTE = "GTE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReceivableStatus(str, Enum):
    """KHONG luu trang thai OVERDUE - qua han la suy ra tu due_at vs hom nay."""

    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class TariffBandCode(str, Enum):
    """EVN gia ban le dien theo gio (TOU 3 muc)."""

    PEAK = "PEAK"  # gio cao diem
    NORMAL = "NORMAL"  # gio binh thuong
    OFF_PEAK = "OFF_PEAK"  # gio thap diem


# --------------------------------------------------------------------------- #
# Nguoi dung / phan quyen
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.BGD.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    acknowledged_alerts: Mapped[list["Alert"]] = relationship(back_populates="acknowledged_by_user")

    __table_args__ = (CheckConstraint("role IN ('BGD','VANHANH','KETOAN')", name="ck_users_role"),)


# --------------------------------------------------------------------------- #
# Nhiet / tai san
# --------------------------------------------------------------------------- #
class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    refrigerant: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rated_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    commissioned_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Diem dat ky thuat ---
    setpoint_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Nguong HACCP: nhiet do TOI DA cho phep cua chuoi lanh (hai san <= -18 C)
    haccp_limit_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Hieu nang: COP va eta la HAI dai luong KHAC NHAU ---
    #: Chi co nghia voi thiet bi lanh: COP = Q_o / N_e
    design_cop: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Chi co nghia voi lo hoi: hieu suat nhiet eta (%)
    design_efficiency_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Lien ket billing (Huong B) ---
    tenant_code: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    meter_entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    telemetry: Mapped[list["TelemetrySample"]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan"
    )
    alarm_rules: Mapped[list["AlarmRule"]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(back_populates="equipment")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('DEEP_FREEZER','COLD_ROOM','BLAST_FREEZER','CHILLER','COMPRESSOR','BOILER')",
            name="ck_equipment_kind",
        ),
        # Khong duoc gan COP cho lo hoi...
        CheckConstraint("kind <> 'BOILER' OR design_cop IS NULL", name="ck_boiler_has_no_cop"),
        # ...va khong duoc gan hieu suat dot cho thiet bi lanh.
        CheckConstraint(
            "kind = 'BOILER' OR design_efficiency_pct IS NULL", name="ck_refrigeration_has_no_eta"
        ),
    )

    @property
    def is_refrigeration(self) -> bool:
        try:
            return EquipmentKind(self.kind) in REFRIGERATION_KINDS
        except ValueError:
            return False

    @property
    def is_combustion(self) -> bool:
        try:
            return EquipmentKind(self.kind) in COMBUSTION_KINDS
        except ValueError:
            return False


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: P_o (bay hoi) hoac P_k (ngung tu) tuy thiet bi
    pressure_bar: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: N_e - cong suat dien tieu thu
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Q_o - cong suat lanh sinh ra (chi thiet bi lanh)
    cooling_capacity_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: COP = Q_o / N_e. NULL voi lo hoi.
    cop: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Hieu suat nhiet eta (%). NULL voi thiet bi lanh.
    efficiency_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Rung toc ISO 10816 (mm/s). > 4.5 = ranh gioi vung C/D.
    vibration_mm_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Chi so cong to dien TICH LUY (kWh). Delta = hieu 2 lan doc.
    energy_kwh_cumulative: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    equipment: Mapped[Equipment] = relationship(back_populates="telemetry")

    __table_args__ = (
        UniqueConstraint("equipment_id", "ts", name="uq_telemetry_equipment_ts"),
        Index("ix_telemetry_equipment_ts", "equipment_id", "ts"),
        Index("ix_telemetry_ts", "ts"),
    )


# --------------------------------------------------------------------------- #
# Canh bao
# --------------------------------------------------------------------------- #
class AlarmRule(Base):
    """Nguong canh bao khai bao duoc, khong hardcode trong code."""

    __tablename__ = "alarm_rules"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    #: NULL = ap dung cho moi thiet bi co `applies_to_kind` tuong ung
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=True
    )
    applies_to_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    comparator: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    #: Vi pham lien tuc trong bao nhieu phut moi ban canh bao (chong nhieu)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.WARNING.value)
    message_template: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    #: True = vi pham an toan thuc pham HACCP
    is_haccp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    equipment: Mapped[Equipment | None] = relationship(back_populates="alarm_rules")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="rule")

    __table_args__ = (
        CheckConstraint(
            "metric IN ('temperature_c','cop','efficiency_pct','vibration_mm_s','pressure_bar','power_kw')",
            name="ck_alarm_rule_metric",
        ),
        CheckConstraint("comparator IN ('LT','LTE','GT','GTE')", name="ck_alarm_rule_comparator"),
        CheckConstraint("severity IN ('CRITICAL','MAJOR','WARNING','INFO')", name="ck_alarm_rule_severity"),
        CheckConstraint("duration_minutes >= 0", name="ck_alarm_rule_duration"),
    )

    def matches_kind(self, equipment: Equipment) -> bool:
        if self.equipment_id is not None:
            return self.equipment_id == equipment.id
        if self.applies_to_kind is None:
            return True
        return self.applies_to_kind == equipment.kind

    def is_breached(self, value: float | None) -> bool:
        if value is None:
            return False
        return {
            Comparator.LT: lambda v: v < self.threshold,
            Comparator.LTE: lambda v: v <= self.threshold,
            Comparator.GT: lambda v: v > self.threshold,
            Comparator.GTE: lambda v: v >= self.threshold,
        }[Comparator(self.comparator)](value)

    def render_message(self, equipment: Equipment, value: float) -> str:
        return self.message_template.format(
            equipment=equipment.name,
            code=equipment.code,
            value=value,
            threshold=self.threshold,
        )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("alarm_rules.id", ondelete="SET NULL"), nullable=True
    )
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    is_haccp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raised_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    rule: Mapped[AlarmRule | None] = relationship(back_populates="alerts")
    equipment: Mapped[Equipment | None] = relationship(back_populates="alerts")
    acknowledged_by_user: Mapped[User | None] = relationship(back_populates="acknowledged_alerts")

    __table_args__ = (
        Index("ix_alerts_open", "cleared_at", "raised_at"),
        CheckConstraint("severity IN ('CRITICAL','MAJOR','WARNING','INFO')", name="ck_alert_severity"),
    )

    @property
    def is_open(self) -> bool:
        return self.cleared_at is None


# --------------------------------------------------------------------------- #
# Kinh doanh
# --------------------------------------------------------------------------- #
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Han muc tin dung. Vuot han muc -> canh bao cong no.
    credit_limit_vnd: Mapped[int | None] = mapped_column(Money, nullable=True)
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    orders: Mapped[list["ServiceOrder"]] = relationship(back_populates="customer")
    receivables: Mapped[list["Receivable"]] = relationship(back_populates="customer")


class MonthlyTarget(Base):
    """Ke hoach doanh thu theo thang. Luu trong DB de KHONG con target hardcode trong UI."""

    __tablename__ = "monthly_targets"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue_target_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    gross_margin_target_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_monthly_target"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_target_month"),
        CheckConstraint("revenue_target_vnd >= 0", name="ck_monthly_target_revenue"),
    )


class ServiceOrder(Base):
    __tablename__ = "service_orders"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True)

    service_type: Mapped[str] = mapped_column(String(64), nullable=False)
    volume_tons: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OrderStatus.IN_PROGRESS.value)

    revenue_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)

    # --- COGS day du: loi gop = doanh thu - TAT CA cac khoan duoi day ---
    electricity_cost_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    refrigerant_cost_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    labor_cost_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    maintenance_cost_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    overhead_cost_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    equipment: Mapped[Equipment | None] = relationship()
    receivables: Mapped[list["Receivable"]] = relationship(back_populates="order")

    __table_args__ = (
        CheckConstraint("revenue_vnd >= 0", name="ck_order_revenue_non_negative"),
        CheckConstraint(
            "status IN ('DRAFT','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_order_status"
        ),
    )

    @property
    def total_cogs_vnd(self) -> int:
        return (
            self.electricity_cost_vnd
            + self.refrigerant_cost_vnd
            + self.labor_cost_vnd
            + self.maintenance_cost_vnd
            + self.overhead_cost_vnd
        )

    @property
    def gross_profit_vnd(self) -> int:
        return self.revenue_vnd - self.total_cogs_vnd

    @property
    def gross_margin_pct(self) -> float | None:
        """Lai gop %. Tra ve None khi chua co doanh thu (tranh chia 0 va tranh hien 0% gia)."""
        if not self.revenue_vnd:
            return None
        return round(self.gross_profit_vnd / self.revenue_vnd * 100, 2)


class Receivable(Base):
    """Khoan phai thu. Qua han duoc SUY RA tu due_at, khong luu trang thai rieng."""

    __tablename__ = "receivables"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("service_orders.id"), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(48), unique=True, nullable=True)

    amount_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    paid_amount_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ReceivableStatus.OPEN.value)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="receivables")
    order: Mapped[ServiceOrder | None] = relationship(back_populates="receivables")

    __table_args__ = (
        Index("ix_receivables_due", "status", "due_at"),
        CheckConstraint(
            "status IN ('OPEN','PARTIAL','PAID','CANCELLED')", name="ck_receivable_status"
        ),
        CheckConstraint("paid_amount_vnd >= 0", name="ck_receivable_paid_non_negative"),
    )

    @property
    def outstanding_vnd(self) -> int:
        return max(0, self.amount_vnd - self.paid_amount_vnd)

    @property
    def is_settled(self) -> bool:
        return self.status in (ReceivableStatus.PAID.value, ReceivableStatus.CANCELLED.value)

    def overdue_days(self, now: datetime | None = None) -> int:
        """So ngay qua han. 0 neu chua den han hoac da thanh toan."""
        if self.is_settled:
            return 0
        now = now or utcnow()
        return max(0, (now - self.due_at).days)


# --------------------------------------------------------------------------- #
# Billing theo dien nang (EVN TOU)
# --------------------------------------------------------------------------- #
class TariffBand(Base):
    """Mot khung gio gia dien. EVN TOU chia 3 muc: cao diem / binh thuong / thap diem.

    Khung gio vuot nua dem (22:00-04:00) duoc tach thanh 2 dong de tranh logic wrap-around.
    """

    __tablename__ = "tariff_bands"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name_vn: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 0..1439, phut ke tu 00:00
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 1..1440, KHONG bao gom
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ISO weekday CSV, vd "1,2,3,4,5,6". "*" = moi ngay.
    days: Mapped[str] = mapped_column(String(32), nullable=False, default="*")
    price_vnd_per_kwh: Mapped[int] = mapped_column(Money, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("code", "start_minute", "days", "effective_from", name="uq_tariff_band"),
        CheckConstraint("code IN ('PEAK','NORMAL','OFF_PEAK')", name="ck_tariff_band_code"),
        CheckConstraint("start_minute >= 0 AND start_minute < 1440", name="ck_tariff_start"),
        CheckConstraint("end_minute > 0 AND end_minute <= 1440", name="ck_tariff_end"),
        CheckConstraint("end_minute > start_minute", name="ck_tariff_range"),
        CheckConstraint("price_vnd_per_kwh >= 0", name="ck_tariff_price"),
    )

    def applies_to(self, moment: datetime) -> bool:
        minute = moment.hour * 60 + moment.minute
        if not (self.start_minute <= minute < self.end_minute):
            return False
        if self.days == "*":
            return True
        allowed = {int(d) for d in self.days.split(",") if d.strip()}
        return moment.isoweekday() in allowed


class MeterReading(Base):
    """Mot ky doc cong to. `delta_kwh` moi la cai de tinh tien - KHONG phai chi so tich luy."""

    __tablename__ = "meter_readings"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True)
    tenant_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reading_start_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    reading_end_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    delta_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="HA")

    #: Chia delta theo 3 khung gio, dung khi billing theo TOU
    peak_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    normal_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    off_peak_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_code", "period_start", "period_end", name="uq_meter_reading_period"),
        CheckConstraint("delta_kwh >= 0", name="ck_meter_delta_non_negative"),
        CheckConstraint("period_end > period_start", name="ck_meter_period_order"),
    )


class BilledInvoice(Base):
    """Hoa don da xuat. UniqueConstraint (tenant, ky) la khoa IDEMPOTENCY:
    goi 2 lan cung ky -> tra ve ban ghi cu, khong tao hoa don trung.
    """

    __tablename__ = "billed_invoices"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meter_reading_id: Mapped[int | None] = mapped_column(ForeignKey("meter_readings.id"), nullable=True)

    total_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    peak_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    normal_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    off_peak_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    electricity_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    service_fee_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    total_vnd: Mapped[int] = mapped_column(Money, nullable=False, default=0)

    #: ID hoa don phia Invoice Ninja (nguon ngoai)
    external_invoice_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_code", "period_start", "period_end", name="uq_billed_invoice_period"),
    )
