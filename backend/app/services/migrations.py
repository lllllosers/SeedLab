"""Explicit, in-process migration API for source and packaged server layouts."""
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event


def migration_config(script_location, config_path=None):
    location = Path(script_location).resolve()
    if not (location / "env.py").is_file() or not (location / "versions").is_dir():
        raise ValueError("数据库升级文件缺失，请检查程序安装目录。")
    config = Config(str(Path(config_path).resolve()) if config_path else None)
    config.set_main_option("script_location", str(location).replace("%", "%%"))
    config.attributes["skip_logging_config"] = True
    return config


def migration_heads(script_location):
    return tuple(ScriptDirectory.from_config(migration_config(script_location)).get_heads())


@contextmanager
def database_config(database_url, script_location, config_path=None):
    config = migration_config(script_location, config_path)
    # Do not import db.session here: its development global engine is unrelated
    # to a wizard's explicit target database.
    sqlite = database_url.startswith("sqlite")
    engine = create_engine(database_url, connect_args={"timeout": 30} if sqlite else {})
    if sqlite:
        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            config.attributes["database_url"] = database_url
            yield config, connection
    finally:
        engine.dispose()


def upgrade_database(database_url, script_location, config_path=None):
    with database_config(database_url, script_location, config_path) as (config, connection):
        command.upgrade(config, "head")
        current = tuple(MigrationContext.configure(connection).get_current_heads())
        if set(current) != set(migration_heads(script_location)):
            raise RuntimeError("数据库升级后版本检查未通过。")
        return current


def check_database_schema(database_url, script_location, config_path=None):
    with database_config(database_url, script_location, config_path) as (config, _):
        command.check(config)
