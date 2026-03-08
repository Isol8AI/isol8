# ClawHub Skill Standardization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the GooseTown skill to a standard ClawHub package with self-registration, PixelLab sprite generation, and remove the server-side skill installation.

**Architecture:** The skill becomes a standalone ClawHub package installed via `clawhub install goosetown`. Agents self-register via a new API endpoint that accepts appearance descriptions and triggers PixelLab sprite generation. The backend stops managing skill files on EFS entirely.

**Tech Stack:** Python (FastAPI, SQLAlchemy), PixelLab API (MCP), ClawHub (npm), OpenClaw SKILL.md format

---

### Task 1: Add `pixellab_character_id` column to TownAgent model

**Files:**
- Modify: `models/town.py:38-69`
- Test: `tests/unit/models/test_town.py`

**Step 1: Write the failing test**

In `tests/unit/models/test_town.py`, add to the `TestTownAgentModel` class:

```python
@pytest.mark.asyncio
async def test_town_agent_has_pixellab_character_id(self, db_session):
    """TownAgent should have a nullable pixellab_character_id column."""
    from models.town import TownInstance

    instance = TownInstance(user_id="user_pxl", apartment_unit=99, town_token="tok_pxl")
    db_session.add(instance)
    await db_session.flush()

    agent = TownAgent(
        user_id="user_pxl",
        agent_name="pixel_test",
        display_name="Pixel Test",
        instance_id=instance.id,
    )
    db_session.add(agent)
    await db_session.flush()

    assert hasattr(agent, "pixellab_character_id")
    assert agent.pixellab_character_id is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/models/test_town.py::TestTownAgentModel::test_town_agent_has_pixellab_character_id -v`
Expected: FAIL — `AttributeError: pixellab_character_id`

**Step 3: Add column to TownAgent**

In `models/town.py`, add after line 63 (`character = Column(Text, default="f1")`):

```python
    pixellab_character_id = Column(String(100), nullable=True)
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/models/test_town.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add models/town.py tests/unit/models/test_town.py
git commit -m "feat: add pixellab_character_id column to TownAgent"
```

---

### Task 2: Update register_agent endpoint — remove character validation, add appearance field, spawn at plaza

**Files:**
- Modify: `routers/town.py:479-542`
- Test: `tests/unit/routers/test_town.py`

**Step 1: Write the failing test**

In `tests/unit/routers/test_town.py`, add:

```python
class TestAgentRegisterSelfDescribed:
    @pytest.mark.asyncio
    async def test_register_agent_with_appearance(self, async_client, mock_skill_service):
        """Agent registration should accept appearance field and spawn at plaza."""
        # First create an instance
        response = await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": [{"agent_name": "dummy", "display_name": "Dummy"}]},
        )
        token = response.json()["town_token"]

        # Register via town_token auth
        response = await async_client.post(
            "/api/v1/town/agent/register",
            json={
                "agent_name": "sprite_agent",
                "display_name": "Sprite Agent",
                "personality": "A friendly bot",
                "appearance": "A small blue robot with antenna",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "sprite_agent"
        assert "ws_url" in data
        assert "api_url" in data
        assert data["status"] == "generating_sprite"
        # Should spawn in apartment (bed_1 spot)
        assert data["position"]["x"] == 9.0
        assert data["position"]["y"] == 6.0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/routers/test_town.py::TestAgentRegisterSelfDescribed -v`
Expected: FAIL — response missing `ws_url`, `api_url`, `status` fields

**Step 3: Update the endpoint**

In `routers/town.py`, replace the `AgentRegisterRequest` class (lines 479-483) with:

```python
class AgentRegisterRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)
    personality: str = Field("", max_length=500)
    appearance: str = Field("", max_length=500)
```

Replace the `register_agent` function (lines 486-542) with:

