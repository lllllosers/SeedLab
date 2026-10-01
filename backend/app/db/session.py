from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from fastapi import Request

def make_engine(url: str):
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            from datetime import datetime
            from app.services.local_time import local_date
            dbapi_connection.create_function("seedlab_local_date", 1,
                lambda value: local_date(datetime.fromisoformat(value)).isoformat() if value else None)
            if ":memory:" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


# Standalone CLI binds this only when a command is invoked. Importing models or
# the desktop wizard must not create a default database directory in Program Root.
SessionLocal = sessionmaker(expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    # SessionLocal remains the standalone CLI's default. HTTP requests must
    # use the database owned by this application's lifespan, never that global.
    with request.app.state.session_factory() as session:
        yield session
