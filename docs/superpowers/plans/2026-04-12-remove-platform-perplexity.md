# Remove Platform-Provided Perplexity Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the platform-provided Perplexity search proxy so users bring their own API key via the existing BYOK system.

**Architecture:** Delete the proxy router, remove the `PERPLEXITY_API_KEY` and `PROXY_BASE_URL` settings, stop injecting search config into container `openclaw.json`, and clean up CDK infrastructure secrets. OpenClaw's built-in provider auto-detection handles search when a user provides their own key.

**Tech Stack:** Python/FastAPI (backend), TypeScript/CDK (infra), Next.js/React (frontend)

---

### Task 1: Delete proxy router and its tests

**Files:**
- Delete: `apps/backend/routers/proxy.py`
- Delete: `apps/backend/tests/unit/routers/test_proxy.py`

- [ ] **Step 1: Delete the proxy router file**

```bash
rm apps/backend/routers/proxy.py
```

- [ ] **Step 2: Delete the proxy router tests**

```bash
rm apps/backend/tests/unit/routers/test_proxy.py
```

- [ ] **Step 3: Commit**

```bash
git add -u apps/backend/routers/proxy.py apps/backend/tests/unit/routers/test_proxy.py
git commit -m "chore: delete Perplexity proxy router and tests"
```

---

### Task 2: Remove proxy router from main.py

**Files:**
- Modify: `apps/backend/main.py:22-39` (import block)
- Modify: `apps/backend/main.py:105-108` (OpenAPI tag)
- Modify: `apps/backend/main.py:225-226` (router registration)

- [ ] **Step 1: Remove `proxy` from the router import block**

In `apps/backend/main.py`, find the import block starting at line 22:

```python
from routers import (
    billing,
    channels,
    config,
    container,
    container_recover,
    container_rpc,
    control_ui_proxy,
    debug,
    desktop_auth,
    integrations,
    proxy,
    settings_keys,
    updates,
    users,
    webhooks,
    websocket_chat,
    workspace_files,
)
```

Remove the `proxy,` line so it becomes:

```python
from routers import (
    billing,
    channels,
    config,
    container,
    container_recover,
    container_rpc,
    control_ui_proxy,
    debug,
    desktop_auth,
    integrations,
    settings_keys,
    updates,
    users,
    webhooks,
    websocket_chat,
    workspace_files,
)
```

- [ ] **Step 2: Remove the proxy OpenAPI tag**

Find this tag dict in the `tags` list (around line 106):

```python
    {
        "name": "proxy",
        "description": "Proxy for external tool APIs (Perplexity, etc.).",
    },
```

Delete it entirely.

- [ ] **Step 3: Remove the proxy router registration**

Find and delete these two lines (around lines 225-226):

```python
# Tool proxy (Perplexity search etc.)
app.include_router(proxy.router, prefix="/api/v1/proxy", tags=["proxy"])
```

- [ ] **Step 4: Run tests to verify no import errors**

Run: `cd apps/backend && uv run python -c "from main import app; print('OK')"`
Expected: `OK` — the app imports cleanly without the proxy module.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/main.py
git commit -m "chore: remove proxy router registration from main.py"
```

---

### Task 3: Remove PERPLEXITY_API_KEY and PROXY_BASE_URL from backend config

**Files:**
- Modify: `apps/backend/core/config.py:33-35`
- Modify: `apps/backend/.env.localstack:67-68`

- [ ] **Step 1: Remove settings from config.py**

In `apps/backend/core/config.py`, find and delete these lines (lines 33-35):

```python
    # Tool proxy (Perplexity search, etc.)
    PERPLEXITY_API_KEY: str = os.getenv("PERPLEXITY_API_KEY", "")
    PROXY_BASE_URL: str = os.getenv("PROXY_BASE_URL", "https://api.isol8.co/api/v1/proxy")
