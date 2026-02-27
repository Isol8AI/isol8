"""
Tests for Skills Management API (routers/skills.py).

TDD: Tests written BEFORE implementation.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestListSkills:
    @pytest.mark.asyncio
    @patch("routers.skills.get_container_manager")
    async def test_list_skills(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps(
            [
                {"name": "brave-search", "enabled": True, "installed": True},
                {"name": "github", "enabled": False, "installed": True},
                {"name": "slack", "enabled": False, "installed": False},
            ]
        )
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert len(data["skills"]) == 3

    @pytest.mark.asyncio
    @patch("routers.skills.get_container_manager")
    async def test_list_skills_no_container(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = None
        mock_get_cm.return_value = mock_cm
        response = await async_client.get("/api/v1/skills")
        assert response.status_code == 404


class TestInstallSkill:
    @pytest.mark.asyncio
    @patch("routers.skills.get_container_manager")
    async def test_install_skill(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = json.dumps({"status": "installed"})
        mock_get_cm.return_value = mock_cm
        response = await async_client.post("/api/v1/skills/github/install")
        assert response.status_code == 200


class TestToggleSkill:
    @pytest.mark.asyncio
    @patch("routers.skills.get_container_manager")
    async def test_enable_skill(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.put("/api/v1/skills/github", json={"enabled": True})
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("routers.skills.get_container_manager")
    async def test_disable_skill(self, mock_get_cm, async_client, test_user):
        mock_cm = MagicMock()
        mock_cm.get_container_port.return_value = 19000
        mock_cm.exec_command.return_value = ""
        mock_get_cm.return_value = mock_cm
        response = await async_client.put("/api/v1/skills/github", json={"enabled": False})
        assert response.status_code == 200


class TestSkillsAuth:
    @pytest.mark.asyncio
    async def test_skills_requires_auth(self, unauthenticated_async_client):
        response = await unauthenticated_async_client.get("/api/v1/skills")
        assert response.status_code in (401, 403)
