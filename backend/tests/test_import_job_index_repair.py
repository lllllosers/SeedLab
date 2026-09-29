from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import make_engine


REPAIR_REVISION = "0b6111724c00"
CURRENT_HEAD = "b742b49a162e"
PREVIOUS_REVISION = "e8b62c74a901"
INDEX_NAME = "ix_import_jobs_file_hash"


@pytest.fixture
def migration_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{(tmp_path / 'import-jobs.db').as_posix()}"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    get_settings.cache_clear()
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    engine = make_engine(url)
    try:
        yield config, engine
    finally:
        engine.dispose()
        get_settings.cache_clear()


def index_unique(connection):
    indexes = connection.exec_driver_sql("PRAGMA index_list('import_jobs')").all()
    return next((bool(row[2]) for row in indexes if row[1] == INDEX_NAME), None)


def insert_job(connection, job_id: str, file_hash: str | None) -> None:
    connection.exec_driver_sql(
        """INSERT INTO import_jobs
           (id, created_at, filename, status, total_rows, successful_rows, file_hash)
           VALUES (?, '2026-09-29', 'materials.xlsx', 'completed', 1, 1, ?)""",
        (job_id, file_hash),
    )


def test_nonunique_index_is_repaired_and_downgrade_keeps_canonical_index(migration_db):
    config, engine = migration_db
    command.upgrade(config, PREVIOUS_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {INDEX_NAME}")
        connection.exec_driver_sql(f"CREATE INDEX {INDEX_NAME} ON import_jobs(file_hash)")
        assert index_unique(connection) is False

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == CURRENT_HEAD
        assert index_unique(connection) is True
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

    command.downgrade(config, PREVIOUS_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == PREVIOUS_REVISION
        assert index_unique(connection) is True
    command.upgrade(config, "head")
    command.check(config)


def test_fresh_database_enforces_unique_nonnull_hash_and_allows_multiple_nulls(migration_db):
    config, engine = migration_db
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == CURRENT_HEAD
        assert index_unique(connection) is True
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

    with engine.begin() as connection:
        insert_job(connection, "first", "a" * 64)
        insert_job(connection, "null-first", None)
        insert_job(connection, "null-second", None)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_job(connection, "duplicate", "a" * 64)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM import_jobs WHERE file_hash IS NULL").scalar() == 2
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM import_jobs WHERE file_hash = ?", ("a" * 64,)).scalar() == 1


def test_missing_index_is_created_as_unique(migration_db):
    config, engine = migration_db
    command.upgrade(config, PREVIOUS_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {INDEX_NAME}")
        assert index_unique(connection) is None
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert index_unique(connection) is True
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    command.check(config)


def test_duplicate_hash_blocks_repair_without_changing_data_or_index(migration_db):
    config, engine = migration_db
    command.upgrade(config, PREVIOUS_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {INDEX_NAME}")
        connection.exec_driver_sql(f"CREATE INDEX {INDEX_NAME} ON import_jobs(file_hash)")
        insert_job(connection, "first", "b" * 64)
        insert_job(connection, "second", "b" * 64)

    with pytest.raises(RuntimeError, match="重复的文件哈希"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == PREVIOUS_REVISION
        assert index_unique(connection) is False
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM import_jobs WHERE file_hash = ?", ("b" * 64,)).scalar() == 2
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
