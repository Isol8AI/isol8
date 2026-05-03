"""Teams BFF — native UI for Paperclip. See spec 2026-05-02."""

from fastapi import APIRouter

from . import agents as _agents
from . import approvals as _approvals
from . import feed as _feed
from . import inbox as _inbox
from . import issues as _issues
from . import work as _work

router = APIRouter(prefix="/teams", tags=["teams"])
router.include_router(_agents.router)
router.include_router(_inbox.router)
router.include_router(_approvals.router)
router.include_router(_issues.router)
router.include_router(_work.router)
router.include_router(_feed.router)
