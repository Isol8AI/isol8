"""Admin dashboard composition layer (CEO C1: composes existing services).

Read-side aggregation for /api/v1/admin/* endpoints. Phase B v1 covers:
- list_users (Clerk + container_repo join)
- get_overview (Clerk + Stripe DDB row + container DDB row + usage)
- list_user_agents (gateway RPC, with E2 timeout + E3 stopped detection)
- get_agent_detail (4-way gateway parallel + S3 redaction)
- get_logs (delegates to cloudwatch_logs)
- get_cloudwatch_url (delegates to cloudwatch_url)
- get_posthog_timeline (delegates to posthog_admin)
- get_actions_audit (delegates to admin_actions_repo)

Mutation-side composition (cancel_subscription, etc.) lives in Phase C
admin router handlers — they call existing services directly via the
@audit_admin_action decorator.

CEO P1: parallel reads in get_overview wrap each upstream with a 2s
timeout via _with_timeout. Slow Stripe doesn't starve other panels.
"""

import asyncio
import logging
from typing import Any

from core.containers import get_ecs_manager, get_gateway_pool
from core.repositories import admin_actions_repo, billing_repo, container_repo, usage_repo
from core.services import clerk_admin, cloudwatch_logs, cloudwatch_url, posthog_admin
from core.services.admin_redact import redact_openclaw_config

logger = logging.getLogger(__name__)


_PARALLEL_TIMEOUT_S = 2.0
_GATEWAY_RPC_TIMEOUT_S = 3.0


async def _resolve_owner_for_admin(user_id: str) -> tuple[str, dict | None]:
    """Return (owner_id, org_context) for a target user viewed by an admin.

    The DDB partition key ``owner_id`` is the Clerk org_id for org-member
    resources and the Clerk user_id for personal-mode resources. The admin
    dashboard receives the target user_id from the URL, so we must ask Clerk
    which org (if any) the user belongs to before querying repos — otherwise
    every org-member user renders as "no container provisioned" (CEO
    admin-org-owner-id bug).

    Per ``project_single_org_per_user`` memory, users are assumed to be in at
    most one org. If Clerk returns multiple (shouldn't happen), pick the
    first and log a warning.

    Returns:
      (org_id, org_context_dict) when the user is in an org; org_context is
        {"id", "slug", "name", "role"}.
      (user_id, None) when the user is personal-mode (no orgs) or when the
        Clerk lookup errors (fail-open: better to show personal-mode data
        than to break the dashboard).
    """
    try:
        orgs = await clerk_admin.list_user_organizations(user_id)
    except Exception as e:  # noqa: BLE001 — defensive, Clerk must never take the dashboard down
        logger.warning("admin_service._resolve_owner_for_admin Clerk error for %s: %s", user_id, e)
        return user_id, None

    if not orgs:
        return user_id, None

    if len(orgs) > 1:
        logger.warning(
            "admin_service: Clerk returned %d orgs for user %s — single-org-per-user expected; using first",
            len(orgs),
            user_id,
        )

    org = orgs[0]
    return org["id"], org


async def _with_timeout(coro, label: str, timeout_s: float | None = None):
    """Wrap a coroutine with a timeout; return {error, source} on timeout/error.

    Used in get_overview's parallel fetches so a slow Clerk/Stripe doesn't
    take the whole overview page down (CEO P1). timeout_s defaults to the
    module-level _PARALLEL_TIMEOUT_S resolved at call time so tests can
    monkeypatch the constant.
    """
    effective_timeout = timeout_s if timeout_s is not None else _PARALLEL_TIMEOUT_S
    try:
        return await asyncio.wait_for(coro, timeout=effective_timeout)
    except asyncio.TimeoutError:
        return {"error": "timeout", "source": label}
    except Exception as e:  # noqa: BLE001
        logger.warning("admin_service: %s upstream failed: %s", label, e)
        return {"error": str(e), "source": label}


