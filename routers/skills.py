"""
Skills management API for user's OpenClaw container.

Requires a dedicated container — returns 404 for free-tier users.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.containers import get_container_manager
from core.containers.manager import ContainerError

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_container(user_id: str) -> int:
    cm = get_container_manager()
    port = cm.get_container_port(user_id)
    if not port:
        raise HTTPException(status_code=404, detail="No container found. Upgrade to a paid plan.")
    return port


def _exec(user_id: str, command: list[str]) -> str:
    cm = get_container_manager()
    try:
        return cm.exec_command(user_id, command)
    except ContainerError as e:
        logger.error("Container exec failed for user %s: %s", user_id, e)
        raise HTTPException(status_code=502, detail="Container command failed")


class SkillToggle(BaseModel):
    enabled: bool


@router.get(
    "",
    summary="List skills",
    description="Lists all available skills and their status.",
    operation_id="list_skills",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_skills(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "skill", "list", "--json"])
    try:
        skills = json.loads(raw)
    except json.JSONDecodeError:
        skills = []
    return {"skills": skills}


@router.post(
    "/{skill_name}/install",
    summary="Install skill",
    description="Installs a skill in the user's container.",
    operation_id="install_skill",
    responses={404: {"description": "No container (free tier)"}},
)
async def install_skill(
    skill_name: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "skill", "install", skill_name, "--json"])
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"status": "installed"}
    return {"result": result}


@router.put(
    "/{skill_name}",
    summary="Enable or disable skill",
    description="Toggles a skill's enabled state.",
    operation_id="toggle_skill",
    responses={404: {"description": "No container (free tier)"}},
)
async def toggle_skill(
    skill_name: str,
    body: SkillToggle,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    action = "enable" if body.enabled else "disable"
    _exec(auth.user_id, ["openclaw", "skill", action, skill_name])
    return {"skill": skill_name, "enabled": body.enabled}