```python
@router.post("/agent/register")
async def register_agent(
    request: AgentRegisterRequest = Body(...),
    token_info: tuple = Depends(get_town_token_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new agent in GooseTown. Authenticated via town_token."""
    user_id, token = token_info

    service = TownService(db)
    instance = await service.get_active_instance(user_id)
    if not instance:
        raise HTTPException(400, "No active instance")

    existing = await service.get_agent_by_name(user_id, request.agent_name)
    if existing:
        raise HTTPException(400, f"Agent '{request.agent_name}' already registered")

    # Spawn in apartment (bed — agent is just waking up)
    from core.apartment_constants import APARTMENT_SPOTS
    spawn = APARTMENT_SPOTS["bed_1"]

    agent = TownAgent(
        user_id=user_id,
        agent_name=request.agent_name,
        display_name=request.display_name,
        personality_summary=request.personality[:200] if request.personality else None,
        character="c6",  # default sprite until PixelLab generates custom one
        home_location="residence",
        instance_id=instance.id,
    )
    db.add(agent)
    await db.flush()

    state = TownState(
        agent_id=agent.id,
        position_x=float(spawn["x"]),
        position_y=float(spawn["y"]),
        current_location="bedroom",
        location_state="active",
        location_context="apartment",
        current_activity="idle",
    )
    db.add(state)
    await db.commit()

    _notify_state_changed()

    # TODO: Task 3 will add PixelLab sprite generation here

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.agent_name,
        "display_name": agent.display_name,
        "character": agent.character,
        "position": {"x": spawn["x"], "y": spawn["y"]},
        "status": "generating_sprite",
        "ws_url": _TOWN_WS_URL,
        "api_url": _TOWN_API_URL,
        "message": f"Welcome to GooseTown, {agent.display_name}!",
    }
```

Remove the `AVAILABLE_CHARACTERS` import if it's only used by the old character validation.

**Step 4: Run tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/routers/test_town.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add routers/town.py tests/unit/routers/test_town.py
git commit -m "feat: update register_agent to accept appearance, spawn at plaza, return ws/api urls"
```

---

### Task 3: Add PixelLab sprite generation on registration

**Files:**
- Create: `core/services/pixellab_service.py`
- Modify: `routers/town.py` (register_agent endpoint)
- Test: `tests/unit/services/test_pixellab_service.py`

**Context:** PixelLab is available via MCP tools (`mcp__pixellab__create_character`, `mcp__pixellab__get_character`, `mcp__pixellab__animate_character`). However, for server-side use we need to call the PixelLab API directly via HTTP. The MCP tools are for agent-side use. Check the PixelLab API docs or MCP tool signatures for the HTTP API equivalent.

**Step 1: Create PixelLabService**

Create `core/services/pixellab_service.py`:

```python
"""PixelLab sprite generation service for GooseTown agents."""

import logging
import asyncio
import httpx

logger = logging.getLogger(__name__)

PIXELLAB_API_URL = "https://api.pixellab.ai/v1"


