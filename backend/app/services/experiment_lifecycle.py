"""Experiment Core: the sole authority for formal state and lifecycle timestamps."""
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.contracts.errors import ConflictError, ValidationError
from app.contracts.experiments import ExperimentOut, ExperimentPatch
from app.core.experiment_types import ExperimentTypeRegistry, ExperimentTypeWorkflow
from app.models import Experiment, ExperimentMaterial
from app.models.entities import now_utc
from app.services.application_support import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.local_time import iso_utc, utc_naive


def completion_check(db: Session, experiment_id: str, registry: ExperimentTypeRegistry):
    experiment = require_entity(db, Experiment, experiment_id)
    return registry.require(experiment.experiment_type).workflow.completion_check(db, experiment)


def require_complete(db: Session, experiment_id: str, registry: ExperimentTypeRegistry):
    experiment = require_entity(db, Experiment, experiment_id)
    registry.require(experiment.experiment_type).workflow.require_complete(db, experiment)


def set_status(db: Session, experiment: Experiment, target: str, workflow: ExperimentTypeWorkflow) -> None:
    # Preserve the existing PATCH validation order, including same-state requests.
    if target == "completed" and target != experiment.status:
        workflow.require_complete(db, experiment)
    if target == "cancelled" and target != experiment.status:
        raise ConflictError("请通过“终止实验”填写原因后结束进行中的实验")
    workflow.require_patch_transition(experiment, target)
    allowed = {"draft": {"ready", "cancelled"}, "ready": {"draft", "cancelled"},
               "active": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}
    if target == experiment.status:
        return
    if target not in allowed[experiment.status]:
        raise ConflictError("当前实验不能直接进入该状态，请先完成实验配置并正式开始实验")
    if target in {"ready", "active"}:
        workflow.require_ready(db, experiment)
    experiment.status = target


def update(db: Session, experiment_id: str, data: ExperimentPatch, user_id: str,
           registry: ExperimentTypeRegistry):
    item = require_entity(db, Experiment, experiment_id)
    if item.status in {"completed", "cancelled"}:
        raise ConflictError("已结束的实验信息只供查阅；已完成实验的测定纠错请进入测定记录")
    workflow = registry.require(item.experiment_type).workflow
    before = ExperimentOut.model_validate(item).model_dump(mode="json")
    patch = data.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key in {"name", "status"} and value is None:
            raise ValidationError("实验名称和当前状态不能为空")
        if key == "planned_start_date":
            workflow.require_editable(item)
        if key != "status":
            setattr(item, key, value)
    if "status" in patch:
        set_status(db, item, patch["status"], workflow)
        if item.status in {"completed", "cancelled"} and item.ended_at is None:
            item.ended_at = now_utc()
    flush_or_conflict(db)
    after = ExperimentOut.model_validate(item).model_dump(mode="json")
    if before != after:
        record(db, user_id, "update", "Experiment", item.id, before, after)
    commit_or_conflict(db)
    return item


def reopen_after_cleanup(experiment: Experiment) -> None:
    # The type workflow has already validated and cleaned its unused design.
    if experiment.status != "ready":
        raise ConflictError("当前实验不能直接进入该状态，请先完成实验配置并正式开始实验")
    experiment.status = "draft"


def activate_from_fact(db: Session, experiment: Experiment, actual: datetime, user_id: str) -> None:
    # The type workflow has validated the actual start fact in this transaction.
    if experiment.status not in {"ready", "active"}:
        raise ConflictError("当前实验不能直接进入该状态，请先完成实验配置并正式开始实验")
    if experiment.status == "ready":
        experiment.status = "active"
    if experiment.started_at is None or actual < utc_naive(experiment.started_at):
        experiment.started_at = actual
    record(db, user_id, "update", "Experiment", experiment.id, None,
           {"status": experiment.status, "started_at": iso_utc(experiment.started_at)})


def correct_started_at(experiment: Experiment, actual: datetime | None) -> None:
    experiment.started_at = actual


def complete(db: Session, experiment_id: str, user_id: str, registry: ExperimentTypeRegistry):
    item = require_entity(db, Experiment, experiment_id)
    require_complete(db, experiment_id, registry)
    before = {"code": item.code, "name": item.name, "status": item.status}
    item.status = "completed"
    item.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record(db, user_id, "update", "Experiment", item.id, before,
           {**before, "status": item.status, "ended_at": iso_utc(item.ended_at)})
    commit_or_conflict(db)
    return item


def terminate(db: Session, experiment_id: str, reason: str, user_id: str):
    item = require_entity(db, Experiment, experiment_id)
    if item.status != "active":
        raise ConflictError("只有进行中的实验可以终止")
    if not reason.strip():
        raise ValidationError("请填写终止原因，方便以后核对实验履历")
    before = {"code": item.code, "name": item.name, "status": item.status}
    item.status = "cancelled"
    item.termination_reason = reason.strip()
    item.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record(db, user_id, "update", "Experiment", item.id, before,
           {**before, "status": item.status, "termination_reason": item.termination_reason, "ended_at": iso_utc(item.ended_at)})
    commit_or_conflict(db)
    return item


def delete_unused(db: Session, experiment_id: str, user_id: str, registry: ExperimentTypeRegistry):
    item = require_entity(db, Experiment, experiment_id)
    workflow = registry.require(item.experiment_type).workflow
    if workflow.has_facts(db, item):
        raise ConflictError("该实验已经产生实际置床或观测数据，不能永久删除。若实验不再继续，请使用‘终止实验’。")
    if item.status not in {"draft", "ready"}:
        raise ConflictError("已完成或已终止的实验保留历史记录，不能永久删除")
    before = {"code": item.code, "name": item.name, "status": item.status}
    try:
        workflow.cleanup_unused(db, item)
        db.execute(delete(ExperimentMaterial).where(ExperimentMaterial.experiment_id == item.id))
        record(db, user_id, "delete", "Experiment", item.id, before, None)
        db.delete(item)
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
