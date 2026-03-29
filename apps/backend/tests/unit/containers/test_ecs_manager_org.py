"""Tests for org-aware ECS manager operations."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.containers.ecs_manager import EcsManager


class TestServiceNaming:
    def test_personal_service_name(self):
        mgr = EcsManager.__new__(EcsManager)
        name = mgr._service_name("user_abc123")
        assert name.startswith("openclaw-user_abc123-")
        assert len(name) <= 255

    def test_org_service_name(self):
        mgr = EcsManager.__new__(EcsManager)
        name = mgr._service_name("org_xyz789")
        assert name.startswith("openclaw-org_xyz789-")
        assert len(name) <= 255

    def test_different_ids_produce_different_names(self):
        mgr = EcsManager.__new__(EcsManager)
        assert mgr._service_name("user_abc") != mgr._service_name("org_xyz")
