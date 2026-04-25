from fastapi import FastAPI


def build_app() -> FastAPI:
    app = FastAPI(title="gcp-local BigQuery", version="0.0.1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "bigquery", "status": "ok"}

    return app
