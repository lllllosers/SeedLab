from fastapi import FastAPI

from app.api import auth, catalog, experiments, system
from app.core.config import get_settings
from app.version import VERSION


settings = get_settings()
app = FastAPI(title="SeedLab API", version=VERSION, docs_url="/docs" if settings.seedlab_env == "development" else None,
              redoc_url=None)
app.include_router(auth.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(experiments.router, prefix="/api")
app.include_router(system.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}
