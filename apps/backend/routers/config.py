"""Config router — unified EFS-write endpoint for openclaw.json patches.

Wraps patch_openclaw_config. Derives owner_id from the auth context,
enforces org_admin for org callers, and tier-gates channel-related
patches behind Starter+.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import (
    AuthContext,
    get_current_user,
    require_org_admin,
    resolve_owner_id,
)
from core.containers.config import read_openclaw_config_from_efs
from core.repositories import billing_repo
from core.services.config_patcher import (
    ConfigPatchError,
    patch_openclaw_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ConfigPatchBody(BaseModel):
    patch: dict


def _patch_touches_channels(patch: dict) -> bool:
    """Return True if the patch modifies any channels.<provider>.* fields.

    A top-level `channels` key alone is fine (e.g., the initial scaffold);
    we only care if the caller is trying to configure channel accounts,
    tokens, bindings, etc.
    """
    if not isinstance(patch, dict):
        return False
    channels = patch.get("channels")
    if not isinstance(channels, dict) or not channels:
        return False
    # Any non-empty nested dict under channels.* means an actual config
    for _provider, provider_cfg in channels.items():
        if isinstance(provider_cfg, dict) and provider_cfg:
            return True
    return False


async def _check_token_collision(owner_id: str, patch: dict) -> None:
    """Raise 409 token_already_assigned_to_other_agent if the patch introduces
    a botToken that already exists under a different accounts.<agent_id> entry
    in the owner's openclaw.json.
    """
    channels = patch.get("channels")
    if not isinstance(channels, dict):
        return

    # Collect (provider, agent_id, token) tuples in the patch
    patch_tokens: list[tuple[str, str, str]] = []
    for provider, provider_cfg in channels.items():
        if not isinstance(provider_cfg, dict):
            continue
        accounts = provider_cfg.get("accounts")
        if not isinstance(accounts, dict):
            continue
        for agent_id, account_cfg in accounts.items():
            if not isinstance(account_cfg, dict):
                continue
            token = account_cfg.get("botToken")
            if isinstance(token, str) and token.strip():
                patch_tokens.append((provider, agent_id, token.strip()))

    if not patch_tokens:
        return

    current = await read_openclaw_config_from_efs(owner_id) or {}
    current_channels = current.get("channels", {}) if isinstance(current, dict) else {}

    for provider, incoming_agent, incoming_token in patch_tokens:
        provider_cfg = current_channels.get(provider, {})
        if not isinstance(provider_cfg, dict):
            continue
        existing_accounts = provider_cfg.get("accounts", {})
        if not isinstance(existing_accounts, dict):
            continue
        for existing_agent, existing_cfg in existing_accounts.items():
            if existing_agent == incoming_agent:
                continue  # same agent, overwrite is fine
            if not isinstance(existing_cfg, dict):
                continue
            if existing_cfg.get("botToken") == incoming_token:
                raise HTTPException(
                    status_code=409,
                    detail="token_already_assigned_to_other_agent",
                )


@router.patch(
    "",
    summary="Patch the caller's openclaw.json config",
    description=(
        "Deep-merges the patch into the caller's owner_id openclaw.json on EFS. "
        "Derives owner_id from auth context (org_id if org, else user_id). "
        "Requires org_admin for org callers. Tier-gates locked fields via config_policy."
    ),
)
async def patch_config(
    body: ConfigPatchBody,
    auth: AuthContext = Depends(get_current_user),
):
    require_org_admin(auth)
    owner_id = resolve_owner_id(auth)

    # Resolve tier and simulate the merged config to apply policy to the
    # final state, not to the isolated patch (which might only toggle a
    # scaffold flag while keeping the locked field legal).
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if isinstance(account, dict) else "free"

    current = await read_openclaw_config_from_efs(owner_id) or {}
    merged = _deep_merge_for_policy(current, body.patch)

    from core.services import config_policy

    violations = config_policy.evaluate(merged, tier)
    if violations:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "policy_violation",
                "fields": [v["field"] for v in violations],
                "reason": violations[0]["reason"],
            },
        )

    # Bot-token collision pre-check (channels-specific; runs only if patch touches channels).
    if _patch_touches_channels(body.patch):
        await _check_token_collision(owner_id, body.patch)

    try:
        await patch_openclaw_config(owner_id, body.patch)
    except ConfigPatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "patched", "owner_id": owner_id}


def _deep_merge_for_policy(base: dict, patch: dict) -> dict:
    """Local deep-merge matching config_patcher._deep_merge semantics —
    dicts merge recursively, non-dict values replace. Kept local to avoid
    importing a private helper."""
    import copy

    result = copy.deepcopy(base) if not isinstance(base, dict) else dict(base)
    if not isinstance(patch, dict):
        return patch
    for k, v in patch.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_for_policy(result[k], v)
        else:
            import copy as _c

            result[k] = _c.deepcopy(v)
    return result
