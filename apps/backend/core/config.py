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

    # Tool proxy (Perplexity search, etc.)
    PERPLEXITY_API_KEY: str = os.getenv("PERPLEXITY_API_KEY", "")
    PROXY_BASE_URL: str = os.getenv("PROXY_BASE_URL", "https://api.isol8.co/api/v1/proxy")

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