```

- [ ] **Step 2: Remove PROXY_BASE_URL from .env.localstack**

In `apps/backend/.env.localstack`, find and delete these lines (lines 67-68):

```
# Proxy (overridden by docker-compose for Docker DNS)
PROXY_BASE_URL=http://localhost:8000/api/v1/proxy
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/config.py apps/backend/.env.localstack
git commit -m "chore: remove PERPLEXITY_API_KEY and PROXY_BASE_URL settings"
```

---

### Task 4: Remove search config from container config generation

**Files:**
- Modify: `apps/backend/core/containers/config.py:223-231` (function signature)
- Modify: `apps/backend/core/containers/config.py:265-278` (search_plugin block)
- Modify: `apps/backend/core/containers/config.py:389-393` (tools.web.search)
- Modify: `apps/backend/core/containers/config.py:417` (plugins.entries spread)
- Modify: `apps/backend/core/containers/ecs_manager.py:993` (caller)
- Modify: `apps/backend/tests/unit/containers/test_config.py:35-56` (search tests)

- [ ] **Step 1: Update the function signature — remove proxy_base_url**

In `apps/backend/core/containers/config.py`, change the function signature from:

```python
def write_openclaw_config(
    region: str = "us-east-1",
    primary_model: str = "",
    gateway_token: str = "",
    proxy_base_url: str = "https://api.isol8.co/api/v1/proxy",
    provider: str = "bedrock",
    ollama_base_url: str = "",
    tier: str = "free",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        primary_model: Default model for agents.  When empty, derived from
            ``TIER_CONFIG[tier]["primary_model"]``.
        gateway_token: Token used as API key for the search proxy.
        proxy_base_url: Base URL for the tool proxy (Perplexity search, etc.).
        provider: LLM provider to use ("bedrock" or "ollama").
        ollama_base_url: Base URL for Ollama server (e.g. "http://ollama:11434").
        tier: Billing tier -- controls which models are available.
            One of "free", "starter", "pro", "enterprise".

    Returns:
        JSON string of the openclaw.json config.
    """
```

To:

```python
def write_openclaw_config(
    region: str = "us-east-1",
    primary_model: str = "",
    gateway_token: str = "",
    provider: str = "bedrock",
    ollama_base_url: str = "",
    tier: str = "free",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        primary_model: Default model for agents.  When empty, derived from
            ``TIER_CONFIG[tier]["primary_model"]``.
        gateway_token: Shared secret for container auth.
        provider: LLM provider to use ("bedrock" or "ollama").
        ollama_base_url: Base URL for Ollama server (e.g. "http://ollama:11434").
        tier: Billing tier -- controls which models are available.
            One of "free", "starter", "pro", "enterprise".

    Returns:
        JSON string of the openclaw.json config.
    """
```

- [ ] **Step 2: Delete the search_plugin block**

Delete these lines (265-278):

```python
    # Build search plugin config — Perplexity via our proxy (v2026.3.22+ format)
    search_plugin = {}
    if gateway_token:
        search_plugin = {
            "perplexity": {
                "enabled": True,
                "config": {
                    "webSearch": {
                        "apiKey": gateway_token,
                        "baseUrl": f"{proxy_base_url}/search",
                    },
                },
            },
        }
```

- [ ] **Step 3: Remove tools.web.search from the config dict**

Change the `tools.web` block from:

```python
        "tools": {
            "profile": "full",
            "deny": ["canvas", "nodes"],
            "web": {
                "search": {"enabled": bool(gateway_token), "provider": "perplexity"}
                if gateway_token
                else {"enabled": False},
                "fetch": {"enabled": True},
            },
```

To:

```python
        "tools": {
            "profile": "full",
            "deny": ["canvas", "nodes"],
            "web": {
                "fetch": {"enabled": True},
            },
```

- [ ] **Step 4: Remove search_plugin spread from plugins.entries**

Change:

```python
        "plugins": {
            "slots": {},
            "entries": {
                **search_plugin,
                "amazon-bedrock": amazon_bedrock_plugin,
            },
        },
```

To:

```python
        "plugins": {
            "slots": {},
            "entries": {
                "amazon-bedrock": amazon_bedrock_plugin,
            },
        },
```

- [ ] **Step 5: Remove proxy_base_url from ecs_manager.py caller**

In `apps/backend/core/containers/ecs_manager.py`, change line 990-995 from:

```python
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=gateway_token,
            proxy_base_url=settings.PROXY_BASE_URL,
            tier=tier,
        )
```

To:

```python
        config_json = write_openclaw_config(
            region=settings.AWS_REGION,
            gateway_token=gateway_token,
            tier=tier,
        )
```

- [ ] **Step 6: Update test_config.py — remove search assertion tests**

In `apps/backend/tests/unit/containers/test_config.py`, delete the two search-specific tests:

Delete `test_config_search_disabled_without_token` (lines 35-39):

```python
    def test_config_search_disabled_without_token(self):
        """Search disabled when no gateway token."""
        config = json.loads(write_openclaw_config(gateway_token=""))
        search = config["tools"]["web"]["search"]
        assert search["enabled"] is False
```

Delete `test_config_uses_perplexity_plugin_for_search` (lines 41-56):

```python
    def test_config_uses_perplexity_plugin_for_search(self):
        """Search uses Perplexity plugin with proxy baseUrl (v2026.3.22+ format)."""
        config = json.loads(
            write_openclaw_config(
                gateway_token="tok_abc123",
            )
        )
        # tools.web.search just enables + sets provider
        search = config["tools"]["web"]["search"]
        assert search["enabled"] is True
        assert search["provider"] == "perplexity"
        # Actual config lives in plugins.entries.perplexity
        plugin = config["plugins"]["entries"]["perplexity"]
        assert plugin["enabled"] is True
        assert plugin["config"]["webSearch"]["apiKey"] == "tok_abc123"
        assert "proxy/search" in plugin["config"]["webSearch"]["baseUrl"]
```

Also update the deep merge test that references perplexity (lines 303-319). Change it to use a generic example:

Replace `test_deep_merge_nested`:

```python
    def test_deep_merge_nested(self):
        """Nested dicts are deep-merged."""
        base = {
            "tools": {
                "web": {"search": {"enabled": False, "provider": "perplexity"}},
                "media": {"image": {"enabled": False}},
            }
        }
        patch = {
            "tools": {
                "web": {"search": {"enabled": True}},
            }
        }
        result = merge_openclaw_config(base, patch)
        assert result["tools"]["web"]["search"]["enabled"] is True
        assert result["tools"]["web"]["search"]["provider"] == "perplexity"  # preserved
        assert result["tools"]["media"]["image"]["enabled"] is False  # preserved
```

With:

```python
    def test_deep_merge_nested(self):
        """Nested dicts are deep-merged."""
        base = {
            "tools": {
                "web": {"fetch": {"enabled": False, "timeout": 30}},
                "media": {"image": {"enabled": False}},
            }
        }
        patch = {
            "tools": {
                "web": {"fetch": {"enabled": True}},
            }
        }
        result = merge_openclaw_config(base, patch)
        assert result["tools"]["web"]["fetch"]["enabled"] is True
        assert result["tools"]["web"]["fetch"]["timeout"] == 30  # preserved
        assert result["tools"]["media"]["image"]["enabled"] is False  # preserved
```

- [ ] **Step 7: Run all config tests**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_config.py -v`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/core/containers/config.py apps/backend/core/containers/ecs_manager.py apps/backend/tests/unit/containers/test_config.py
git commit -m "chore: remove search plugin injection from container config"
```

---

### Task 5: Remove Perplexity secret from CDK infrastructure

**Files:**
- Modify: `apps/infra/lib/stacks/auth-stack.ts:6-13` (AuthSecrets interface), `apps/infra/lib/stacks/auth-stack.ts:52-59` (secrets object)
- Modify: `apps/infra/lib/stacks/service-stack.ts:21-28` (SecretNames interface), `apps/infra/lib/stacks/service-stack.ts:601-603` (ECS secret)
- Modify: `apps/infra/lib/local-stage.ts:35` (secret seed), `apps/infra/lib/local-stage.ts:90` (secret name)
- Modify: `apps/infra/lib/isol8-stage.ts:86` (secret name)
- Modify: `localstack/init/ready.d/01-seed.sh:143` (secret seed)

- [ ] **Step 1: Remove from AuthSecrets interface and secrets object in auth-stack.ts**

In `apps/infra/lib/stacks/auth-stack.ts`, remove `perplexityApiKey` from the `AuthSecrets` interface:

Change:

```typescript
export interface AuthSecrets {
  clerkIssuer: secretsmanager.ISecret;
  clerkSecretKey: secretsmanager.ISecret;
  stripeSecretKey: secretsmanager.ISecret;
  stripeWebhookSecret: secretsmanager.ISecret;
  perplexityApiKey: secretsmanager.ISecret;
  encryptionKey: secretsmanager.ISecret;
}
```

To:

```typescript
export interface AuthSecrets {
  clerkIssuer: secretsmanager.ISecret;
  clerkSecretKey: secretsmanager.ISecret;
  stripeSecretKey: secretsmanager.ISecret;
  stripeWebhookSecret: secretsmanager.ISecret;
  encryptionKey: secretsmanager.ISecret;
}
```

And remove from the secrets construction:

Change:

```typescript
    this.secrets = {
      clerkIssuer: createSecret("ClerkIssuer", "clerk_issuer"),
      clerkSecretKey: createSecret("ClerkSecretKey", "clerk_secret_key"),
      stripeSecretKey: createSecret("StripeSecretKey", "stripe_secret_key"),
      stripeWebhookSecret: createSecret("StripeWebhookSecret", "stripe_webhook_secret"),
      perplexityApiKey: createSecret("PerplexityApiKey", "perplexity_api_key"),
      encryptionKey: createSecret("EncryptionKey", "encryption_key"),
    };
```

To:

```typescript
    this.secrets = {
      clerkIssuer: createSecret("ClerkIssuer", "clerk_issuer"),
      clerkSecretKey: createSecret("ClerkSecretKey", "clerk_secret_key"),
      stripeSecretKey: createSecret("StripeSecretKey", "stripe_secret_key"),
      stripeWebhookSecret: createSecret("StripeWebhookSecret", "stripe_webhook_secret"),
      encryptionKey: createSecret("EncryptionKey", "encryption_key"),
    };
```

- [ ] **Step 2: Remove from SecretNames interface and ECS secret injection in service-stack.ts**

In `apps/infra/lib/stacks/service-stack.ts`, remove `perplexityApiKey` from the `SecretNames` interface:

Change:

```typescript
export interface SecretNames {
  clerkIssuer: string;
  clerkSecretKey: string;
  stripeSecretKey: string;
  stripeWebhookSecret: string;
  perplexityApiKey: string;
  encryptionKey: string;
}
```

To:

```typescript
export interface SecretNames {
  clerkIssuer: string;
  clerkSecretKey: string;
  stripeSecretKey: string;
  stripeWebhookSecret: string;
  encryptionKey: string;
}
```

And remove the ECS secret injection (lines 601-603):

```typescript
        PERPLEXITY_API_KEY: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportPerplexityApiKey", props.secretNames.perplexityApiKey),
        ),
```

Delete those three lines.

- [ ] **Step 3: Remove from local-stage.ts**

In `apps/infra/lib/local-stage.ts`, remove the secret seed value (line 35):

```typescript
        perplexity_api_key: process.env.PERPLEXITY_API_KEY ?? "",
```

And remove the secret name prop (line 90):

```typescript
        perplexityApiKey: `isol8/${env}/perplexity_api_key`,
```

- [ ] **Step 4: Remove from isol8-stage.ts**

In `apps/infra/lib/isol8-stage.ts`, remove the secret name prop (line 86):

```typescript
        perplexityApiKey: `isol8/${env}/perplexity_api_key`,
```

- [ ] **Step 5: Remove from localstack seed script**

In `localstack/init/ready.d/01-seed.sh`, remove line 143:

```bash
  ["isol8/local/perplexity_api_key"]="${PERPLEXITY_API_KEY:-pplx_placeholder}"
```

- [ ] **Step 6: Verify CDK compiles**

Run: `cd apps/infra && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 7: Commit**

```bash
git add apps/infra/lib/stacks/auth-stack.ts apps/infra/lib/stacks/service-stack.ts apps/infra/lib/local-stage.ts apps/infra/lib/isol8-stage.ts localstack/init/ready.d/01-seed.sh
git commit -m "chore: remove Perplexity API key from CDK infrastructure"
```

---

### Task 6: Update landing page Skills component

**Files:**
- Modify: `apps/frontend/src/components/landing/Skills.tsx:50` (installed count)
- Modify: `apps/frontend/src/components/landing/Skills.tsx:56-62` (Perplexity card)

- [ ] **Step 1: Decrement installed count**

In `apps/frontend/src/components/landing/Skills.tsx`, change line 50 from:

```tsx
              <span className="store-pill">Installed (6)</span>
```

To:

```tsx
              <span className="store-pill">Installed (5)</span>
```

- [ ] **Step 2: Move Perplexity from "Installed" to "Available"**

Remove the Perplexity card from the "Installed" section (lines 56-62):

```tsx
            <div className="store-card">
              <span className="store-card-emoji">🔍</span>
              <div className="store-card-info">
                <span className="store-card-name">Perplexity <span className="store-badge">Installed</span></span>
                <span className="store-card-desc">Search the web with AI-powered answers</span>
              </div>
            </div>
```

And add it to the "Available" section (after the existing available cards) without the badge, with an install button:

```tsx
            <div className="store-card">
              <span className="store-card-emoji">🔍</span>
              <div className="store-card-info">
                <span className="store-card-name">Perplexity</span>
                <span className="store-card-desc">Search the web with AI-powered answers</span>
              </div>
              <span className="store-install-btn">Install</span>
            </div>
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/landing/Skills.tsx
git commit -m "chore: move Perplexity to Available section on landing page"
```

---

### Task 7: Run full test suite and verify

- [ ] **Step 1: Run backend tests**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: All tests pass. No import errors from the removed proxy module.

- [ ] **Step 2: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: No errors.

- [ ] **Step 3: Run CDK synth (optional — verifies stack compiles)**

Run: `cd apps/infra && npx cdk synth --quiet 2>&1 | head -5`
Expected: No errors (may warn about missing context, that's fine).
