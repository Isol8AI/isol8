"""Marketplace listings public + creator endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from core.auth import AuthContext, get_current_user
from core.services import marketplace_search, marketplace_service
from schemas import marketplace as schemas


router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


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
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result
