# Load environment variables FIRST, before any other imports
from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging
from contextlib import asynccontextmanager

from core.observability.logging import configure_logging

configure_logging(level="INFO")

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from core.auth import get_current_user
from core.config import settings
from core.containers import (
    get_ecs_manager,
    get_gateway_pool,
    startup_containers,
    shutdown_containers,
)
from core.observability.e2e_correlation import E2ECorrelationMiddleware
from core.observability.metrics import put_metric
from core.repositories import container_repo
from core.services.update_service import run_scheduled_worker
from routers import (
    admin_catalog,
    billing,
    catalog,
    channels,
    config,
    container,
    container_recover,
    container_rpc,
    control_ui_proxy,
    debug,
    desktop_auth,
    integrations,
    settings_keys,
    updates,
    users,
    webhooks,
    websocket_chat,
    workspace_files,
)

logger = logging.getLogger(__name__)


async def _safe_idle_checker():
    """Run the gateway idle checker with a metric emitted on crash.

    The in-process reaper used to die silently inside this broad except, which
    meant free-tier containers never scaled to zero. Emitting
    ``gateway.idle_checker.crash`` lets a CloudWatch alarm page when the reaper
    dies. The metric emit is itself wrapped in try/except so a metric failure
    can't mask the original reaper crash.
    """
    try:
        pool = get_gateway_pool()
        await pool.run_idle_checker()
    except Exception:
        try:
            put_metric("gateway.idle_checker.crash")
        except Exception:
            pass
        logger.warning("idle checker exited with exception", exc_info=True)


async def _resume_provisioning_transitions() -> None:
    """Resume the provisioning -> running poller for any containers that were
    mid-transition when the backend last shut down.

    ``_await_running_transition`` is an in-process asyncio task — a deploy or
    crash kills it mid-poll. DDB ``status="provisioning"`` is the durable
    marker that the transition hasn't completed; on startup we find those
    rows and re-kick the poller. The poller itself is idempotent (if the
    container is already healthy, the first iteration transitions it to
    running and exits).
    """
    try:
        rows = await container_repo.get_by_status("provisioning")
    except Exception:
        logger.warning("Could not resume provisioning transitions on startup", exc_info=True)
        return

    ecs = get_ecs_manager()
    for row in rows:
        owner_id = row["owner_id"]
        asyncio.create_task(ecs._await_running_transition(owner_id))
        logger.info("Resumed provisioning -> running poller for %s", owner_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting application...")
    await startup_containers()
    await _resume_provisioning_transitions()
    worker_task = asyncio.create_task(run_scheduled_worker())

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

# Request-ID middleware — generates/propagates X-Request-ID for log correlation.
# Added first so it runs innermost (after CORS and ProxyHeaders).
from core.observability.middleware import RequestContextMiddleware

app.add_middleware(RequestContextMiddleware)

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
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-E2E-Run-Id"],
)

# E2E correlation middleware — binds X-E2E-Run-Id header to log context so
# every log line emitted while handling an e2e harness request carries the
# same e2e_run_id field. No-op for traffic that doesn't send the header.
app.add_middleware(E2ECorrelationMiddleware)


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

# Clerk webhook events (user lifecycle)
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])

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

# Channel management (Telegram, Discord, WhatsApp)
app.include_router(channels.router, prefix="/api/v1/channels", tags=["channels"])

# Config patching (unified EFS write endpoint)
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])

app.include_router(settings_keys.router, prefix="/api/v1/settings/keys", tags=["settings"])

# Integrations (MCP servers, ClawHub)
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])

# Workspace file browser (EFS agent workspace)
app.include_router(workspace_files.router, prefix="/api/v1/container", tags=["container"])

# Debug routes (dev-only container provisioning)
app.include_router(debug.router, prefix="/api/v1/debug", tags=["debug"])

app.include_router(desktop_auth.router, prefix="/api/v1/auth", tags=["desktop"])

# Agent catalog (user-facing list/deploy/deployed + admin publish)
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(admin_catalog.router, prefix="/api/v1")


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
