from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.api import auth, catalog, configuration, execution, experiments, material_import, measurement, setup, system, workbook_export
from app.core.bootstrap import ensure_bootstrap_token
from app.core.config import Settings, get_settings
from app.core.web import ProductionWeb
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    development = settings.seedlab_env == "development"
    application = FastAPI(
        title="SeedLab API", version=VERSION,
        docs_url="/docs" if development else None, redoc_url=None,
        openapi_url="/openapi.json" if development else None, lifespan=lifespan,
    )
    for router in (setup.router, auth.router, catalog.router, configuration.router,
                   execution.router, measurement.router, experiments.router, system.router,
                   material_import.router, workbook_export.router):
        application.include_router(router, prefix="/api")

    @application.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    if settings.seedlab_env == "production":
        # Last mount: registered API routes always take precedence.
        application.mount("/", ProductionWeb(settings.web_root), name="web")
    return application


app = create_app()
