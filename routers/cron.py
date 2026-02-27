"""
Cron job management API for user's OpenClaw container.

Requires a dedicated container — returns 404 for free-tier users.
All operations exec commands inside the user's Docker container.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
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


class CronJobCreate(BaseModel):
    schedule: str
    task: str
    enabled: bool = True
    agent: Optional[str] = None
    channel: Optional[str] = None
    delivery: Optional[str] = None


class CronJobUpdate(BaseModel):
    schedule: Optional[str] = None
    task: Optional[str] = None
    enabled: Optional[bool] = None
    agent: Optional[str] = None
    channel: Optional[str] = None
    delivery: Optional[str] = None


@router.get(
    "",
    summary="List cron jobs",
    description="Lists all scheduled cron jobs in the user's container.",
    operation_id="list_cron_jobs",
    responses={404: {"description": "No container (free tier)"}},
)
async def list_cron_jobs(auth: AuthContext = Depends(get_current_user)):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "cron", "list", "--json"])
    try:
        jobs = json.loads(raw)
    except json.JSONDecodeError:
        jobs = []
    return {"jobs": jobs}


@router.post(
    "",
    summary="Create cron job",
    description="Creates a new scheduled cron job.",
    operation_id="create_cron_job",
    responses={404: {"description": "No container (free tier)"}},
)
async def create_cron_job(
    body: CronJobCreate,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    cmd = ["openclaw", "cron", "add", "--schedule", body.schedule, "--task", body.task, "--json"]
    if body.agent:
        cmd.extend(["--agent", body.agent])
    if body.channel:
        cmd.extend(["--channel", body.channel])
    if body.delivery:
        cmd.extend(["--delivery", body.delivery])
    if not body.enabled:
        cmd.append("--disabled")
    raw = _exec(auth.user_id, cmd)
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        job = {"status": "created"}
    return {"job": job}


@router.put(
    "/{cron_id}",
    summary="Update cron job",
    description="Updates a cron job's schedule or configuration.",
    operation_id="update_cron_job",
    responses={404: {"description": "No container (free tier)"}},
)
async def update_cron_job(
    cron_id: str,
    body: CronJobUpdate,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    cmd = ["openclaw", "cron", "edit", "--id", cron_id, "--json"]
    if body.schedule is not None:
        cmd.extend(["--schedule", body.schedule])
    if body.task is not None:
        cmd.extend(["--task", body.task])
    if body.enabled is not None:
        cmd.append("--enabled" if body.enabled else "--disabled")
    raw = _exec(auth.user_id, cmd)
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        job = {"id": cron_id, "status": "updated"}
    return {"job": job}


@router.delete(
    "/{cron_id}",
    status_code=204,
    summary="Delete cron job",
    description="Deletes a cron job.",
    operation_id="delete_cron_job",
    responses={404: {"description": "No container (free tier)"}},
)
async def delete_cron_job(
    cron_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    _exec(auth.user_id, ["openclaw", "cron", "delete", "--id", cron_id])
    return Response(status_code=204)


@router.post(
    "/{cron_id}/run",
    summary="Run cron job now",
    description="Manually triggers a cron job.",
    operation_id="run_cron_job",
    responses={404: {"description": "No container (free tier)"}},
)
async def run_cron_job(
    cron_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "cron", "run", "--id", cron_id, "--json"])
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"status": "triggered"}
    return {"result": result}


@router.get(
    "/{cron_id}/history",
    summary="Get cron run history",
    description="Returns run history for a cron job.",
    operation_id="get_cron_history",
    responses={404: {"description": "No container (free tier)"}},
)
async def get_cron_history(
    cron_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    _require_container(auth.user_id)
    raw = _exec(auth.user_id, ["openclaw", "cron", "history", "--id", cron_id, "--json"])
    try:
        history = json.loads(raw)
    except json.JSONDecodeError:
        history = []
    return {"history": history}
