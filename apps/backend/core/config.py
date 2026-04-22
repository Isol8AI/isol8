import os

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Isol8"
    API_V1_STR: str = "/api/v1"

    # Environment mode
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "")

    # Clerk Auth
    CLERK_ISSUER: str = os.getenv("CLERK_ISSUER", "https://your-clerk-domain.clerk.accounts.dev")
    CLERK_AUDIENCE: str | None = None

    # DynamoDB
    DYNAMODB_TABLE_PREFIX: str = os.getenv("DYNAMODB_TABLE_PREFIX", "isol8-dev-")
    DYNAMODB_ENDPOINT_URL: str | None = os.getenv("DYNAMODB_ENDPOINT_URL", None)

    # Clerk Secret Key (for fetching user/org metadata)
    CLERK_SECRET_KEY: str | None = os.getenv("CLERK_SECRET_KEY")

    # Clerk Webhook Secret (svix signing secret for verifying Clerk webhook payloads)
    CLERK_WEBHOOK_SECRET: str | None = os.getenv("CLERK_WEBHOOK_SECRET")

    # AWS Configuration
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_ENABLED: bool = os.getenv("BEDROCK_ENABLED", "true").lower() == "true"

    # CORS Configuration (comma-separated origins; deployed values set by Terraform)
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS as comma-separated list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # --- ECS Fargate ---
    ECS_CLUSTER_ARN: str = os.getenv("ECS_CLUSTER_ARN", "")
    ECS_TASK_DEFINITION: str = os.getenv("ECS_TASK_DEFINITION", "")
    ECS_SUBNETS: str = os.getenv("ECS_SUBNETS", "")  # comma-separated
    ECS_SECURITY_GROUP_ID: str = os.getenv("ECS_SECURITY_GROUP_ID", "")

    # --- Cloud Map ---
    CLOUD_MAP_NAMESPACE_ID: str = os.getenv("CLOUD_MAP_NAMESPACE_ID", "")
    CLOUD_MAP_SERVICE_ID: str = os.getenv("CLOUD_MAP_SERVICE_ID", "")
    CLOUD_MAP_SERVICE_ARN: str = os.getenv("CLOUD_MAP_SERVICE_ARN", "")

    # --- EFS ---
    EFS_MOUNT_PATH: str = os.getenv("EFS_MOUNT_PATH", "/mnt/efs/users")
    EFS_FILE_SYSTEM_ID: str = os.getenv("EFS_FILE_SYSTEM_ID", "")

    # --- S3 Config ---
    S3_CONFIG_BUCKET: str = os.getenv("S3_CONFIG_BUCKET", "")
    AGENT_CATALOG_BUCKET: str = os.getenv("AGENT_CATALOG_BUCKET", "")

    # --- Platform admin ---
    # Comma-separated Clerk user IDs allowed to call /admin/catalog/publish
    # AND every endpoint under /api/v1/admin/* (the admin dashboard).
    # v1 is env-driven rather than org-role-driven because "platform admin"
    # (Isol8 team) is distinct from "org admin" (customer admin of a
    # customer org). See require_platform_admin in core/auth.py.
    PLATFORM_ADMIN_USER_IDS: str = os.getenv("PLATFORM_ADMIN_USER_IDS", "")

    # --- Admin dashboard (v1, see #351) ---
    # Master switch — false means /admin/* returns 404 from the Next.js
    # middleware. Flip true on a per-environment basis to expose the surface.
    ADMIN_UI_ENABLED: bool = os.getenv("ADMIN_UI_ENABLED", "false").lower() == "true"

    # Per-user opt-in allowlist for staged rollout. When non-empty, only
    # listed Clerk user IDs see the admin UI even when ADMIN_UI_ENABLED=true.
    # Comma-separated. Empty string = open to every PLATFORM_ADMIN_USER_IDS member.
    ADMIN_UI_ENABLED_USER_IDS: str = os.getenv("ADMIN_UI_ENABLED_USER_IDS", "")

    # Whether to write an audit row for every read-only admin GET
    # (e.g. /admin/users/{id}/overview). Default true so PII viewing
    # leaves a trail. Disable to reduce DDB write volume in dev.
    ADMIN_AUDIT_VIEWS: bool = os.getenv("ADMIN_AUDIT_VIEWS", "true").lower() == "true"

    # --- PostHog (server-side, distinct from NEXT_PUBLIC_POSTHOG_KEY) ---
    # Used by core/services/posthog_admin.py to query the Persons API for the
    # admin dashboard's Activity tab. Empty defaults so the admin client
    # stubs gracefully (returns {events: [], stubbed: true}) when unset —
    # local dev works without a real PostHog project.
    POSTHOG_HOST: str = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
    POSTHOG_PROJECT_ID: str = os.getenv("POSTHOG_PROJECT_ID", "")
    POSTHOG_PROJECT_API_KEY: str = os.getenv("POSTHOG_PROJECT_API_KEY", "")

    @property
    def admin_ui_enabled_user_ids(self) -> set[str]:
        """Parsed allowlist for ADMIN_UI_ENABLED_USER_IDS."""
        raw = self.ADMIN_UI_ENABLED_USER_IDS or ""
        return {u.strip() for u in raw.split(",") if u.strip()}

    # --- IAM ---
    CONTAINER_EXECUTION_ROLE_ARN: str = os.getenv("CONTAINER_EXECUTION_ROLE_ARN", "")

    # --- OpenClaw ---
    # The container image is pinned in openclaw-version.json at the repo root
    # and imported directly by the CDK container stack. No env var override
    # in production — bump the JSON file to upgrade.

    # WebSocket Configuration (API Gateway Management API)
    WS_CONNECTIONS_TABLE: str = os.getenv("WS_CONNECTIONS_TABLE", "isol8-websocket-connections")
    WS_MANAGEMENT_API_URL: str = os.getenv("WS_MANAGEMENT_API_URL", "")  # Set by Terraform

    # Billing / Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_METER_ID: str = os.getenv("STRIPE_METER_ID", "")
    BILLING_MARKUP: float = float(os.getenv("BILLING_MARKUP", "1.4"))

    # Encryption (base64-encoded 32-byte key for Fernet encryption of BYOK API keys)
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")

    # KMS CMK ARN/alias for per-container secrets (operator device private keys,
    # gateway tokens). Provisioned by CDK as `alias/isol8-{env}-container-secrets`.
    # Backend calls kms:Encrypt at provision time and kms:Decrypt at handshake
    # time — both operations are audited via CloudTrail so we have a per-call
    # record of which backend instance touched which container's secrets.
    CONTAINER_SECRETS_KMS_KEY_ID: str = os.getenv("CONTAINER_SECRETS_KMS_KEY_ID", "")

    # Free tier default model
    FREE_TIER_MODEL: str = os.getenv("FREE_TIER_MODEL", "minimax.minimax-m2.5")

    @field_validator("CLERK_ISSUER")
    @classmethod
    def validate_clerk_issuer(cls, v: str) -> str:
        if "your-clerk-domain" in v:
            raise ValueError("CLERK_ISSUER not configured. Set the CLERK_ISSUER environment variable.")
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Tier configuration
TIER_CONFIG = {
    "free": {
        "included_budget_microdollars": 2_000_000,  # $2 lifetime
        "budget_type": "lifetime",
        "primary_model": "amazon-bedrock/minimax.minimax-m2.5",
        "subagent_model": "amazon-bedrock/minimax.minimax-m2.5",
        "model_aliases": {
            "amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"},
        },
        "container_cpu": "512",
        "container_memory": "1024",
        "scale_to_zero": True,
    },
    "starter": {
        "included_budget_microdollars": 10_000_000,  # $10/mo
        "budget_type": "monthly",
        "primary_model": "amazon-bedrock/qwen.qwen3-vl-235b-a22b",
        "subagent_model": "amazon-bedrock/minimax.minimax-m2.5",
        "model_aliases": {
            "amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"},
            "amazon-bedrock/qwen.qwen3-vl-235b-a22b": {"alias": "Qwen3 VL 235B"},
        },
        "container_cpu": "512",
        "container_memory": "1024",
        "scale_to_zero": False,
    },
    "pro": {
        "included_budget_microdollars": 40_000_000,  # $40/mo
        "budget_type": "monthly",
        "primary_model": "amazon-bedrock/qwen.qwen3-vl-235b-a22b",
        "subagent_model": "amazon-bedrock/minimax.minimax-m2.5",
        "model_aliases": {
            "amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"},
            "amazon-bedrock/qwen.qwen3-vl-235b-a22b": {"alias": "Qwen3 VL 235B"},
        },
        "container_cpu": "1024",
        "container_memory": "2048",
        "scale_to_zero": False,
    },
    "enterprise": {
        "included_budget_microdollars": 80_000_000,  # $80/mo
        "budget_type": "monthly",
        "primary_model": "amazon-bedrock/qwen.qwen3-vl-235b-a22b",
        # Per product rule (2026-04-09): MiniMax is the subagent model on every
        # paid tier, not just starter/pro. Enterprise used to clone the primary
        # for the subagent; we've unified.
        "subagent_model": "amazon-bedrock/minimax.minimax-m2.5",
        "model_aliases": {
            "amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"},
            "amazon-bedrock/qwen.qwen3-vl-235b-a22b": {"alias": "Qwen3 VL 235B"},
        },
        "container_cpu": "2048",
        "container_memory": "4096",
        "scale_to_zero": False,
    },
}
