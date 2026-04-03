# Load environment variables FIRST, before any other imports
from dotenv import load_dotenv

load_dotenv()

import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from core.auth import get_current_user
from core.config import settings
from core.containers import startup_containers, shutdown_containers
from routers import (
    billing,
    channels,
    container,
    container_recover,
    container_rpc,
    control_ui_proxy,
    debug,
    desktop_auth,
    integrations,
    proxy,
    settings_keys,
    updates,
    users,
    websocket_chat,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    import asyncio

    from core.containers import get_gateway_pool
    from core.services.update_service import run_scheduled_worker

    # Startup
    logger.info("Starting application...")
    await startup_containers()
    worker_task = asyncio.create_task(run_scheduled_worker())

    async def _safe_idle_checker():
        try:
            pool = get_gateway_pool()
            await pool.run_idle_checker()
        except Exception:
            logger.warning("Idle checker not available (gateway pool init failed)")

    idle_checker_task = asyncio.create_task(_safe_idle_checker())

    yield

    # Shutdown
    logger.info("Shutting down application...")
    idle_checker_task.cancel()
    worker_task.cancel()
    try:
        await idle_checker_task
    except asyncio.CancelledError:
        pass
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await shutdown_containers()


openapi_tags = [
    {
        "name": "users",
        "description": "User registration and sync.",
    },
    {
        "name": "websocket",
        "description": "WebSocket connect, disconnect, and message endpoints (API Gateway integration).",
    },
    {
        "name": "billing",
        "description": "Billing, usage tracking, and subscription management.",
    },
    {
        "name": "container",
        "description": "OpenClaw container RPC proxy for the control panel.",
    },
    {
        "name": "control-ui",
        "description": "Proxy for the embedded OpenClaw control UI SPA.",
    },
    {
        "name": "proxy",
        "description": "Proxy for external tool APIs (Perplexity, etc.).",
    },
    {
        "name": "channels",
        "description": "Messaging channel management (Telegram, Discord, WhatsApp).",
    },
    {
        "name": "integrations",
        "description": "MCP server and ClawHub integration management.",
    },
    {
        "name": "debug",
        "description": "Dev-only container provisioning.",
    },
    {
        "name": "health",
        "description": "Root and health check endpoints for verifying API availability.",
    },
]

app = FastAPI(
    title="Isol8 API",
    description=(
        "AI agent platform powered by OpenClaw. Personal agents with persistent memory and streaming LLM inference."
    ),
    version="2.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=None if settings.ENVIRONMENT == "prod" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "prod" else "/redoc",
    servers=(
        [{"url": "https://api-dev.isol8.co", "description": "Development"}]
        if settings.ENVIRONMENT == "dev"
        else [{"url": "https://api.isol8.co", "description": "Production"}]
        if settings.ENVIRONMENT == "prod"
        else [
            {"url": "http://localhost:8000", "description": "Local development"},
            {"url": "https://api-dev.isol8.co", "description": "Development"},
        ]
    ),
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

# Proxy-headers middleware — ALB terminates TLS and forwards X-Forwarded-Proto.
# Without this, FastAPI generates http:// URLs in redirects (e.g. redirect_slashes),
# which breaks clients behind HTTPS.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


def custom_openapi():
    """Override OpenAPI schema generation to inject BearerAuth security scheme."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

# Routes
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])

# WebSocket routes (API Gateway WebSocket -> HTTP POST)
app.include_router(websocket_chat.router, prefix="/api/v1/ws")

# Billing routes
app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])

# Container lifecycle management (GET /status, POST /retry)
app.include_router(container.router, prefix="/api/v1/container", tags=["container"])

# Container RPC proxy & file uploads (POST /rpc, POST /gateway/restart, POST /files)
app.include_router(container_rpc.router, prefix="/api/v1/container", tags=["container"])

# Container recovery (state-aware recover endpoint)
app.include_router(container_recover.router, prefix="/api/v1/container", tags=["container"])

# Container updates (pending updates, apply/schedule)
app.include_router(updates.router, prefix=f"{settings.API_V1_STR}/container", tags=["container"])

# Control UI proxy (embedded OpenClaw control UI SPA)
app.include_router(control_ui_proxy.router, prefix="/api/v1/control-ui", tags=["control-ui"])

# Tool proxy (Perplexity search etc.)
app.include_router(proxy.router, prefix="/api/v1/proxy", tags=["proxy"])

# Channel management (Telegram, Discord, WhatsApp)
app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])

app.include_router(settings_keys.router, prefix="/api/v1/settings/keys", tags=["settings"])

# Integrations (MCP servers, ClawHub)
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])

# Debug routes (dev-only container provisioning)
app.include_router(debug.router, prefix="/api/v1/debug", tags=["debug"])

app.include_router(desktop_auth.router, prefix="/api/v1/auth", tags=["desktop"])


@app.get(
    "/",
    summary="API root",
    description="Returns a welcome message. Useful for verifying the API is reachable.",
    operation_id="root",
    tags=["health"],
)
async def root():
    return {"message": "Welcome to Isol8 API"}


@app.get(
    "/health",
    summary="Health check",
    description=(
        "Validates DynamoDB connectivity. Returns HTTP 200 when healthy, HTTP 503 when unhealthy. "
        "Used by ALB health checks to determine whether to route traffic to this instance."
    ),
    operation_id="health_check",
    tags=["health"],
    responses={
        503: {"description": "DynamoDB connection failed"},
    },
)
async def health_check():
    """Health check for ALB — validates DynamoDB connectivity."""
    try:
        from core.dynamodb import get_table, run_in_thread

        table = get_table("users")
        await run_in_thread(table.load)  # DescribeTable API call
        return {"status": "healthy", "database": "dynamodb"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@app.get(
    "/protected",
    summary="Test authentication",
    description="Returns the authenticated user's ID. Useful for verifying that Clerk JWT authentication is working.",
    operation_id="protected_route",
    tags=["health"],
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
    },
)
async def protected_route(auth=Depends(get_current_user)):
    return {"message": "You are authenticated", "user_id": auth.user_id}