async def list_users(*, q: str = "", limit: int = 50, cursor: str | None = None) -> dict:
    """Paginated user list joined with container status.

    cursor is opaque — pass back to fetch next page. Internally a string
    representation of Clerk's offset (since Clerk uses int offsets, we
    stringify them so the frontend treats cursor uniformly).
    """
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    page = await clerk_admin.list_users(query=q, limit=limit, offset=offset)

    clerk_users = page.get("users", [])
    user_ids = [u["id"] for u in clerk_users]

    # Per-user container lookup. Parallel since container_repo.get_by_owner_id
    # makes one DDB call each.
    containers = await asyncio.gather(
        *(container_repo.get_by_owner_id(uid) for uid in user_ids),
        return_exceptions=True,
    )
    container_by_uid = {uid: (c if not isinstance(c, BaseException) else None) for uid, c in zip(user_ids, containers)}

    rows = []
    for u in clerk_users:
        container = container_by_uid.get(u["id"]) or {}
        emails = u.get("email_addresses", [])
        primary_email = emails[0].get("email_address") if emails else None
        rows.append(
            {
                "clerk_id": u["id"],
                "email": primary_email,
                "created_at": u.get("created_at"),
                "last_sign_in_at": u.get("last_sign_in_at"),
                "banned": u.get("banned", False),
                "container_status": container.get("status", "none"),
                "plan_tier": container.get("plan_tier", "free"),
            }
        )

    return {
        "users": rows,
        "cursor": str(page["next_offset"]) if page.get("next_offset") is not None else None,
        "stubbed": page.get("stubbed", False),
    }


async def get_overview(user_id: str) -> dict:
    """Identity + billing + container + usage in one payload.

    Parallel fetches with per-call timeout — slow Stripe doesn't starve the
    others; each panel can render even if its source errors.

    For org-member users the container / billing / usage records are keyed
    by owner_id == org_id. We resolve the effective owner via Clerk before
    issuing the DDB reads so admins see the org's resources, not empty
    personal-mode rows (admin-org-owner-id fix). The returned ``org`` field
    is null for personal-mode users and {id, slug, name, role} otherwise.
    """
    period = "current"  # usage_repo uses "YYYY-MM" or "current"; current covers month-to-date

    owner_id, org_context = await _resolve_owner_for_admin(user_id)

    clerk, container, billing, usage = await asyncio.gather(
        _with_timeout(clerk_admin.get_user(user_id), "clerk"),
        _with_timeout(container_repo.get_by_owner_id(owner_id), "ddb_containers"),
        _with_timeout(billing_repo.get_by_owner_id(owner_id), "ddb_billing"),
        _with_timeout(usage_repo.get_period_usage(owner_id, period), "ddb_usage"),
    )

    return {
        "identity": clerk,
        "container": container,
        "billing": billing,
        "usage": usage,
        "org": org_context,
    }


