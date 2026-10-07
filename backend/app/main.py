from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth, catalog, configuration, execution, experiments, material_import, measurement, setup, system, workbook_export
from app.api.errors import application_error_handler
from app.contracts.errors import ApplicationError
from app.core.bootstrap import ensure_bootstrap_token
from app.core.config import Settings, get_settings
from app.core.web import ProductionWeb
from app.db.session import make_engine
from app.version import VERSION


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        engine = make_engine(settings.seedlab_database_url)
        _app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with Session(engine) as db:
                ensure_bootstrap_token(db, settings)
            yield
        finally:
            engine.dispose()

    development = settings.seedlab_env == "development"
    application = FastAPI(
        title="SeedLab API", version=VERSION,
        docs_url="/docs" if development else None, redoc_url=None,
        openapi_url="/openapi.json" if development else None, lifespan=lifespan,
    )
    application.state.settings = settings
    application.add_exception_handler(ApplicationError, application_error_handler)
    for router in (setup.router, auth.router, catalog.router, configuration.router,
                   execution.router, measurement.router, experiments.router, system.router,
                   material_import.router, workbook_export.router):
        application.include_router(router, prefix="/api")

    @application.get("/api/health")
    def health(request: Request):
        result = {"status": "ok", "version": VERSION}
        runtime = settings.seedlab_runtime_info
        # Public probes keep the existing response. Only this deployment's
        # local control credential can read filesystem/runtime information.
        if runtime and secrets.compare_digest(request.headers.get("X-SeedLab-Control", "").encode(),
                                              runtime["probe_token"].encode()):
            result.update({key: value for key, value in runtime.items() if key != "probe_token"})
        return result

    if settings.seedlab_env == "production":
        # Last mount: registered API routes always take precedence.
        application.mount("/", ProductionWeb(settings.web_root), name="web")
    return application


app = create_app()
