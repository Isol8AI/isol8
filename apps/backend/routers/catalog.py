from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.services.catalog_service import CatalogService, get_catalog_service


router = APIRouter(prefix="/catalog", tags=["catalog"])


class DeployRequest(BaseModel):
    slug: str


@router.get("", description="List catalog agents available for one-click deploy.")
async def list_catalog(
    _: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"agents": service.list()}


@router.post(
    "/deploy",
    description="Deploy a catalog agent into the current user's container.",
)
async def deploy(
    req: DeployRequest,
    auth: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.deploy(user_id=auth.user_id, slug=req.slug)


@router.get(
    "/deployed",
    description="List which catalog templates the current user has already deployed.",
)
async def list_deployed(
    auth: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"deployed": service.list_deployed_for_user(auth.user_id)}
