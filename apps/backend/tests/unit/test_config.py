"""Tests for core.config Settings."""

import importlib
import os
from unittest.mock import patch


@patch.dict(os.environ, {"MARKETPLACE_LISTINGS_TABLE": "isol8-dev-marketplace-listings"})
def test_marketplace_listings_table_env_var_loaded():
    import core.config

    importlib.reload(core.config)
    assert core.config.settings.MARKETPLACE_LISTINGS_TABLE == "isol8-dev-marketplace-listings"


@patch.dict(os.environ, {"MARKETPLACE_ARTIFACTS_BUCKET": "isol8-dev-marketplace-artifacts"})
def test_marketplace_artifacts_bucket_env_var_loaded():
    import core.config

    importlib.reload(core.config)
    assert core.config.settings.MARKETPLACE_ARTIFACTS_BUCKET == "isol8-dev-marketplace-artifacts"


@patch.dict(os.environ, {"STRIPE_CONNECT_REFRESH_URL": "https://example.com/refresh"})
def test_stripe_connect_refresh_url_loaded():
    import core.config

    importlib.reload(core.config)
    assert core.config.settings.STRIPE_CONNECT_REFRESH_URL == "https://example.com/refresh"
