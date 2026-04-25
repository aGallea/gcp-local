from fastapi import FastAPI

from gcp_local.services.bigquery.routes.datasets import (
    build_router as datasets_router,
)
from gcp_local.services.bigquery.routes.tables import (
    build_router as tables_router,
)
from gcp_local.services.bigquery.storage import BigQueryStorage


def build_app(storage: BigQueryStorage) -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    app.include_router(datasets_router(storage))
    app.include_router(tables_router(storage))
    return app
