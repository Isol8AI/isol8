"""Tests for the instance-based GooseTown opt-in / opt-out flow.

The new POST /opt-in creates a TownInstance + agents in one shot,
installs the GooseTown skill, and writes per-agent config files.
POST /opt-out reverses everything.

TownSkillService is mocked because it performs filesystem I/O that
requires an EFS mount.
"""

import pytest
from unittest.mock import MagicMock

from core.services.town_skill import TownSkillService
from routers.town import get_skill_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_skill_service(app):
    """Override get_skill_service with a no-op mock."""
    mock_svc = MagicMock(spec=TownSkillService)
    app.dependency_overrides[get_skill_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(get_skill_service, None)


def _opt_in_payload(*agents):
    """Build an instance opt-in request body from (name, display[, summary]) tuples."""
    return {
        "agents": [
            {
                "agent_name": name,
                "display_name": display,
                **({"personality_summary": ps} if ps else {}),
            }
            for name, display, *rest in agents
            for ps in [rest[0] if rest else None]
        ]
    }


# ===========================================================================
# Opt-In Tests
# ===========================================================================


class TestInstanceOptIn:
    """POST /api/v1/town/opt-in — instance-level registration."""

    @pytest.mark.asyncio
    async def test_opt_in_single_agent(self, async_client, db_session, test_user, mock_skill_service):
        """Opt-in with one agent creates instance + agent + calls skill service."""
        response = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("archie", "Archie", "A happy dog")),
        )

        assert response.status_code == 201
        data = response.json()

        # Instance fields
        assert "instance_id" in data
        assert data["apartment_unit"] == 1
        assert isinstance(data["town_token"], str)
        assert len(data["town_token"]) > 10

        # Agent fields
        assert len(data["agents"]) == 1
        agent = data["agents"][0]
        assert agent["agent_name"] == "archie"
        assert agent["display_name"] == "Archie"
        assert agent["personality_summary"] == "A happy dog"
        assert agent["is_active"] is True

        # Skill service calls
        mock_skill_service.install_skill.assert_called_once_with("user_test_123")
        mock_skill_service.write_agent_config.assert_called_once()
        mock_skill_service.append_heartbeat.assert_called_once_with("user_test_123", "archie")

    @pytest.mark.asyncio
    async def test_opt_in_multiple_agents(self, async_client, db_session, test_user, mock_skill_service):
        """Opt-in with multiple agents creates all of them."""
        response = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(
                ("alpha", "Alpha Bot"),
                ("beta", "Beta Bot", "Quiet thinker"),
                ("gamma", "Gamma Bot"),
            ),
        )

        assert response.status_code == 201
        data = response.json()
        assert len(data["agents"]) == 3
        names = [a["agent_name"] for a in data["agents"]]
        assert names == ["alpha", "beta", "gamma"]

        # Skill service: install once, config + heartbeat per agent
        mock_skill_service.install_skill.assert_called_once()
        assert mock_skill_service.write_agent_config.call_count == 3
        assert mock_skill_service.append_heartbeat.call_count == 3

    @pytest.mark.asyncio
    async def test_opt_in_duplicate_instance_rejected(self, async_client, db_session, test_user, mock_skill_service):
        """Second opt-in for the same user returns 400."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("first", "First")),
        )

        response = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("second", "Second")),
        )

        assert response.status_code == 400
        assert "already has an active" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_opt_in_apartment_unit_increments(self, async_client, db_session, test_user, mock_skill_service):
        """Each new instance gets the next apartment unit."""
        # First user opts in
        r1 = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("a1", "Agent 1")),
        )
        assert r1.status_code == 201
        assert r1.json()["apartment_unit"] == 1

        # First user opts out so they can opt in again (different user would be better
        # but we use the same mock auth; just verify the counter).
        await async_client.post("/api/v1/town/opt-out")

        r2 = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("a2", "Agent 2")),
        )
        assert r2.status_code == 201
        # Apartment unit is max(existing) + 1, even if old one deactivated
        assert r2.json()["apartment_unit"] == 2

    @pytest.mark.asyncio
    async def test_opt_in_empty_agents_rejected(self, async_client, db_session, test_user, mock_skill_service):
        """Opt-in with zero agents is rejected by validation."""
        response = await async_client.post(
            "/api/v1/town/opt-in",
            json={"agents": []},
        )
        assert response.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_opt_in_skill_failure_non_fatal(self, async_client, db_session, test_user, mock_skill_service):
        """If skill installation fails, the DB records are still created."""
        mock_skill_service.install_skill.side_effect = FileNotFoundError("no skill source")

        response = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("broken", "Broken Bot")),
        )

        # Endpoint succeeds — skill failure is non-fatal
        assert response.status_code == 201
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_name"] == "broken"


# ===========================================================================
# Opt-Out Tests
# ===========================================================================


class TestInstanceOptOut:
    """POST /api/v1/town/opt-out — instance-level deregistration."""

    @pytest.mark.asyncio
    async def test_opt_out_success(self, async_client, db_session, test_user, mock_skill_service):
        """Opt-out deactivates instance + agents and calls skill service."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("a1", "Agent One"), ("a2", "Agent Two")),
        )
        mock_skill_service.reset_mock()

        response = await async_client.post("/api/v1/town/opt-out")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "opted_out"
        assert data["deactivated_agents"] == 2

        # Skill service: remove config + heartbeat per agent, uninstall once
        assert mock_skill_service.remove_agent_config.call_count == 2
        assert mock_skill_service.strip_heartbeat.call_count == 2
        mock_skill_service.uninstall_skill.assert_called_once_with("user_test_123")

    @pytest.mark.asyncio
    async def test_opt_out_no_instance(self, async_client, db_session, test_user, mock_skill_service):
        """Opt-out without an active instance returns 404."""
        response = await async_client.post("/api/v1/town/opt-out")

        assert response.status_code == 404
        assert "No active GooseTown instance" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_opt_out_idempotent(self, async_client, db_session, test_user, mock_skill_service):
        """Second opt-out returns 404 (already deactivated)."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("x", "X")),
        )

        r1 = await async_client.post("/api/v1/town/opt-out")
        assert r1.status_code == 200

        r2 = await async_client.post("/api/v1/town/opt-out")
        assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_opt_out_skill_failure_non_fatal(self, async_client, db_session, test_user, mock_skill_service):
        """If skill uninstall fails, the DB records are still deactivated."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("y", "Y")),
        )
        mock_skill_service.reset_mock()
        mock_skill_service.remove_agent_config.side_effect = OSError("perm denied")

        response = await async_client.post("/api/v1/town/opt-out")

        # Endpoint succeeds — skill failure is non-fatal
        assert response.status_code == 200
        assert response.json()["deactivated_agents"] == 1


