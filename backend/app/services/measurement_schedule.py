"""DAG means laboratory local calendar date plus natural days.

Python and SQLite keep their native execution paths. The SQLite local-date UDF
already delegates timezone conversion to local_time; parity tests protect the
calendar-day addition without materializing SQL queues in Python.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import String, cast, func

from app.services.local_time import local_date


def scheduled_date(germinated_at: datetime | None, dag: int) -> date | None:
    return local_date(germinated_at) + timedelta(days=dag) if germinated_at else None


def scheduled_date_expression(germinated_at, dag):
    return func.date(func.seedlab_local_date(germinated_at), '+' + cast(dag, String) + ' days')