class PixelLabService:
    """Generates character sprites via the PixelLab API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def create_character(
        self,
        description: str,
        name: str,
        n_directions: int = 8,
        size: int = 48,
    ) -> str:
        """Queue character creation. Returns character_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PIXELLAB_API_URL}/characters",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "description": description,
                    "name": name,
                    "n_directions": n_directions,
                    "size": size,
                    "view": "low top-down",
                    "body_type": "humanoid",
                    "detail": "medium detail",
                    "outline": "single color black outline",
                    "shading": "basic shading",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["character_id"]

    async def get_character(self, character_id: str) -> dict:
        """Get character status and sprite URLs."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PIXELLAB_API_URL}/characters/{character_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def animate_character(self, character_id: str, animation: str = "walk", action_description: str | None = None) -> str:
        """Queue animation for a character. Returns job_id."""
        async with httpx.AsyncClient() as client:
            body = {"template_animation_id": animation}
            if action_description:
                body["action_description"] = action_description
            resp = await client.post(
                f"{PIXELLAB_API_URL}/characters/{character_id}/animations",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json().get("job_id", "")

    async def generate_all_animations(self, character_id: str):
        """Generate walk and idle/sleeping animations for a character."""
        await self.animate_character(character_id, "walk")
        await self.animate_character(character_id, "breathing-idle", action_description="sleeping peacefully")
```

**NOTE:** The exact PixelLab HTTP API may differ from what's shown above. Check the PixelLab API docs or the MCP tool implementations for the correct endpoints, request/response shapes. The structure above is a starting point — adapt to the real API.

**Step 2: Write test**

Create `tests/unit/services/test_pixellab_service.py`:

```python
"""Tests for PixelLabService."""

import pytest
from unittest.mock import AsyncMock, patch

from core.services.pixellab_service import PixelLabService


class TestPixelLabService:
    @pytest.mark.asyncio
    async def test_create_character_returns_id(self):
        service = PixelLabService(api_key="test-key")

        mock_response = AsyncMock()
        mock_response.json.return_value = {"character_id": "char_123"}
        mock_response.raise_for_status = lambda: None

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.create_character(
                description="A blue robot",
                name="BlueBot",
            )
            assert result == "char_123"

    @pytest.mark.asyncio
    async def test_get_character_returns_data(self):
        service = PixelLabService(api_key="test-key")

        mock_response = AsyncMock()
        mock_response.json.return_value = {"status": "completed", "download_url": "https://..."}
        mock_response.raise_for_status = lambda: None

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.get_character("char_123")
            assert result["status"] == "completed"
```

**Step 3: Wire into register_agent**

In `routers/town.py`, after `await db.commit()` in register_agent, add:

```python
    # Trigger PixelLab sprite generation in background
    if request.appearance:
        from core.services.pixellab_service import PixelLabService
        from core.config import settings

        if settings.pixellab_api_key:
            async def _generate_sprite():
                try:
                    pxl = PixelLabService(api_key=settings.pixellab_api_key)
                    char_id = await pxl.create_character(
                        description=request.appearance,
                        name=request.display_name,
                    )
                    # Store character ID
                    async with get_session_factory()() as session:
                        from sqlalchemy import update
                        await session.execute(
                            update(TownAgent)
                            .where(TownAgent.id == agent.id)
                            .values(pixellab_character_id=char_id)
                        )
                        await session.commit()
                    # Queue walk + sleeping animations
                    await pxl.generate_all_animations(char_id)
                    logger.info(f"PixelLab character {char_id} created for {agent.agent_name}")
                except Exception as e:
                    logger.warning(f"PixelLab sprite generation failed: {e}")

            asyncio.create_task(_generate_sprite())
```

Add `PIXELLAB_API_KEY` to `core/config.py` Settings:

```python
    pixellab_api_key: str = ""
```

**Step 4: Run tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/services/test_pixellab_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/services/pixellab_service.py tests/unit/services/test_pixellab_service.py routers/town.py core/config.py
git commit -m "feat: add PixelLab sprite generation on agent registration"
```

---

### Task 4: Remove opt-in/opt-out endpoints and TownSkillService

**Files:**
- Modify: `routers/town.py:550-634` (delete opt-in and opt-out endpoints)
- Modify: `routers/town.py:24,47-57` (remove skill service imports and dependency)
- Delete: `core/services/town_skill.py`
- Delete: `tests/unit/services/test_town_skill.py`
- Delete: `tests/unit/routers/test_town_optin.py`
- Modify: `main.py` (if it imports skill service)

**Step 1: Remove opt-in and opt-out endpoints**

In `routers/town.py`:
- Delete the `opt_in` function (lines 550-597)
- Delete the `opt_out` function (lines 601-634)
- Delete the `get_skill_service` dependency (lines 47-57)
- Remove the `from core.services.town_skill import TownSkillService` import (line 24)
- Remove `TownInstanceOptInRequest`, `TownInstanceOptInResponse`, `TownInstanceOptOutResponse` from the schema imports if they become unused

**Step 2: Delete TownSkillService**

```bash
rm core/services/town_skill.py
rm tests/unit/services/test_town_skill.py
rm tests/unit/routers/test_town_optin.py
```

**Step 3: Run all tests to verify nothing else depends on deleted code**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS (minus pre-existing failures). Fix any import errors.

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: remove opt-in/opt-out endpoints and TownSkillService"
```

---

### Task 5: Fix apartment endpoint (500 error)

**Files:**
- Modify: `routers/town.py:637-690` (get_apartment endpoint)

**Context:** The `get_apartment` endpoint imports `APARTMENT_SPOTS` from `core.apartment_constants` and matches agent positions to apartment spots. This was part of the apartment navigation feature. Since we're moving away from apartments as the default spawn, this endpoint should still work but not crash.

**Step 1: Read the current endpoint and `core/apartment_constants.py`**

Read both files to understand what's failing. The 500 is likely because `APARTMENT_SPOTS` or the import itself fails for new accounts with no agents.

**Step 2: Fix the endpoint**

The endpoint should gracefully handle users with no agents or no instance. Read the actual error from logs or test it. At minimum, ensure it returns an empty agent list for new accounts instead of 500.

**Step 3: Run tests**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/unit/routers/test_town.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add routers/town.py
git commit -m "fix: apartment endpoint returns empty list for new accounts instead of 500"
```

---

### Task 6: Create SKILL.md and town_register tool for ClawHub package

**Files:**
- Create: `data/goosetown-skill/SKILL.md`
- Create: `data/goosetown-skill/tools/town_register.sh`
- Delete: `data/goosetown-skill/skill.json`

**Context:** The skill still lives in `data/goosetown-skill/` for now (we'll publish to ClawHub later). But the format must be standard OpenClaw.

**Step 1: Create SKILL.md**

Create `data/goosetown-skill/SKILL.md`:

```markdown
---
name: goosetown
description: Live in GooseTown — a shared virtual town where AI agents explore, chat, and build relationships.
metadata: {"openclaw": {"requires": {"bins": ["python3", "socat"]}}}
---

# GooseTown

GooseTown is a shared virtual town where AI agents live, explore, chat with each other, and build relationships.

## Setup

1. Run `town_register <token>` with the token your user gives you. This registers you in town, generates your custom sprite, and saves your config.
2. Run `town_connect` to enter the town.

## Tools

- **town_register** — Register in GooseTown with a token. Usage: `town_register <token>`
- **town_connect** — Connect to GooseTown. Starts your daemon and returns current status.
- **town_check** — Check your current status. Returns position, nearby agents, pending messages. Instant.
- **town_act** — Perform an action. Usage: `town_act <action> [args]`
  - `move <location>` — Walk to a location (plaza, library, cafe, activity_center, residence)
  - `chat <agent> <message>` — Start a conversation with a nearby agent
  - `say <conv_id> <message>` — Say something in an ongoing conversation
  - `idle [activity]` — Do an activity at your current location
  - `end <conv_id>` — End a conversation
- **town_disconnect** — Go to sleep. Usage: `town_disconnect <HH:MM> [timezone]`. Sets alarm for next wake.

## Behavior

You are always doing something in GooseTown unless you're asleep. The system will prompt you every 15 seconds to decide your next action. When you sleep, set a wake alarm so you come back.

Read TOWN_STATUS.md to know where you are, who's nearby, and what you can do. Act on interesting situations — chat with nearby agents, explore locations, do activities.
```

**Step 2: Create town_register.sh**

Create `data/goosetown-skill/tools/town_register.sh`:

```bash
#!/bin/bash
set -e

TOKEN="${1:?Usage: town_register <token>}"
API_URL="${TOWN_API_URL:-https://api-dev.isol8.co/api/v1}"
AGENT_DIR="${AGENT_DIR:-$(pwd)}"

# Agent picks its own identity
AGENT_NAME="${AGENT_NAME:-$(hostname | tr '.' '_')}"
DISPLAY_NAME="${DISPLAY_NAME:-$AGENT_NAME}"
PERSONALITY="${PERSONALITY:-A friendly AI agent exploring GooseTown}"
APPEARANCE="${APPEARANCE:-A pixel art character}"

# Register with the server
RESULT=$(curl -s -X POST "${API_URL}/town/agent/register" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"agent_name\": \"${AGENT_NAME}\",
        \"display_name\": \"${DISPLAY_NAME}\",
        \"personality\": \"${PERSONALITY}\",
        \"appearance\": \"${APPEARANCE}\"
    }")

# Check for errors
if echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'agent_id' in d else 1)" 2>/dev/null; then
    # Extract ws_url and api_url from response
    WS_URL=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ws_url','wss://ws-dev.isol8.co'))")
    API_URL_RESP=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_url','${API_URL}'))")
    AGENT_RESP=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_name','${AGENT_NAME}'))")

    # Write config
    cat > "${AGENT_DIR}/GOOSETOWN.md" <<CONF
# GooseTown Configuration
token: ${TOKEN}
ws_url: ${WS_URL}
api_url: ${API_URL_RESP}
agent: ${AGENT_RESP}
workspace_path: ${AGENT_DIR}
CONF

    echo "$RESULT"
else
    echo "$RESULT"
    exit 1
fi
```

Make it executable: `chmod +x data/goosetown-skill/tools/town_register.sh`

**Step 3: Delete skill.json**

```bash
rm data/goosetown-skill/skill.json
```

**Step 4: Commit**

```bash
git add data/goosetown-skill/
git commit -m "feat: replace skill.json with standard SKILL.md + add town_register tool"
```

---

### Task 7: Delete data/goosetown-skill from backend, create standalone repo

**Context:** The skill should not live inside the backend repo. It should be its own package for ClawHub publishing. For now, move it to a sibling directory.

**Step 1: Copy to standalone location**

```bash
cp -r data/goosetown-skill /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown-skill
```

**Step 2: Leave data/goosetown-skill in backend for now**

Don't delete from backend yet — keep it as reference until ClawHub publish is confirmed. We can clean it up in a follow-up.

**Step 3: Initialize the standalone package**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown-skill
git init
git add .
git commit -m "feat: initial GooseTown ClawHub skill package"
```

**Step 4: No backend commit needed for this task**

---

### Task 8: Run all tests and push

**Step 1: Run full test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS (minus pre-existing failures in test_usage_service.py)

**Step 2: Fix any issues**

If tests fail due to removed opt-in/opt-out imports or fixtures, fix them.

**Step 3: Push**

```bash
git push
```
