import os

from pydantic import field_validator
from pydantic_settings import BaseSettings

from core.services.bedrock_discovery import discover_models


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
    OPENCLAW_IMAGE: str = os.getenv("OPENCLAW_IMAGE", "ghcr.io/openclaw/openclaw:v2026.3.24")

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

# Billing plan budgets in microdollars (1 microdollar = $0.000001)
PLAN_BUDGETS = {
    "free": 2_000_000,  # $2
    "starter": 25_000_000,  # $25
    "pro": 75_000_000,  # $75
}

# Fallback models used when Bedrock discovery is unavailable (e.g., local dev without AWS creds).
FALLBACK_MODELS = [
    # Claude
    {"id": "us.anthropic.claude-opus-4-6-v1", "name": "Claude Opus 4.6"},
    {"id": "us.anthropic.claude-opus-4-5-20251101-v1:0", "name": "Claude Opus 4.5"},
    {"id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "name": "Claude Sonnet 4.5"},
    {"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "name": "Claude Haiku 4.5"},
    # DeepSeek
    {"id": "us.deepseek.r1-v1:0", "name": "DeepSeek R1"},
    # Meta
    {"id": "us.meta.llama3-3-70b-instruct-v1:0", "name": "Llama 3.3 70B"},
    # Amazon
    {"id": "us.amazon.nova-pro-v1:0", "name": "Amazon Nova Pro"},
    {"id": "us.amazon.nova-lite-v1:0", "name": "Amazon Nova Lite"},
    # OpenAI (GPT-OSS)
    {"id": "us.openai.gpt-oss-120b-1:0", "name": "GPT-OSS 120B"},
    {"id": "us.openai.gpt-oss-20b-1:0", "name": "GPT-OSS 20B"},
    # Qwen
    {"id": "us.qwen.qwen3-235b-a22b-2507-v1:0", "name": "Qwen3 235B"},
    {"id": "us.qwen.qwen3-32b-v1:0", "name": "Qwen3 32B"},
    # Mistral
    {"id": "us.mistral.mistral-large-2512-v1:0", "name": "Mistral Large 3"},
]


def get_available_models() -> list[dict[str, str]]:
    """Get available models via Bedrock discovery, falling back to hardcoded list."""
    if not settings.BEDROCK_ENABLED:
        return FALLBACK_MODELS
    models = discover_models(region=settings.AWS_REGION)
    return models if models else FALLBACK_MODELS
