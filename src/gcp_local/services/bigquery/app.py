from fastapi import FastAPI

from gcp_local.services.bigquery.engine.jobs import JobRunner
from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.routes.jobs import (
    build_router as jobs_router,
)
from gcp_local.services.bigquery.routes.tabledata import (
    build_router as tabledata_router,
)
from gcp_local.services.bigquery.routes.tables import (
    build_router as tables_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage, runner: JobRunner) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    app.include_router(jobs_router(runner))
    app.include_router(tabledata_router(storage))
    return app
