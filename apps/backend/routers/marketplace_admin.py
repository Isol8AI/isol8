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
    """List the marketplace listings currently awaiting moderation.

    Queries the status-published-index GSI for status="review" rows. Returns
    up to 50 newest-first; the admin UI paginates client-side at v0 volume.
    """
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

    First publish (version=1): marketplace_service.approve flips status
    review→published.

    Subsequent versions: when version > 1, derive prev_version automatically
    by reading the listing's history and finding the currently-published
    row. publish_v2 atomically flips prev_version's status published→retired
    AND new version's review→published in one TransactWriteItems. This
    keeps the frontend ignorant of the v_prev concept — the admin just
    approves; the backend figures out which version (if any) to retire.

    `prev_version` query param is retained as a manual override for
    edge cases where the admin wants to be explicit (e.g. tooling that
    wants to fail loudly on race conditions).
    """
    try:
        if version > 1 and prev_version is None:
            # Derive prev_version: the currently-published row of this listing.
            table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
            rows = table.query(
                KeyConditionExpression="listing_id = :l",
                ExpressionAttributeValues={":l": listing_id},
            ).get("Items", [])
            published = next((r for r in rows if r.get("status") == "published"), None)
            if published is not None and int(published["version"]) != version:
                prev_version = int(published["version"])

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


class RejectBody(BaseModel):
    """Body schema for the admin reject endpoint.

    Notes is a body field, not a query param: the admin UI sends
    ``{ notes }`` in JSON (apps/frontend/src/app/admin/_actions/marketplace.ts).
    Declaring `notes: str` as a plain function arg made FastAPI bind it as
    a query param, so every reject from the UI 422'd.
    """

    notes: str = Field(..., min_length=1, max_length=4096)


@router.post("/listings/{listing_id}/reject")
@audit_admin_action(
    "marketplace.reject",
    target_user_id_override="__marketplace__",
    capture_params=["listing_id", "version", "body"],
)
async def reject(
    listing_id: str,
    body: RejectBody,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_platform_admin)],
    version: int = 1,
):
    """Reject a listing version with seller-visible notes.

    Flips status review→draft and persists the moderator's notes on the
    row so the seller can see them on their listing detail page and resubmit.
    """
    try:
        return await marketplace_service.reject(
            listing_id=listing_id, version=version, notes=body.notes, rejected_by=auth.user_id
        )
    except marketplace_service.InvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


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
    # Pick the live (or in-review) version dynamically — admin opens the
    # preview from the review queue, which can hold a v_new=2 row while
    # v_prev=1 is published. Hardcoding version=1 would 404 for any v2+
    # listing the moderator wants to inspect.
    table = boto3.resource("dynamodb").Table(settings.MARKETPLACE_LISTINGS_TABLE)
    rows = table.query(
        KeyConditionExpression="listing_id = :l",
        ExpressionAttributeValues={":l": listing_id},
        ScanIndexForward=False,  # newest version first
    ).get("Items", [])
    if not rows:
        raise HTTPException(status_code=404, detail="listing not found")
    # Prefer the row in 'review' state (the moderation target), then the
    # currently published row, then the highest-version row of any state.
    listing = (
        next((r for r in rows if r.get("status") == "review"), None)
        or next((r for r in rows if r.get("status") == "published"), None)
        or rows[0]
    )

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
            version=int(listing.get("version", 1)),
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
                    # Fail closed: a partial preview means the safety scan
                    # would only see files BEFORE the cutoff, so a malicious
                    # artifact could hide bad files behind padding. Surface
                    # 413 so the moderator knows to reject the upload, not
                    # approve based on incomplete evidence.
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"unpacked preview exceeds {_MAX_PREVIEW_TARBALL_BYTES // (1024 * 1024)} MB cap; "
                            "ask the seller to split the artifact or contact ops to raise the cap"
                        ),
                    )
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
        version=int(listing.get("version", 1)),
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
    try:
        result = await takedown_service.execute_admin_initiated_takedown(
            listing_id=listing_id,
            reason=body.reason,
            basis_md=body.basis_md,
            decided_by=auth.user_id,
        )
    except takedown_service.ListingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
