from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import AuthContext, require_platform_admin
from core.services.admin_audit import audit_admin_action
from core.services.catalog_service import CatalogService, get_catalog_service


router = APIRouter(prefix="/admin/catalog", tags=["admin", "catalog"])


class PublishRequest(BaseModel):
    agent_id: str
    slug: str | None = None
    description: str | None = None


@router.post(
    "/publish",
    description="Package an agent from the admin's EFS workspace and upload it to the shared catalog bucket.",
)
@audit_admin_action(
    "catalog.publish",
    target_user_id_override="__catalog__",
)
async def publish(
    req: PublishRequest,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.publish(
        admin_user_id=auth.user_id,
        agent_id=req.agent_id,
        slug_override=req.slug,
        description_override=req.description,
    )


@router.get(
    "",
    description="Admin view of the catalog: live entries with manifest preview + retired entries.",
)
async def list_all(
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return service.list_all()


@router.post(
    "/{slug}/unpublish",
    description="Soft-delete a catalog slug. Moves the slug to catalog.json's retired list; S3 artifacts preserved.",
)
@audit_admin_action(
    "catalog.unpublish",
    target_user_id_override="__catalog__",
)
async def unpublish(
    slug: str,
    request: Request,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    try:
        return await service.unpublish(admin_user_id=auth.user_id, slug=slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{slug}/versions",
    description="List every published version of a catalog slug.",
)
async def list_versions(
    slug: str,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"versions": service.list_versions(slug)}
