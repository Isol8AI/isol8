"""Unit tests for admin-dashboard settings in core.config.

Covers ADMIN_UI_ENABLED feature flag, ADMIN_UI_ENABLED_USER_IDS allowlist
override (with parsed @property), ADMIN_AUDIT_VIEWS toggle, and
POSTHOG_HOST/POSTHOG_PROJECT_ID/POSTHOG_PROJECT_API_KEY server-side
PostHog secrets.
"""

import os
from unittest.mock import patch


class TestAdminUiSettings:
    def test_admin_ui_enabled_defaults_false(self):
        """v1 ships dark — admin surface returns 404 unless explicitly flipped."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_UI_ENABLED", None)
            from core.config import Settings

            fresh = Settings()
            assert fresh.ADMIN_UI_ENABLED is False

    def test_admin_ui_enabled_reads_env(self):
        with patch.dict(os.environ, {"ADMIN_UI_ENABLED": "true"}):
            from core.config import Settings

            fresh = Settings()
            assert fresh.ADMIN_UI_ENABLED is True

    def test_admin_ui_enabled_user_ids_default_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_UI_ENABLED_USER_IDS", None)
            from core.config import Settings

            fresh = Settings()
            assert fresh.ADMIN_UI_ENABLED_USER_IDS == ""
            assert fresh.admin_ui_enabled_user_ids == set()

    def test_admin_ui_enabled_user_ids_parses_csv(self):
        with patch.dict(
            os.environ,
            {"ADMIN_UI_ENABLED_USER_IDS": "user_alpha, user_beta ,user_gamma"},
        ):
            from core.config import Settings

            fresh = Settings()
            assert fresh.admin_ui_enabled_user_ids == {
                "user_alpha",
                "user_beta",
                "user_gamma",
            }

    def test_admin_ui_enabled_user_ids_skips_empty_entries(self):
        with patch.dict(os.environ, {"ADMIN_UI_ENABLED_USER_IDS": "user_alpha,, ,user_beta"}):
            from core.config import Settings

            fresh = Settings()
            assert fresh.admin_ui_enabled_user_ids == {"user_alpha", "user_beta"}

    def test_admin_audit_views_defaults_true(self):
        """Read endpoints log audit rows by default — admins probing user data leaves a trail."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_AUDIT_VIEWS", None)
            from core.config import Settings

            fresh = Settings()
            assert fresh.ADMIN_AUDIT_VIEWS is True

    def test_admin_audit_views_can_be_disabled(self):
        with patch.dict(os.environ, {"ADMIN_AUDIT_VIEWS": "false"}):
            from core.config import Settings

            fresh = Settings()
            assert fresh.ADMIN_AUDIT_VIEWS is False


class TestPostHogServerSettings:
    def test_posthog_host_defaults_to_us_cloud(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTHOG_HOST", None)
            from core.config import Settings

            fresh = Settings()
            assert fresh.POSTHOG_HOST == "https://app.posthog.com"

    def test_posthog_project_id_defaults_empty(self):
        """Empty defaults make posthog_admin client stub gracefully when unset."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTHOG_PROJECT_ID", None)
            os.environ.pop("POSTHOG_PROJECT_API_KEY", None)
            from core.config import Settings

            fresh = Settings()
            assert fresh.POSTHOG_PROJECT_ID == ""
            assert fresh.POSTHOG_PROJECT_API_KEY == ""

    def test_posthog_settings_reads_env(self):
        with patch.dict(
            os.environ,
            {
                "POSTHOG_HOST": "https://eu.posthog.com",
                "POSTHOG_PROJECT_ID": "12345",
                "POSTHOG_PROJECT_API_KEY": "phc_secret_xyz",
            },
        ):
            from core.config import Settings

            fresh = Settings()
            assert fresh.POSTHOG_HOST == "https://eu.posthog.com"
            assert fresh.POSTHOG_PROJECT_ID == "12345"
            assert fresh.POSTHOG_PROJECT_API_KEY == "phc_secret_xyz"
