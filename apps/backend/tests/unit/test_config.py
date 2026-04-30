"""Tests for core.config Settings.

Each test instantiates a fresh `Settings()` locally rather than reloading the
`core.config` module. Reloading mutates the module-level `settings` singleton
that other tests in the same pytest session import; that pollution caused
unrelated suites (e.g. test_workspace_catalog_helpers) to fail when they ran
after this file. Local-instantiation keeps the global pristine.
"""

import os

# Match the codebase pattern (e.g. test_admin_org_resolution.py): seed CLERK_ISSUER
# before any `core.*` import so Settings() instantiation in conftest doesn't fail
# when this file is run in isolation.
os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import patch  # noqa: E402

from core.config import Settings  # noqa: E402


@patch.dict(os.environ, {"MARKETPLACE_LISTINGS_TABLE": "isol8-dev-marketplace-listings"})
def test_marketplace_listings_table_env_var_loaded():
    settings = Settings()
    assert settings.MARKETPLACE_LISTINGS_TABLE == "isol8-dev-marketplace-listings"


@patch.dict(os.environ, {"MARKETPLACE_ARTIFACTS_BUCKET": "isol8-dev-marketplace-artifacts"})
def test_marketplace_artifacts_bucket_env_var_loaded():
    settings = Settings()
    assert settings.MARKETPLACE_ARTIFACTS_BUCKET == "isol8-dev-marketplace-artifacts"


@patch.dict(os.environ, {"STRIPE_CONNECT_REFRESH_URL": "https://example.com/refresh"})
def test_stripe_connect_refresh_url_loaded():
    settings = Settings()
    assert settings.STRIPE_CONNECT_REFRESH_URL == "https://example.com/refresh"
