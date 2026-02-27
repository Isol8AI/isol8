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
    CLERK_WEBHOOK_SECRET: str | None = os.getenv("CLERK_WEBHOOK_SECRET")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/securechat")

    # Clerk Secret Key (for fetching user/org metadata)
    CLERK_SECRET_KEY: str | None = os.getenv("CLERK_SECRET_KEY")

    # AWS Configuration
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_ENABLED: bool = os.getenv("BEDROCK_ENABLED", "true").lower() == "true"

    # Tool API Keys (passed to OpenClaw gateway)
    BRAVE_API_KEY: str = os.getenv("BRAVE_API_KEY", "")

    # CORS Configuration (comma-separated origins; deployed values set by Terraform)
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS as comma-separated list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # Per-user container configuration
    CONTAINERS_ROOT: str = os.getenv("CONTAINERS_ROOT", "/var/lib/isol8/containers")
    OPENCLAW_IMAGE: str = os.getenv("OPENCLAW_IMAGE", "ghcr.io/openclaw/openclaw:latest")
    CONTAINER_PORT_START: int = int(os.getenv("CONTAINER_PORT_START", "19000"))
    CONTAINER_PORT_END: int = int(os.getenv("CONTAINER_PORT_END", "19999"))

    # WebSocket Configuration (API Gateway Management API)
    WS_CONNECTIONS_TABLE: str = os.getenv("WS_CONNECTIONS_TABLE", "isol8-websocket-connections")
    WS_MANAGEMENT_API_URL: str = os.getenv("WS_MANAGEMENT_API_URL", "")  # Set by Terraform

    # Billing / Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_METER_ID: str = os.getenv("STRIPE_METER_ID", "")
    BILLING_MARKUP: float = float(os.getenv("BILLING_MARKUP", "1.4"))

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
    "starter": 15_000_000,  # $15
    "pro": 45_000_000,  # $45
    "usage_only": 0,  # No included budget
}

FREE_TIER_LIMIT = PLAN_BUDGETS["free"]

# Fallback models used when Bedrock discovery is unavailable (e.g., local dev without AWS creds).
FALLBACK_MODELS = [
    {"id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "name": "Claude 3.5 Sonnet"},
    {"id": "us.anthropic.claude-3-5-haiku-20241022-v1:0", "name": "Claude 3.5 Haiku"},
    {"id": "us.anthropic.claude-3-opus-20240229-v1:0", "name": "Claude 3 Opus"},
    {"id": "us.meta.llama3-3-70b-instruct-v1:0", "name": "Llama 3.3 70B"},
    {"id": "us.meta.llama3-1-70b-instruct-v1:0", "name": "Llama 3.1 70B"},
    {"id": "us.amazon.nova-pro-v1:0", "name": "Amazon Nova Pro"},
    {"id": "us.amazon.nova-lite-v1:0", "name": "Amazon Nova Lite"},
]


def get_available_models() -> list[dict[str, str]]:
    """Get available models via Bedrock discovery, falling back to hardcoded list."""
    from core.services.bedrock_discovery import discover_models

    models = discover_models(region=settings.AWS_REGION)
    return models if models else FALLBACK_MODELS
