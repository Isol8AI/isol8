# Remove Platform-Provided Perplexity Search

**Date:** 2026-04-12
**Status:** Draft
**Approach:** Full removal (Approach A)

## Summary

Remove the platform-provided Perplexity search proxy and all supporting infrastructure. Users who want web search bring their own Perplexity API key via the existing BYOK system. OpenClaw's built-in provider auto-detection handles the rest — search defaults to enabled and automatically discovers any configured provider credentials.

## Motivation

The platform currently proxies Perplexity API calls on behalf of all users using a shared API key. This is a cost the platform absorbs. Users should instead provide their own key, which the existing BYOK system already supports.

## Design

### What gets removed

**Backend — proxy router:**
- Delete `routers/proxy.py` (the entire file)
- Delete `tests/unit/routers/test_proxy.py`
- `main.py`: remove the proxy router import, `app.include_router(proxy.router, ...)`, and the `"proxy"` OpenAPI tag

**Backend — config:**
- `core/config.py`: remove `PERPLEXITY_API_KEY` and `PROXY_BASE_URL` settings

**Backend — container config generation (`core/containers/config.py`):**
- Remove the `search_plugin` dict (lines 265-278) that builds the perplexity plugin entry using `gateway_token` and `proxy_base_url`
- Remove `**search_plugin` spread from `plugins.entries` (line 417)
- Remove `tools.web.search` from the generated config (lines 389-392) — omit entirely, do not set `enabled: false`
- Keep `tools.web.fetch` as-is
- Remove `proxy_base_url` parameter from the `write_openclaw_config()` function signature
- Update the docstring to remove proxy_base_url references

**Backend — ECS manager (`core/containers/ecs_manager.py`):**
- Remove `proxy_base_url=settings.PROXY_BASE_URL` from the `write_openclaw_config()` call (line 993)

**Backend — localstack env:**
- `.env.localstack`: remove `PROXY_BASE_URL` entry

**CDK infrastructure:**
- `apps/infra/lib/stacks/auth-stack.ts`: remove `perplexityApiKey` from `AuthSecrets` interface and the `createSecret("PerplexityApiKey", "perplexity_api_key")` call
- `apps/infra/lib/stacks/service-stack.ts`: remove `perplexityApiKey` from `SecretNames` interface and the `PERPLEXITY_API_KEY` ECS secret injection
- `apps/infra/lib/local-stage.ts`: remove `perplexity_api_key` from secret seed values and `perplexityApiKey` from secret names prop
- `apps/infra/lib/isol8-stage.ts`: remove `perplexityApiKey` from secret names prop
- `localstack/init/ready.d/01-seed.sh`: remove `isol8/local/perplexity_api_key` secret seed

**Frontend:**
- `apps/frontend/src/components/landing/Skills.tsx`: remove the "Installed" badge from the Perplexity entry (keep the entry itself — it's still a supported skill via BYOK)

**Tests:**
- `tests/unit/routers/test_proxy.py`: delete
- `tests/unit/containers/test_config.py`: update assertions — remove expectations for `search.provider == "perplexity"`, `plugins.entries.perplexity`, and `tools.web.search` in the generated config

### What stays (BYOK path)

- `core/services/key_service.py` — BYOK encryption/decryption/patching for perplexity keys
- `routers/settings_keys.py` — BYOK API key CRUD endpoints
- `apps/frontend/src/components/control/panels/SkillsPanel.tsx` — BYOK UI with `PERPLEXITY_API_KEY` mapping
- `tests/unit/services/test_key_service.py` — BYOK tests

### Why omitting `tools.web.search` is safe

OpenClaw's `resolveWebSearchEnabled()` returns `true` by default when the config key is absent. Its `resolveWebSearchProviderId()` auto-detects providers by scanning for available credentials. When a user adds a BYOK Perplexity key, OpenClaw discovers it and enables search automatically. If no credentials exist, the agent simply can't use the search tool — no error at startup, just a runtime error if the tool is invoked.

### Installed skills count

The landing page shows "Installed (6)" — this should be decremented to "Installed (5)" since Perplexity is no longer platform-provided.

## Rollout

This is a breaking change for users who currently rely on platform-provided search. On next container config update (Track 1 silent patch or re-provision), search will stop working unless the user has added their own key. No migration needed — the old config on EFS will continue to point at the now-dead proxy URL, which will 404. Users add their own key via Settings > API Keys to restore search.

## Out of scope

- Adding other search providers (Tavily, Serper, etc.) to the BYOK system
- Any changes to OpenClaw's search auto-detection logic
- Notifying users about the change (product/comms decision)