# ===========================================================================
# Round-trip / Integration Tests
# ===========================================================================


class TestOptInOptOutRoundTrip:
    """End-to-end opt-in then opt-out flow."""

    @pytest.mark.asyncio
    async def test_opt_in_then_opt_out_then_opt_in(self, async_client, db_session, test_user, mock_skill_service):
        """User can opt in, opt out, and opt in again with a new token."""
        r1 = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("bot", "Bot")),
        )
        assert r1.status_code == 201
        token1 = r1.json()["town_token"]

        await async_client.post("/api/v1/town/opt-out")

        r2 = await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("bot2", "Bot 2")),
        )
        assert r2.status_code == 201
        token2 = r2.json()["town_token"]

        # Tokens are different
        assert token1 != token2

    @pytest.mark.asyncio
    async def test_agents_appear_in_state_after_opt_in(self, async_client, db_session, test_user, mock_skill_service):
        """After opt-in, agents appear in GET /state (once moved to town context)."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("luna", "Luna"), ("sol", "Sol")),
        )

        # Agents spawn in apartment context; move to town so they appear in /state
        from sqlalchemy import update
        from models.town import TownState

        await db_session.execute(update(TownState).values(location_context="town"))
        await db_session.commit()

        response = await async_client.get("/api/v1/town/state")
        assert response.status_code == 200
        data = response.json()
        assert len(data["world"]["players"]) == 2
        assert len(data["world"]["agents"]) == 2

    @pytest.mark.asyncio
    async def test_agents_disappear_after_opt_out(self, async_client, db_session, test_user, mock_skill_service):
        """After opt-out, agents no longer appear in GET /state (fallback to defaults)."""
        await async_client.post(
            "/api/v1/town/opt-in",
            json=_opt_in_payload(("luna", "Luna")),
        )

        # Move to town context first so we can verify disappearance
        from sqlalchemy import update
        from models.town import TownState

        await db_session.execute(update(TownState).values(location_context="town"))
        await db_session.commit()

        # Verify agent appears
        response = await async_client.get("/api/v1/town/state")
        assert len(response.json()["world"]["players"]) == 1

        await async_client.post("/api/v1/town/opt-out")

        response = await async_client.get("/api/v1/town/state")
        assert response.status_code == 200
        data = response.json()
        # With no active agents, returns empty defaults
        assert len(data["world"]["players"]) == 0
