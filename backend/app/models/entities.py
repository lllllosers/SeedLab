from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class User(Identity, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SessionToken(Identity, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user: Mapped[User] = relationship()


class Taxon(Identity, Base):
    __tablename__ = "taxa"
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    scientific_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    common_name: Mapped[str | None] = mapped_column(String(255))
    family: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    seed_lots: Mapped[list["SeedLot"]] = relationship(back_populates="taxon")


class SeedLot(Identity, Base):
    __tablename__ = "seed_lots"
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    taxon_id: Mapped[str] = mapped_column(ForeignKey("taxa.id", ondelete="RESTRICT"), index=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    taxon: Mapped[Taxon] = relationship(back_populates="seed_lots")
    __table_args__ = (CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_seed_lot_quantity"),)


class Experiment(Identity, Base):
    __tablename__ = "experiments"
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('draft', 'active', 'completed', 'cancelled')", name="ck_experiment_status"),)


class ExperimentProtocol(Identity, Base):
    __tablename__ = "experiment_protocols"
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), unique=True)
    summary: Mapped[str | None] = mapped_column(Text)
    seed_count_per_dish: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("seed_count_per_dish IS NULL OR seed_count_per_dish > 0", name="ck_protocol_seed_count"),)


class ExperimentMaterial(Identity, Base):
    __tablename__ = "experiment_materials"
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), index=True)
    seed_lot_id: Mapped[str] = mapped_column(ForeignKey("seed_lots.id", ondelete="RESTRICT"), index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (UniqueConstraint("experiment_id", "seed_lot_id", name="uq_material_experiment_lot"),)


class MeasurementTimepoint(Identity, Base):
    __tablename__ = "measurement_timepoints"
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), index=True)
    day_after_germination: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        CheckConstraint("day_after_germination >= 0", name="ck_timepoint_dag_nonnegative"),
        Index("uq_timepoint_experiment_dag", "experiment_id", "day_after_germination", unique=True),
    )


class GerminationDish(Identity, Base):
    __tablename__ = "germination_dishes"
    material_id: Mapped[str] = mapped_column(ForeignKey("experiment_materials.id", ondelete="RESTRICT"), index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    seed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("seed_count > 0", name="ck_dish_seed_count"), UniqueConstraint("material_id", "label", name="uq_dish_label"))


class GerminationObservation(Identity, Base):
    __tablename__ = "germination_observations"
    dish_id: Mapped[str] = mapped_column(ForeignKey("germination_dishes.id", ondelete="RESTRICT"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_germinated_count: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("new_germinated_count >= 0", name="ck_observation_count"), UniqueConstraint("dish_id", "observed_at", name="uq_observation_time"))


class SeedlingSample(Identity, Base):
    __tablename__ = "seedling_samples"
    dish_id: Mapped[str] = mapped_column(ForeignKey("germination_dishes.id", ondelete="RESTRICT"), index=True)
    sample_number: Mapped[int] = mapped_column(Integer, nullable=False)
    germinated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("sample_number > 0", name="ck_sample_number"), UniqueConstraint("dish_id", "sample_number", name="uq_sample_number"))


class SeedlingMeasurement(Identity, Base):
    __tablename__ = "seedling_measurements"
    sample_id: Mapped[str] = mapped_column(ForeignKey("seedling_samples.id", ondelete="RESTRICT"), index=True)
    timepoint_id: Mapped[str] = mapped_column(ForeignKey("measurement_timepoints.id", ondelete="RESTRICT"), index=True)
    root_length_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    shoot_length_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("root_length_mm IS NULL OR root_length_mm >= 0", name="ck_root_length"), CheckConstraint("shoot_length_mm IS NULL OR shoot_length_mm >= 0", name="ck_shoot_length"), UniqueConstraint("sample_id", "timepoint_id", name="uq_sample_timepoint"))


class AuditLog(Identity, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)


class ImportJob(Identity, Base):
    __tablename__ = "import_jobs"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
