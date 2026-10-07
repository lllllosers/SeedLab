"""GER supplies type-specific decisions; Core performs formal transitions."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.contracts.errors import ConflictError, ValidationError
from app.core.experiment_types import EXPERIMENT_TYPES, ExperimentTypeRegistration
from app.models import (Experiment, ExperimentMaterial, ExperimentProtocol, GerminationDish,
                        GerminationObservation, MeasurementTimepoint, SeedlingMeasurement, SeedlingSample)
from app.services.germination_config import days_for, editable, materials_for, protocol_for, validate_all
from app.services.measurement_query import slot_summary


class GerminationWorkflow:
    def require_editable(self, experiment: Experiment) -> None:
        editable(experiment)

    def require_patch_transition(self, experiment: Experiment, target: str) -> None:
        if experiment.numbering_locked_at and target == "draft":
            raise ConflictError("置床编号已确认；若尚未置床，请使用“重新调整实验”")

    def require_ready(self, db: Session, experiment: Experiment) -> None:
        protocol = protocol_for(db, experiment.id)
        materials = materials_for(db, experiment.id)
        days = days_for(db, experiment.id)
        missing = []
        if protocol is None:
            missing.append("填写默认实验方案")
        else:
            fields = {
                "seeds_per_dish": "每皿种子数", "replicate_count": "重复数",
                "sampling_rule": "取样方式", "sample_count": "取样数",
                "sample_scope": "取样范围", "germination_criterion": "发芽判定标准",
            }
            missing.extend(f"填写{label}" for key, label in fields.items() if not getattr(protocol, key))
        if not materials:
            missing.append("添加至少一个实验材料")
        if not days:
            missing.append("设置至少一个发芽后测定时间（DAG）")
        if missing:
            raise ValidationError("标记为已就绪前，请先" + "、".join(missing))
        validate_all(protocol, materials)

    def completion_check(self, db: Session, experiment: Experiment) -> dict:
        dishes = list(db.scalars(select(GerminationDish).join(ExperimentMaterial,
            GerminationDish.material_id == ExperimentMaterial.id).where(ExperimentMaterial.experiment_id == experiment.id)))
        pending = sum(dish.sown_at is None and dish.cancelled_at is None for dish in dishes)
        # Informational only; the experimenter's completion action is the final confirmation.
        observing = sum(dish.sown_at is not None and dish.cancelled_at is None for dish in dishes)
        measurement = slot_summary(db, experiment.id)
        outstanding = sum(measurement[key] for key in ("due_today_count", "overdue_count", "upcoming_count", "unschedulable_count"))
        return {"pending_dish_count": pending, "observing_dish_count": observing, **measurement,
                "measurement_pending_count": outstanding,
                "can_complete": experiment.status == "active" and pending == 0 and outstanding == 0}

    def require_complete(self, db: Session, experiment: Experiment) -> None:
        result = self.completion_check(db, experiment)
        if not result["can_complete"]:
            if experiment.status != "active":
                raise ConflictError("只有进行中的实验可以确认完成")
            raise ConflictError(f"暂不能完成实验：待置床 {result['pending_dish_count']} 个、幼苗测定待办 {result['measurement_pending_count']} 项。请先处理待置床培养皿并完成已有幼苗测定，再确认完成实验。")

    def has_facts(self, db: Session, experiment: Experiment) -> bool:
        material_ids = select(ExperimentMaterial.id).where(ExperimentMaterial.experiment_id == experiment.id)
        dish_ids = select(GerminationDish.id).where(GerminationDish.material_id.in_(material_ids))
        sample_ids = select(SeedlingSample.id).where(SeedlingSample.dish_id.in_(dish_ids))
        return any(db.scalar(query.limit(1)) is not None for query in (
            select(GerminationDish.id).where(GerminationDish.id.in_(dish_ids), GerminationDish.sown_at.is_not(None)),
            select(GerminationObservation.id).where(GerminationObservation.dish_id.in_(dish_ids)),
            select(SeedlingSample.id).where(SeedlingSample.dish_id.in_(dish_ids)),
            select(SeedlingMeasurement.id).where(SeedlingMeasurement.sample_id.in_(sample_ids))))

    def cleanup_unused(self, db: Session, experiment: Experiment) -> None:
        material_ids = select(ExperimentMaterial.id).where(ExperimentMaterial.experiment_id == experiment.id)
        dish_ids = select(GerminationDish.id).where(GerminationDish.material_id.in_(material_ids))
        db.execute(delete(GerminationDish).where(GerminationDish.id.in_(dish_ids)))
        db.execute(delete(MeasurementTimepoint).where(MeasurementTimepoint.experiment_id == experiment.id))
        db.execute(delete(ExperimentProtocol).where(ExperimentProtocol.experiment_id == experiment.id))


def germination_registration() -> ExperimentTypeRegistration:
    return ExperimentTypeRegistration(code="GER", label=EXPERIMENT_TYPES["GER"], workflow=GerminationWorkflow())