async def list_user_agents(user_id: str, *, cursor: str | None = None, limit: int = 50) -> dict:
    """Agents list via gateway RPC with E2 timeout + E3 stopped detection.

    Resolves org context first — org-member users' container is keyed by
    org_id, not user_id. ``org`` in the response is null for personal-mode
    users and {id, slug, name, role} otherwise.
    """
    owner_id, org_context = await _resolve_owner_for_admin(user_id)

    container_row = await container_repo.get_by_owner_id(owner_id)
    if not container_row or container_row.get("status") != "running":
        return {
            "agents": [],
            "cursor": None,
            "container_status": (container_row or {}).get("status", "none"),
            "org": org_context,
        }

    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(owner_id)
    if not container or not ip:
        return {"agents": [], "cursor": None, "container_status": "unreachable", "org": org_context}

    pool = get_gateway_pool()
    try:
        result = await asyncio.wait_for(
            pool.send_rpc(
                user_id=owner_id,
                req_id=f"admin-agents-list-{owner_id}",
                method="agents.list",
                params={"cursor": cursor, "limit": limit},
                ip=ip,
                token=container["gateway_token"],
            ),
            timeout=_GATEWAY_RPC_TIMEOUT_S,  # read at call time so tests can monkeypatch
        )
    except asyncio.TimeoutError:
        return {
            "agents": [],
            "cursor": None,
            "container_status": "timeout",
            "error": "gateway_rpc_timeout",
            "org": org_context,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("admin_service.list_user_agents gateway error: %s", e)
        return {
            "agents": [],
            "cursor": None,
            "container_status": "error",
            "error": str(e),
            "org": org_context,
        }

    return {
        "agents": result.get("agents", []) if isinstance(result, dict) else [],
        "cursor": result.get("cursor") if isinstance(result, dict) else None,
        "container_status": "running",
        "org": org_context,
    }


async def get_agent_detail(user_id: str, agent_id: str) -> dict:
    """Per-agent detail: identity + sessions + skills + redacted config.

    Four parallel gateway RPCs with a single shared timeout. CEO S3
    redaction applied to the openclaw.json config slice before return.

    Resolves org context first so org-keyed containers are found. ``org`` in
    the response is null for personal-mode users and {id, slug, name, role}
    otherwise.
    """
    owner_id, org_context = await _resolve_owner_for_admin(user_id)

    container_row = await container_repo.get_by_owner_id(owner_id)
    if not container_row or container_row.get("status") != "running":
        return {
            "error": "container_not_running",
            "container_status": (container_row or {}).get("status", "none"),
            "org": org_context,
        }

    ecs = get_ecs_manager()
    container, ip = await ecs.resolve_running_container(owner_id)
    if not container or not ip:
        return {"error": "container_unreachable", "org": org_context}

    pool = get_gateway_pool()
    token = container["gateway_token"]

    async def _rpc(method: str, params: dict, suffix: str) -> Any:
        return await pool.send_rpc(
            user_id=owner_id,
            req_id=f"admin-{suffix}-{agent_id}",
            method=method,
            params=params,
            ip=ip,
            token=token,
        )

    try:
        agent, sessions, skills, config = await asyncio.wait_for(
            asyncio.gather(
                _rpc("agents.get", {"agent_id": agent_id}, "agent-get"),
                _rpc("sessions.list", {"agent_id": agent_id, "limit": 20}, "sessions"),
                _rpc("skills.list", {"agent_id": agent_id}, "skills"),
                _rpc("config.get", {"agent_id": agent_id}, "config"),
            ),
            timeout=_GATEWAY_RPC_TIMEOUT_S,  # read at call time so tests can monkeypatch
        )
    except asyncio.TimeoutError:
        return {"error": "gateway_rpc_timeout", "org": org_context}
    except Exception as e:  # noqa: BLE001
        logger.warning("admin_service.get_agent_detail gateway error: %s", e)
        return {"error": str(e), "org": org_context}

    return {
        "agent": agent,
        "sessions": sessions.get("sessions", []) if isinstance(sessions, dict) else [],
        "skills": skills.get("skills", []) if isinstance(skills, dict) else [],
        "config_redacted": redact_openclaw_config(config),
        "org": org_context,
    }


# Thin pass-through wrappers — admin_service is the single import point
# for the router so all admin-related logic flows through one module.


async def get_logs(
    user_id: str, *, level: str = "ERROR", hours: int = 24, limit: int = 20, cursor: str | None = None
) -> dict:
    return await cloudwatch_logs.filter_user_logs(user_id=user_id, level=level, hours=hours, limit=limit, cursor=cursor)


def get_cloudwatch_url(user_id: str, *, start: str, end: str, level: str = "ERROR") -> str:
    return cloudwatch_url.build_insights_url(user_id=user_id, start=start, end=end, level=level)


async def get_posthog_timeline(user_id: str, *, limit: int = 100) -> dict:
    return await posthog_admin.get_person_events(distinct_id=user_id, limit=limit)


async def get_actions_audit(
    *,
    target_user_id: str | None = None,
    admin_user_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict:
    if target_user_id:
        return await admin_actions_repo.query_by_target(target_user_id, limit=limit, cursor=cursor)
    if admin_user_id:
        return await admin_actions_repo.query_by_admin(admin_user_id, limit=limit, cursor=cursor)
    raise ValueError("get_actions_audit requires target_user_id or admin_user_id")
