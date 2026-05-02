"""Pydantic schemas for marketplace endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FormatStr = Literal["openclaw", "skillmd"]
DeliveryMethodStr = Literal["cli", "mcp", "both"]
ListingStatusStr = Literal["draft", "review", "published", "retired", "taken_down"]


class ListingCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=80)
    description_md: str = Field(..., min_length=1, max_length=4096)
    format: FormatStr
    delivery_method: DeliveryMethodStr
    price_cents: int = Field(..., ge=0, le=2000)
    tags: list[str] = Field(..., max_length=5)
    category: str | None = None
    suggested_clients: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug_lowercase_kebab(cls, v: str) -> str:
        # Slug must be lowercase alphanumeric + hyphens.
        if not all(c.islower() or c.isdigit() or c == "-" for c in v):
            raise ValueError("slug must be lowercase letters, digits, and hyphens only")
        if v.startswith("-") or v.endswith("-"):
            raise ValueError("slug must not start or end with a hyphen")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_lowercase(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v if t.strip()]

    @model_validator(mode="after")
    def _format_and_delivery_compatible(self) -> "ListingCreate":
        # Plan 1 carve-out: OpenClaw runtime not in v1 MCP. OpenClaw listings
        # cannot select mcp delivery. Use cli OR both — runtime treats both
        # as cli for openclaw format.
        if self.format == "openclaw" and self.delivery_method == "mcp":
            raise ValueError("openclaw format + mcp delivery is unsupported in v1; use delivery_method='cli'")
        return self


class Listing(BaseModel):
    listing_id: str
    slug: str
    name: str
    description_md: str
    format: FormatStr
    delivery_method: DeliveryMethodStr
    price_cents: int
    tags: list[str]
    seller_id: str
    status: ListingStatusStr
    version: int
    created_at: datetime
    published_at: datetime | None
    artifact_format_version: str = "v1"


class CheckoutRequest(BaseModel):
    listing_slug: str
    success_url: str
    cancel_url: str
    email: str | None = None  # required for anonymous (guest) checkout


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class InstallValidateResponse(BaseModel):
    """Returned by GET /install/validate."""

    listing_id: str
    listing_slug: str
    version: int
    download_url: str  # 5-min pre-signed S3 URL
    manifest_sha256: str
    expires_at: datetime


class TakedownRequest(BaseModel):
    reason: Literal["dmca", "policy", "fraud", "seller-request"]
    claimant_name: str
    claimant_email: str
    basis_md: str = Field(..., min_length=10, max_length=4096)


# -- Artifact upload + seller / buyer surfacing --


class ArtifactUploadResponse(BaseModel):
    """Returned by POST /listings/{id}/artifact and /artifact-from-agent."""

    listing_id: str
    version: int
    manifest_sha256: str
    file_count: int
    bytes: int


class ArtifactFromAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=4, max_length=64)


class AgentSummary(BaseModel):
    agent_id: str
    name: str | None = None
    updated_at: datetime | None = None


class MyAgentsResponse(BaseModel):
    items: list[AgentSummary]


class SellerEligibilityResponse(BaseModel):
    tier: str  # "free" | "starter" | "pro" | "enterprise" | "none"
    can_sell_skillmd: bool
    can_sell_openclaw: bool
    reason: str | None = None  # populated when can_sell_openclaw=False


class PurchaseSummary(BaseModel):
    purchase_id: str
    listing_id: str
    listing_slug: str | None = None
    license_key: str
    price_paid_cents: int
    status: Literal["paid", "refunded", "revoked"]
    created_at: str  # ISO8601 string (matches DDB raw value)


class MyPurchasesResponse(BaseModel):
    items: list[PurchaseSummary]


# -- Admin moderation preview --


class FileTreeEntry(BaseModel):
    path: str
    size_bytes: int


class SafetyFlag(BaseModel):
    pattern: str  # short identifier: "curl-bash", "eval", "secret", etc.
    severity: Literal["high", "medium", "low"]
    file: str
    line: int | None = None
    snippet: str  # ~80 char excerpt for the admin UI


class OpenclawSummary(BaseModel):
    tools_count: int = 0
    providers: list[str] = Field(default_factory=list)
    cron_count: int = 0
    channels_count: int = 0
    sub_agent_count: int = 0
    raw_config_size_bytes: int = 0


class ListingPreviewResponse(BaseModel):
    """Returned by GET /admin/marketplace/listings/{id}/preview.

    Backend reads the listing's S3 tarball, extracts in-memory, runs the
    safety scan, and surfaces enough context for an admin to make an
    informed approve/reject call.
    """

    listing_id: str
    slug: str
    name: str
    seller_id: str
    format: FormatStr
    status: ListingStatusStr
    price_cents: int
    tags: list[str]
    manifest: dict
    file_tree: list[FileTreeEntry]
    skill_md_text: str | None = None
    openclaw_summary: OpenclawSummary | None = None
    safety_flags: list[SafetyFlag]
