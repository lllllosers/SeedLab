"""UTC-naive SQLite timestamps and laboratory calendar dates."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return utc_naive(value).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def local_date(value: datetime) -> date:
    return local_datetime(value).date()


def local_datetime(value: datetime) -> datetime:
    return utc_naive(value).replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(get_settings().seedlab_timezone))


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().seedlab_timezone)).date()
