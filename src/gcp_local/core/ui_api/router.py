"""ui-api FastAPI router. Versioned ``v1``; explicitly internal."""

from fastapi import APIRouter

from gcp_local.core.lifecycle import Lifecycle
from gcp_local.core.ui_api.schemas import PortInfo, ServiceInfo, ServiceList

# Services that have a UI surface in this release. Extended as follow-up specs land.
UI_SUPPORTED_SERVICES = frozenset({"gcs"})


def build_ui_api_router(lc: Lifecycle) -> APIRouter:
    router = APIRouter(prefix="/_emulator/ui-api/v1")

    @router.get("/services", response_model=ServiceList)
    async def list_services() -> ServiceList:
        return ServiceList(
            services=[
                ServiceInfo(
                    name=s.name,
                    ports=[PortInfo(number=p.number, protocol=p.protocol) for p in s.default_ports],
                    ui_supported=s.name in UI_SUPPORTED_SERVICES,
                )
                for s in lc.services
            ],
        )

    return router
