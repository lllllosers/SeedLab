"""Allocate experiment identity once; dates and descriptions never renumber it."""
from datetime import date
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Experiment
from app.services.local_time import today


def experiment_batch_month(planned_start_date: date | None) -> str:
    return (planned_start_date or today()).strftime("%Y%m")


def next_experiment_code(db: Session, experiment_type: str, batch_month: str) -> str:
    # Generic allocator; accepted workflow types are enforced by input/schema.
    if not re.fullmatch(r"[A-Z]{3,8}", experiment_type) or not re.fullmatch(r"\d{6}", batch_month):
        raise ValueError("Invalid experiment numbering scope")
    date(int(batch_month[:4]), int(batch_month[4:]), 1)
    prefix = f"{experiment_type}-{batch_month}-"
    codes = db.scalars(select(Experiment.code).where(
        Experiment.experiment_type == experiment_type, Experiment.code.like(prefix + "%")))
    highest = max((int(code[len(prefix):]) for code in codes if code[len(prefix):].isdigit()), default=0)
    # A concurrent creator can allocate the same candidate: the existing unique
    # constraint and transactional flush/commit must reject that entire request.
    return f"{prefix}{highest + 1:03d}"
