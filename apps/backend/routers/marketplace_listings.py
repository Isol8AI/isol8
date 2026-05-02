"""Marketplace listings public + creator endpoints."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from core.auth import AuthContext, get_current_user
from core.containers import get_workspace
from core.repositories import billing_repo
from core.services import (
    agent_export,
    marketplace_search,
    marketplace_service,
    skillmd_adapter,
)
from schemas import marketplace as schemas


router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


# Tier strings that grant openclaw publishing.
_PAID_TIERS = {"starter", "pro", "enterprise"}

# Cap on multipart body size — slightly above the unzipped cap to allow for
# compression headroom. Larger requests rejected with 413 before parse.
_MAX_ARTIFACT_BODY_BYTES = 10 * 1024 * 1024


@router.get("/listings")
async def list_listings(
    response: Response,
    tags: str | None = Query(default=None, description="Comma-separated tags"),
    limit: int = Query(default=24, ge=1, le=100),
):
    """Public browse + search. CloudFront caches for 60s."""
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=60"
    if tags:
        query_tags = [t.strip() for t in tags.split(",") if t.strip()]
        items = await marketplace_search.search(query_tags=query_tags, limit=limit)
    else:
        items = await marketplace_search.browse(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/listings/{slug}")
async def get_listing(slug: str, response: Response):
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=60"
    listing = await marketplace_service.get_by_slug(slug=slug)
    if not listing or listing["status"] in ("retired", "taken_down"):
        raise HTTPException(status_code=404, detail="listing not found")
    return listing


@router.post("/listings")
async def create_listing(
    payload: schemas.ListingCreate,
    auth: Annotated[AuthContext, Depends(get_current_user)],
):
    """Create a draft listing (requires authenticated seller)."""
    try:
        listing = await marketplace_service.create_draft(
            seller_id=auth.user_id,
            slug=payload.slug,
            name=payload.name,
            description_md=payload.description_md,
            format=payload.format,
            delivery_method=payload.delivery_method,
            price_cents=payload.price_cents,
            tags=payload.tags,
            artifact_bytes=b"",  # uploaded separately; this is the metadata create
            manifest={"name": payload.name, "description": payload.description_md},
        )
    except marketplace_service.SlugCollisionError:
        raise HTTPException(status_code=409, detail="slug already taken")
    return listing


@router.post("/listings/{listing_id}/submit")
async def submit(
    listing_id: str,
    auth: Annotated[AuthContext, Depends(get_current_user)],
):
    """Transition draft -> review."""
    try:
        result = await marketplace_service.submit_for_review(listing_id=listing_id, seller_id=auth.user_id)
    except marketplace_service.ArtifactNotUploadedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


# ---------------------------------------------------------------------------
# Artifact upload — Path A (zip from laptop) and Path B (snapshot from EFS)
# ---------------------------------------------------------------------------


@router.post("/listings/{listing_id}/artifact", response_model=schemas.ArtifactUploadResponse)
async def upload_artifact(
    listing_id: str,
    auth: Annotated[AuthContext, Depends(get_current_user)],
    file: UploadFile = File(..., description="ZIP containing SKILL.md + companion files"),
):
    """Upload zipped SKILL.md skill content for a draft listing (Path A).

    Body: multipart form-data with a single ``file`` field holding the zip.
    Validates and unpacks the zip server-side, runs the SKILL.md adapter
    (which validates frontmatter + paths), packs into the catalog tarball
    format, replaces the listing's S3 artifact, and flips
    artifact_uploaded=True on the listing row.
    """
    body = await file.read()
    if len(body) > _MAX_ARTIFACT_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {_MAX_ARTIFACT_BODY_BYTES // (1024 * 1024)} MB",
        )

    try:
        files = skillmd_adapter.unpack_zip_and_normalize(body)
    except skillmd_adapter.ZipValidationError as e:
        raise HTTPException(status_code=400, detail=f"zip validation failed: {e}")

    try:
        package = skillmd_adapter.pack_skillmd(files)
    except skillmd_adapter.PathRejectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except skillmd_adapter.FrontmatterError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await marketplace_service.replace_artifact(
            listing_id=listing_id,
            seller_id=auth.user_id,
            artifact_bytes=package.tarball_bytes,
            manifest=package.manifest,
        )
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return schemas.ArtifactUploadResponse(
        listing_id=result["listing_id"],
        version=result["version"],
        manifest_sha256=result["manifest_sha256"],
        file_count=len(package.tarball_contents),
        bytes=len(package.tarball_bytes),
    )


@router.post(
    "/listings/{listing_id}/artifact-from-agent",
    response_model=schemas.ArtifactUploadResponse,
)
async def upload_artifact_from_agent(
    listing_id: str,
    payload: schemas.ArtifactFromAgentRequest,
    auth: Annotated[AuthContext, Depends(get_current_user)],
):
    """Snapshot one of the seller's existing OpenClaw agents (Path B).

    Body: ``{ agent_id }``. Reads ``/mnt/efs/users/{seller}/agents/{agent_id}/``
    directly from EFS (no container interaction), tars the directory, packs
    it as a CatalogPackage, and replaces the listing's artifact.

    Requires the seller to be on a paid tier (free-tier users have no
    container, so no agents on EFS to publish).
    """
    # Tier gate. Free-tier users (or unbilled accounts) cannot publish
    # OpenClaw agents — they have nothing on EFS to snapshot.
    account = await billing_repo.get_by_owner_id(auth.user_id)
    tier = (account or {}).get("tier", "none")
    if tier not in _PAID_TIERS:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "publishing OpenClaw agents requires Isol8 Starter, Pro, or Enterprise",
                "current_tier": tier,
                "upgrade_url": "https://isol8.co/pricing",
            },
        )

    try:
        package = agent_export.export_agent_from_efs(seller_id=auth.user_id, agent_id=payload.agent_id)
    except agent_export.InvalidAgentIdError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except agent_export.AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = await marketplace_service.replace_artifact(
            listing_id=listing_id,
            seller_id=auth.user_id,
            artifact_bytes=package.tarball_bytes,
            manifest=package.manifest,
        )
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return schemas.ArtifactUploadResponse(
        listing_id=result["listing_id"],
        version=result["version"],
        manifest_sha256=result["manifest_sha256"],
        file_count=len(package.tarball_contents),
        bytes=len(package.tarball_bytes),
    )


# ---------------------------------------------------------------------------
# Seller surfacing — agent picker + tier gate
# ---------------------------------------------------------------------------


@router.get("/my-agents", response_model=schemas.MyAgentsResponse)
async def my_agents(auth: Annotated[AuthContext, Depends(get_current_user)]):
    """List the caller's existing OpenClaw agents on EFS for the publish picker.

    Returns empty list (200) if the seller has no container or no agents
    yet — the storefront UI shows a friendly empty state.
    """
    workspace = get_workspace()
    try:
        agent_ids = workspace.list_agents(auth.user_id)
    except Exception:
        # EFS read failures should not break the publish UI.
        return schemas.MyAgentsResponse(items=[])

    items: list[schemas.AgentSummary] = []
    for aid in agent_ids:
        agent_dir = workspace.user_path(auth.user_id) / "agents" / aid
        try:
            mtime = datetime.fromtimestamp(agent_dir.stat().st_mtime, tz=timezone.utc)
        except OSError:
            mtime = None
        items.append(schemas.AgentSummary(agent_id=aid, name=aid, updated_at=mtime))
    return schemas.MyAgentsResponse(items=items)


@router.get("/seller-eligibility", response_model=schemas.SellerEligibilityResponse)
async def seller_eligibility(auth: Annotated[AuthContext, Depends(get_current_user)]):
    """Surface whether the caller can publish each format.

    The /sell form calls this on mount and gates the format dropdown.
    Cheap (single billing repo lookup); UI calls it on every mount so a
    user who upgrades mid-session sees the new option immediately.
    """
    account = await billing_repo.get_by_owner_id(auth.user_id)
    tier = (account or {}).get("tier", "none")
    can_openclaw = tier in _PAID_TIERS
    return schemas.SellerEligibilityResponse(
        tier=tier,
        can_sell_skillmd=True,  # any signed-in user
        can_sell_openclaw=can_openclaw,
        reason=None
        if can_openclaw
        else "Publishing OpenClaw agents requires an Isol8 Starter, Pro, or Enterprise subscription.",
    )
