"""Admin moderation endpoints — approve, reject, takedown, preview."""

import io
import json
import tarfile
from typing import Annotated, Literal

import boto3
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import AuthContext, require_platform_admin
from core.config import settings
from core.services import marketplace_safety, marketplace_service, takedown_service
from core.services.admin_audit import audit_admin_action
from schemas import marketplace as schemas


router = APIRouter(prefix="/api/v1/admin/marketplace", tags=["marketplace-admin"])

# Cap on tarball size for the in-memory preview extract.
_MAX_PREVIEW_TARBALL_BYTES = 10 * 1024 * 1024


@router.get("/listings")
@audit_admin_action(
    "marketplace.list_review_queue",
    target_user_id_override="__marketplace__",
)
async def review_queue(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
    resp = table.query(
        IndexName="status-published-index",
        KeyConditionExpression="#s = :review",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":review": "review"},
        Limit=50,
    )
    return {"items": resp.get("Items", [])}


@router.post("/listings/{listing_id}/approve")
@audit_admin_action(
    "marketplace.approve",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "version", "prev_version"],
)
async def approve(
    listing_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    version: int = 1,
    prev_version: int | None = None,
):
    """Approve a listing version.

    First publish (default): version=1, no prev_version → marketplace_service.approve
    flips status review→published.

    Subsequent versions: pass version=N and prev_version=M → publish_v2 atomically
    flips prev_version's status published→retired AND new version's review→published
    in one TransactWriteItems.
    """
    try:
        if prev_version is not None:
            await marketplace_service.publish_v2(
                listing_id=listing_id,
                prev_version=prev_version,
                new_version=version,
                approved_by=auth.user_id,
            )
            return {"status": "published", "version": version, "retired_version": prev_version}
        return await marketplace_service.approve(listing_id=listing_id, version=version, approved_by=auth.user_id)
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/listings/{listing_id}/reject")
@audit_admin_action(
    "marketplace.reject",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "version", "notes"],
)
async def reject(
    listing_id: str,
    notes: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    version: int = 1,
):
    return await marketplace_service.reject(
        listing_id=listing_id, version=version, notes=notes, rejected_by=auth.user_id
    )


