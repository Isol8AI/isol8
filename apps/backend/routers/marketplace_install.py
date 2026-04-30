"""Install validation endpoint for the CLI installer + MCP server."""

import time
from typing import Annotated

import boto3
from fastapi import APIRouter, Header, HTTPException, Request

from core.config import settings
from core.services import license_service, marketplace_service


router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace-install"])


async def _presigned_url(*, listing_id: str, version: int) -> tuple[str, str]:
    """Generate a 5-minute pre-signed S3 URL for the artifact + return SHA."""
    s3 = boto3.client("s3")
    bucket = settings.MARKETPLACE_ARTIFACTS_BUCKET
    key = f"listings/{listing_id}/v{version}/workspace.tar.gz"
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=300,
    )
    listing = await marketplace_service.get_by_id(listing_id=listing_id, version=version)
    return url, (listing or {}).get("manifest_sha256", "")


@router.get("/install/validate")
async def validate_install(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    if not authorization or not authorization.startswith("Bearer iml_"):
        raise HTTPException(status_code=401, detail="missing license key")
    license_key = authorization[len("Bearer ") :]
    source_ip = request.client.host if request.client else "unknown"

    result = await license_service.validate(license_key=license_key, source_ip=source_ip)
    if result.status == "revoked":
        raise HTTPException(status_code=401, detail=f"license revoked: {result.reason}")
    if result.status == "rate_limited":
        raise HTTPException(status_code=429, detail="install rate limit exceeded")
    if result.status != "valid":
        raise HTTPException(status_code=401, detail="invalid license")

    url, sha = await _presigned_url(listing_id=result.listing_id, version=result.listing_version)
    listing = await marketplace_service.get_by_id(listing_id=result.listing_id, version=result.listing_version)
    return {
        "listing_id": result.listing_id,
        "listing_slug": listing["slug"] if listing else "",
        "version": result.listing_version,
        "download_url": url,
        "manifest_sha256": sha,
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 300)),
    }
