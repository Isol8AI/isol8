from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthContext, require_platform_admin
from core.services.catalog_service import CatalogService, get_catalog_service


router = APIRouter(prefix="/admin/catalog", tags=["admin", "catalog"])


class PublishRequest(BaseModel):
    agent_id: str
    slug: str | None = None
    description: str | None = None


@router.post("/publish")
async def publish(
    req: PublishRequest,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.publish(
        admin_user_id=auth.user_id,
        agent_id=req.agent_id,
        slug_override=req.slug,
        description_override=req.description,
    )
