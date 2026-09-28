from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.api import auth, catalog, configuration, execution, experiments, setup, system
from app.core.bootstrap import ensure_bootstrap_token
from app.core.config import get_settings
from app.db.session import make_engine
from app.version import VERSION


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine = make_engine(get_settings().seedlab_database_url)
    try:
        with Session(engine) as db:
            ensure_bootstrap_token(db)
    finally:
        engine.dispose()
    yield


settings = get_settings()
app = FastAPI(title="SeedLab API", version=VERSION, docs_url="/docs" if settings.seedlab_env == "development" else None,
              redoc_url=None, lifespan=lifespan)
app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(configuration.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(experiments.router, prefix="/api")
app.include_router(system.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}
