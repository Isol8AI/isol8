"""Teams BFF — native UI for Paperclip. See spec 2026-05-02."""

from fastapi import APIRouter

from . import agents as _agents

router = APIRouter(prefix="/teams", tags=["teams"])
router.include_router(_agents.router)