@router.get(
    "/listings/{listing_id}/preview",
    response_model=schemas.ListingPreviewResponse,
)
@audit_admin_action(
    "marketplace.listing_preview",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id"],
)
async def listing_preview(
    listing_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    """Preview a listing's contents for moderation review.

    Streams the listing's workspace.tar.gz from S3, extracts in-memory
    (capped at 10 MB), runs the safety scan, and returns a structured
    response that the admin UI renders as a file tree + content viewer +
    safety-flag banner.
    """
    table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
    listing = table.get_item(Key={"listing_id": listing_id, "version": 1}).get("Item")
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")

    s3 = boto3.client("s3")
    bucket = settings.MARKETPLACE_ARTIFACTS_BUCKET
    s3_prefix = listing.get("s3_prefix", "")
    tar_key = f"{s3_prefix}workspace.tar.gz"

    try:
        head = s3.head_object(Bucket=bucket, Key=tar_key)
    except Exception:
        # Empty / not-yet-uploaded artifact — return an empty preview rather
        # than 500. The admin UI shows "no artifact uploaded yet".
        return schemas.ListingPreviewResponse(
            listing_id=listing_id,
            slug=listing.get("slug", ""),
            name=listing.get("name", ""),
            seller_id=listing.get("seller_id", ""),
            format=listing.get("format", "openclaw"),
            status=listing.get("status", "draft"),
            price_cents=int(listing.get("price_cents", 0)),
            tags=list(listing.get("tags", [])),
            manifest=listing.get("manifest_json", {}),
            file_tree=[],
            skill_md_text=None,
            openclaw_summary=None,
            safety_flags=[],
        )
    if head.get("ContentLength", 0) > _MAX_PREVIEW_TARBALL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"artifact tarball exceeds {_MAX_PREVIEW_TARBALL_BYTES // (1024 * 1024)} MB preview cap",
        )

    body = s3.get_object(Bucket=bucket, Key=tar_key)["Body"].read()

    file_tree: list[schemas.FileTreeEntry] = []
    file_dict: dict[str, bytes] = {}
    skill_md_text: str | None = None
    openclaw_config: dict | None = None

    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
            total_unpacked = 0
            for m in tf.getmembers():
                if m.issym() or m.islnk():
                    continue  # defense-in-depth; producer side already strips these
                if not m.isfile():
                    continue
                total_unpacked += m.size
                if total_unpacked > _MAX_PREVIEW_TARBALL_BYTES:
                    break
                f = tf.extractfile(m)
                if f is None:
                    continue
                # Strip leading "./" tarballs from catalog_package use.
                clean_name = m.name[2:] if m.name.startswith("./") else m.name
                data = f.read()
                file_tree.append(schemas.FileTreeEntry(path=clean_name, size_bytes=m.size))
                file_dict[clean_name] = data
                if clean_name == "SKILL.md" and skill_md_text is None:
                    try:
                        skill_md_text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        skill_md_text = None
                if clean_name == "openclaw.json" and openclaw_config is None:
                    try:
                        openclaw_config = json.loads(data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        openclaw_config = None
    except tarfile.TarError as e:
        raise HTTPException(status_code=422, detail=f"artifact tarball is not readable: {e}")

    file_tree.sort(key=lambda e: e.path)
    listing_format = listing.get("format", "openclaw")
    flags = marketplace_safety.scan(file_dict, format=listing_format)

    openclaw_summary: schemas.OpenclawSummary | None = None
    if listing_format == "openclaw" and isinstance(openclaw_config, dict):
        tools = openclaw_config.get("tools") or {}
        providers = list((openclaw_config.get("models") or {}).get("providers") or {})
        cron = openclaw_config.get("cron") or {}
        channels = openclaw_config.get("channels") or {}
        agents_block = openclaw_config.get("agents") or {}
        openclaw_summary = schemas.OpenclawSummary(
            tools_count=len(tools) if isinstance(tools, dict) else 0,
            providers=[str(p) for p in providers],
            cron_count=len(cron.get("jobs") or {}) if isinstance(cron, dict) else 0,
            channels_count=sum(len(v.get("accounts") or {}) for v in channels.values() if isinstance(v, dict))
            if isinstance(channels, dict)
            else 0,
            sub_agent_count=len(agents_block.get("sub_agents") or []) if isinstance(agents_block, dict) else 0,
            raw_config_size_bytes=len(file_dict.get("openclaw.json", b"")),
        )

    return schemas.ListingPreviewResponse(
        listing_id=listing_id,
        slug=listing.get("slug", ""),
        name=listing.get("name", ""),
        seller_id=listing.get("seller_id", ""),
        format=listing_format,
        status=listing.get("status", "draft"),
        price_cents=int(listing.get("price_cents", 0)),
        tags=list(listing.get("tags", [])),
        manifest=listing.get("manifest_json", {}),
        file_tree=file_tree,
        skill_md_text=skill_md_text if listing_format == "skillmd" else None,
        openclaw_summary=openclaw_summary,
        safety_flags=[
            schemas.SafetyFlag(
                pattern=f.pattern,
                severity=f.severity,
                file=f.file,
                line=f.line,
                snippet=f.snippet,
            )
            for f in flags
        ],
    )


class AdminTakedownBody(BaseModel):
    """Admin-initiated takedown body.

    Under the Isol8-internal scope there's no public DMCA filing form, so
    the takedown is created and granted in a single admin action: the admin
    types the reason on the listing detail page and submits.
    """

    reason: Literal["dmca", "policy", "fraud", "seller-request"]
    basis_md: str = Field(..., min_length=10, max_length=4096)


@router.post("/listings/{listing_id}/takedown")
@audit_admin_action(
    "marketplace.takedown",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "body"],
)
async def admin_initiated_takedown(
    listing_id: str,
    body: AdminTakedownBody,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    """Admin-initiated takedown.

    Writes the takedown row + cascades license revocation + flips the
    listing's status to `taken_down`, all in one shot. Returns the new
    takedown_id and the count of affected purchases so the UI can show
    confirmation copy.
    """
    result = await takedown_service.execute_admin_initiated_takedown(
        listing_id=listing_id,
        reason=body.reason,
        basis_md=body.basis_md,
        decided_by=auth.user_id,
    )
    return {"status": "taken_down", **result}


@router.get("/takedowns")
@audit_admin_action(
    "marketplace.list_takedowns",
    target_user_id_override="__marketplace__",
)
async def list_takedowns(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
):
    """Recent takedowns, newest first.

    Audit-log view (no `?status=pending` queue — the queue is structurally
    empty under the Isol8-internal scope). v0 volume is very low (< a few
    hundred rows expected for the foreseeable future), so we page through
    the full scan, sort in Python, and slice the top 50. We deliberately do
    NOT cap the scan with `Limit=N` — DDB scans return items in
    unpredictable order, so a capped scan would return "newest of an
    arbitrary subset" rather than the globally newest rows.

    TODO(scale): when takedown volume grows, replace the scan with a query
    against a GSI partitioned on `decision` and sorted by `decided_at`
    (e.g. `decision-decided_at-index`), and drop this Python-side sort.
    """
    table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_TAKEDOWNS_TABLE)
    items: list[dict] = []
    scan_kwargs: dict = {}
    while True:
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last
    # Sort by decided_at desc; rows that somehow lack decided_at sink to the
    # bottom (shouldn't happen for admin-initiated rows, but be defensive).
    items.sort(key=lambda r: r.get("decided_at") or "", reverse=True)
    return {"items": items[:50]}
