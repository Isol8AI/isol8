# Org-pooled credits — fix-plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the credit ledger so that org members and admins share one balance keyed on `owner_id`, not on the per-Clerk-user `user_id`. Production members were getting `code=out_of_credits` at chat time even though their org admin had a positive balance.

**Architecture:** Today, every credit-ledger code path keys on the chatting user's Clerk id, while the org-billing surface (Stripe customer, subscription, `provider_choice`) is already owner-keyed. After this fix, all four ledger paths (read balance, configure auto-reload, top-up checkout metadata + webhook credit, chat gate balance, deduct on completion, provision gate) consistently use `resolve_owner_id(ctx)` / `self.user_id` (which on a `GatewayConnection` is the container owner).

**Tech Stack:** FastAPI + Python 3.13, DynamoDB (`isol8-prod-credits` table — keeps PK attribute name `user_id`; we just write the owner id into it), Stripe Checkout webhooks, pytest + moto.

**Out of scope:**
- DDB attribute rename `user_id → owner_id` on `credits` / `credit-transactions`. Cost > benefit; the column accepts whatever string we write.
- Migrating existing prod credit rows where an org admin holds a balance under their personal user_id. The user explicitly said they'll handle prod state out-of-band; we'll include the migration command in the PR description.
- `provider_choice` per-user behavior — Workstream B (2026-05-03) already moved provider_choice to the owner-scoped `billing_accounts` row, so it's already correct.

---

### Task 1: Add org-context async-client fixtures

The existing conftest already provides `mock_org_admin_user` / `mock_org_member_user` dependency overrides; we just need matching async clients to drive them through the API.

**Files:**
- Modify: `apps/backend/tests/conftest.py`

- [ ] **Step 1: Append two fixtures** at the end of the file, mirroring the existing `async_client` fixture (line 144).

```python
@pytest.fixture
async def async_client_org_admin(app, mock_org_admin_user) -> AsyncGenerator:
    """Async test client authenticated as org admin (user_test_123 in org_test_456)."""
    from core.auth import get_current_user

    app.dependency_overrides[get_current_user] = mock_org_admin_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client_org_member(app, mock_org_member_user) -> AsyncGenerator:
    """Async test client authenticated as org member (user_test_789 in org_test_456)."""
    from core.auth import get_current_user

    app.dependency_overrides[get_current_user] = mock_org_member_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Sanity collect.** `cd apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py --collect-only -q`. Expected: passes.

- [ ] **Step 3: Commit.** `git add apps/backend/tests/conftest.py && git commit -m "test(conftest): add async_client_org_admin / org_member fixtures"`

---

### Task 2: `GET /credits/balance` keyed on owner_id

**Files:**
- Modify: `apps/backend/routers/billing.py` (line 522)
- Modify: `apps/backend/tests/unit/routers/test_billing_credits.py`

- [ ] **Step 1: Failing test.** Append to `test_billing_credits.py`:

```python
@pytest.mark.asyncio
async def test_get_balance_org_member_reads_owner_id(async_client_org_member, credit_ledger_tables):
    """Org members and admin share one credit balance, keyed on owner_id (the org_id).
    Without this, every org member sees balance=0 because their personal user_id has no
    credit row — see PR fixing 'out_of_credits' for org members."""
    captured: dict = {}

    async def fake_get_balance(key, *, consistent: bool = False):
        captured["key"] = key
        return 9_876_543

    with patch("routers.billing.credit_ledger.get_balance", new=fake_get_balance):
        resp = await async_client_org_member.get("/api/v1/billing/credits/balance")
    assert resp.status_code == 200
    assert resp.json() == {"balance_microcents": 9_876_543, "balance_dollars": "9.88"}
    assert captured["key"] == "org_test_456"


@pytest.mark.asyncio
async def test_get_balance_personal_uses_user_id(async_client, credit_ledger_tables):
    """Personal users have owner_id == user_id, so the read is unchanged."""
    captured: dict = {}

    async def fake_get_balance(key, *, consistent: bool = False):
        captured["key"] = key
        return 1_000_000

    with patch("routers.billing.credit_ledger.get_balance", new=fake_get_balance):
        resp = await async_client.get("/api/v1/billing/credits/balance")
    assert resp.status_code == 200
    assert captured["key"] == "user_test_123"
```

- [ ] **Step 2: Run — expect FAIL.** `cd apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py::test_get_balance_org_member_reads_owner_id -v`

- [ ] **Step 3: Fix.** In `apps/backend/routers/billing.py` line 522:

Find:
```python
    balance_uc = await credit_ledger.get_balance(ctx.user_id)
```
Replace:
```python
    balance_uc = await credit_ledger.get_balance(resolve_owner_id(ctx))
```

- [ ] **Step 4: Run — expect PASS.** `cd apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py -v -k balance`

- [ ] **Step 5: Commit.** `git commit -m "fix(billing): key /credits/balance on owner_id"`

---

### Task 3: `PUT /credits/auto_reload` keyed on owner_id

**Files:**
- Modify: `apps/backend/routers/billing.py` (line 583)
- Modify: `apps/backend/tests/unit/routers/test_billing_credits.py`

- [ ] **Step 1: Failing test.** Append:

```python
@pytest.mark.asyncio
async def test_set_auto_reload_org_uses_owner_id(async_client_org_admin, credit_ledger_tables):
    captured: dict = {}

    async def fake_set(key, *, enabled, threshold_cents, amount_cents):
        captured["key"] = key

    with patch("routers.billing.credit_ledger.set_auto_reload", new=fake_set):
        resp = await async_client_org_admin.put(
            "/api/v1/billing/credits/auto_reload",
            json={"enabled": True, "threshold_cents": 500, "amount_cents": 5000},
        )
    assert resp.status_code == 200
    assert captured["key"] == "org_test_456"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Fix.** In `billing.py` line 583, change `ctx.user_id` → `resolve_owner_id(ctx)`.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit.** `git commit -m "fix(billing): key auto_reload config on owner_id"`

---

### Task 4: Top-up checkout metadata + webhook credit on `owner_id`

Currently `create_credit_top_up_checkout` (`billing_service.py:285,290`) writes `user_id` into Stripe metadata, and the webhook (`billing.py:809,824`) reads `metadata.user_id` and credits the ledger. Switch both ends to `owner_id`. The `user_id` parameter on `create_credit_top_up_checkout` is unused after this and is dropped from the signature (no caller currently passes it for any other purpose).

For the webhook, we **read both keys** for one deploy to bridge in-flight Stripe checkouts (`metadata.owner_id` preferred, `metadata.user_id` fallback) with a `credit.top_up.legacy_metadata` metric so we can verify the fallback can be removed. Per reviewer I2 — strict-from-day-one would silently drop a real customer top-up if a checkout was in flight at deploy. Follow-up PR removes the fallback once the metric stays at zero.

**Files:**
- Modify: `apps/backend/core/services/billing_service.py:218-295` (function signature, docstring, metadata writes)
- Modify: `apps/backend/routers/billing.py:558` (caller — drop `user_id=` kwarg)
- Modify: `apps/backend/routers/billing.py:809-832` (webhook reader + credit)
- Modify: `apps/backend/tests/unit/routers/test_billing_credits.py` (fixtures + assertions)

- [ ] **Step 1: Update existing tests** to use `owner_id` in metadata.

In `test_top_up_creates_checkout_session` (around line 97):

Find:
```python
    assert kwargs["metadata"]["user_id"] == "user_test_123"
```
Replace:
```python
    assert kwargs["metadata"]["owner_id"] == "user_test_123"
    assert "user_id" not in kwargs["metadata"]
```

For each of the five existing webhook tests (`test_checkout_session_completed_credits_ledger`, `*_with_full_discount_*`, `*_with_unpaid_status_*`, `test_async_payment_succeeded_*`, `test_async_payment_failed_*`), find their fake-event metadata dicts and rename the `user_id` key to `owner_id` (values stay the same opaque id strings).

- [ ] **Step 2: Add new failing tests.** Append:

```python
@pytest.mark.asyncio
async def test_top_up_org_admin_writes_org_id_to_metadata(
    async_client_org_admin, credit_ledger_tables
):
    """Org admin top-up: charges the org's Stripe customer, but the credit grant
    is written to the org_id row so every member sees the balance."""
    fake_session = type("S", (), {"id": "cs_test_org", "url": "https://checkout.stripe.com/c/pay/cs_test_org"})()
    with (
        patch(
            "core.services.billing_service.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"stripe_customer_id": "cus_test_org"}),
        ),
        patch("stripe.checkout.Session.create", return_value=fake_session) as mock_session,
    ):
        resp = await async_client_org_admin.post(
            "/api/v1/billing/credits/top_up",
            json={"amount_cents": 5000},
        )
    assert resp.status_code == 200
    _, kwargs = mock_session.call_args
    assert kwargs["customer"] == "cus_test_org"
    assert kwargs["metadata"]["owner_id"] == "org_test_456"
    assert kwargs["payment_intent_data"]["metadata"]["owner_id"] == "org_test_456"
    assert "user_id" not in kwargs["metadata"]


@pytest.mark.asyncio
async def test_webhook_legacy_metadata_user_id_falls_back_with_metric(
    async_client, monkeypatch, credit_ledger_tables
):
    """Bridge: a checkout that started before the deploy still has only
    metadata.user_id. Credit it (so we don't lose customer money) but emit
    a metric so we know when the fallback can be removed."""
    fake_event = {
        "id": "evt_legacy",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_legacy",
                "payment_status": "paid",
                "amount_total": 2000,
                "metadata": {
                    "purpose": "credit_top_up",
                    "user_id": "u_legacy",
                    "amount_cents": "2000",
                },
            }
        },
    }
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda body, sig, secret: fake_event)
    metric_calls: list = []
    monkeypatch.setattr("routers.billing.put_metric", lambda *a, **k: metric_calls.append((a, k)))
    with patch("routers.billing.credit_ledger.top_up", new=AsyncMock(return_value=20_000_000)) as mock_top_up:
        resp = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=json.dumps(fake_event),
            headers={"stripe-signature": "ignored"},
        )
    assert resp.status_code == 200
    args, _ = mock_top_up.call_args
    assert args[0] == "u_legacy"
    assert any(a and a[0] == "credit.top_up.legacy_metadata" for a, _ in metric_calls)
```

- [ ] **Step 3: Run — expect FAIL** on all the new + updated tests.

- [ ] **Step 4: Update `create_credit_top_up_checkout`** in `apps/backend/core/services/billing_service.py`.

Drop the `user_id` parameter from the signature (line 218-223):

```python
async def create_credit_top_up_checkout(
    *,
    owner_id: str,
    amount_cents: int,
) -> stripe.checkout.Session:
```

Replace the docstring sentence at line 246-249 to match (`owner_id` not `user_id`). Then update the metadata writes (line 282-292):

```python
            payment_intent_data={
                "metadata": {
                    "purpose": "credit_top_up",
                    "owner_id": owner_id,
                },
            },
            metadata={
                "purpose": "credit_top_up",
                "owner_id": owner_id,
                "amount_cents": str(amount_cents),
            },
```

- [ ] **Step 5: Update the router caller** at `apps/backend/routers/billing.py:556-562`. Drop the `user_id=ctx.user_id,` kwarg.

- [ ] **Step 6: Update the webhook handler** at `apps/backend/routers/billing.py:809-832` to read both keys with a metric on the legacy path:

Find:
```python
        user_id = session["metadata"].get("user_id")
        amount_cents_str = session["metadata"].get("amount_cents")
        if not user_id or not amount_cents_str:
            logger.error("Credit top-up checkout.session missing metadata: %s", session.get("id"))
            return Response(status_code=200)
```
Replace:
```python
        # owner_id is the credit ledger key — org_id for org context, user_id
        # for personal. See create_credit_top_up_checkout for where we write it.
        # Bridge: in-flight checkouts that started before this deploy carry
        # only metadata.user_id; credit them and emit a metric. Once the
        # metric stays at zero, drop the fallback.
        metadata = session["metadata"]
        ledger_key = metadata.get("owner_id") or metadata.get("user_id")
        amount_cents_str = metadata.get("amount_cents")
        if not ledger_key or not amount_cents_str:
            logger.error("Credit top-up checkout.session missing metadata: %s", session.get("id"))
            return Response(status_code=200)
        if not metadata.get("owner_id") and metadata.get("user_id"):
            put_metric("credit.top_up.legacy_metadata")
            logger.warning(
                "Credit top-up using legacy metadata.user_id for session %s — "
                "in-flight Stripe checkout from before owner-pool deploy",
                session.get("id"),
            )
```

Then change `await credit_ledger.top_up(user_id, ...)` → `await credit_ledger.top_up(ledger_key, ...)` at line 824.

- [ ] **Step 7: Run — expect PASS.** `cd apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py -v`

- [ ] **Step 8: Commit.** `git commit -m "fix(billing): credit top-up writes/reads owner_id metadata"`

---

### Task 5: `gate_chat` balance check uses `owner_id`

The existing test `test_card3_balance_keyed_on_member_provider_keyed_on_owner` (`tests/unit/gateway/test_connection_pool_credits.py:97-122`) explicitly pins the bug — it asserts the balance arg is the member id. Flip it to the owner id. Also drop the `owner_id: str | None = None` default — every production caller passes it; the back-compat path is the bug.

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py:1073` (signature) and `:1141` (balance call)
- Modify: `apps/backend/tests/unit/gateway/test_connection_pool_credits.py:97-122, :265-274`

- [ ] **Step 1: Update the assertion** in `test_card3_balance_keyed_on_member_provider_keyed_on_owner`:

Find (line 99-102):
```python
    """Workstream B regression: gate_chat reads provider_choice from
    billing_repo.get_by_owner_id(owner_id), and credit balance from
    credit_ledger.get_balance(user_id) — different keys.
    """
```
Replace:
```python
    """After the org-pooled-credits fix, both provider_choice (from
    billing_repo.get_by_owner_id) AND credit balance (from credit_ledger.get_balance)
    are keyed on owner_id, not on the chatting member.
    """
```

Find (line 118-122):
```python
    # Provider check used the owner.
    billing_mock.assert_awaited_once_with("org_Y")
    # Credit balance used the member.
    balance_args, balance_kwargs = balance_mock.call_args
    assert balance_args[0] == "member_X"
```
Replace:
```python
    # Both provider check and balance lookup keyed on owner — credits pool.
    billing_mock.assert_awaited_once_with("org_Y")
    balance_args, balance_kwargs = balance_mock.call_args
    assert balance_args[0] == "org_Y"
```

Rename the test name to match: `test_card3_balance_keyed_on_owner_credits_pool`.

- [ ] **Step 2: Update the back-compat test.** The current `test_owner_id_omitted_skips_all_gates_for_back_compat` (line 264-274) asserts the gate is a no-op when `owner_id` is omitted. After we make `owner_id` required, that test should assert a `TypeError` instead — or be deleted. Delete it: there are no production callers that omit `owner_id`, and tests should not pin the buggy back-compat path.

- [ ] **Step 3: Run — expect FAIL** (the renamed test now expects `org_Y`).

- [ ] **Step 4: Fix `gate_chat`.** In `apps/backend/core/gateway/connection_pool.py:1073`:

Find:
```python
    async def gate_chat(self, *, user_id: str, owner_id: str | None = None) -> dict:
```
Replace:
```python
    async def gate_chat(self, *, user_id: str, owner_id: str) -> dict:
```

Update docstring (lines 1083-1101): drop the "owner_id is optional for back-compat" sentence.

Find at line 1141:
```python
        balance = await credit_ledger.get_balance(user_id, consistent=True)
```
Replace:
```python
        # Credits pool at the owner level — every org member draws from one
        # balance keyed on owner_id. (provider_choice above is also owner-
        # scoped via billing_accounts since Workstream B 2026-05-03.)
        balance = await credit_ledger.get_balance(owner_id, consistent=True)
```

Update the comment block above (1132-1138) to remove the "Credits stay per-member below" note.

- [ ] **Step 5: Run — expect PASS.** `cd apps/backend && uv run pytest tests/unit/gateway/test_connection_pool_credits.py -v`

- [ ] **Step 6: Commit.** `git commit -m "fix(gateway): gate_chat balance uses owner_id (org credits pool)"`

---

### Task 6: `_maybe_deduct_credits` deducts from owner

`self.user_id` on a `GatewayConnection` IS the container owner (the connection is keyed on owner per `_create_connection`). Deduct from `self.user_id` and drop the now-unused `member_user_id` parameter. The provider lookup at line 754 already uses `self.user_id`, so it stays. Existing test `test_deduct_provider_keyed_on_owner_credits_keyed_on_member` (line 345-371) pins the buggy behavior — flip it.

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py:704-799` (signature, body, log)
- Modify: `apps/backend/core/gateway/connection_pool.py:684-692` (caller — drop `member_user_id=` kwarg)
- Modify: `apps/backend/tests/unit/gateway/test_connection_pool_credits.py` (test name + assertion + drop `member_user_id=` from test calls)

- [ ] **Step 1: Update the regression test** at line 345-371. Rename to `test_deduct_keyed_on_owner_credits_pool`, drop `member_user_id=`, and assert `args[0] == "org_Y"`:

```python
@pytest.mark.asyncio
async def test_deduct_keyed_on_owner_credits_pool():
    """After the org-pooled-credits fix, deduct draws from the owner row
    (self.user_id is the container owner), not from the chatting member."""
    conn = _make_connection(user_id="org_Y")
    billing_mock = AsyncMock(return_value={"provider_choice": "bedrock_claude"})
    deduct_mock = AsyncMock(return_value=0)
    with (
        patch("core.repositories.billing_repo.get_by_owner_id", new=billing_mock),
        patch("core.services.credit_ledger.deduct", new=deduct_mock),
    ):
        await conn._maybe_deduct_credits(
            chat_session_id="sess_1",
            model="amazon-bedrock/anthropic.claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
        )
    billing_mock.assert_awaited_once_with("org_Y")
    deduct_mock.assert_awaited_once()
    args, _ = deduct_mock.call_args
    assert args[0] == "org_Y"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Update `_maybe_deduct_credits`** in `apps/backend/core/gateway/connection_pool.py`. Drop the `member_user_id` parameter entirely and the `_parse_session_key` fallback — they only existed to choose the deduct key, which is now `self.user_id`.

Find (line 704-714):
```python
    async def _maybe_deduct_credits(
        self,
        *,
        chat_session_id: str,
        member_user_id: str | None = None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
```
Replace:
```python
    async def _maybe_deduct_credits(
        self,
        *,
        chat_session_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
```

Update the docstring (line 715-732) to drop the now-stale `member_user_id` paragraph.

Find (line 740-749):
```python
        # Prefer the explicitly-resolved member id from the caller; only
        # fall back to session-key parsing when the caller didn't pass one.
        # For channel/DM/group session keys without a member_id segment,
        # the parser returns owner-context only — that's the wrong row for
        # credit deduction.
        if member_user_id:
            billing_user_id = member_user_id
        else:
            parsed = _parse_session_key(chat_session_id)
            billing_user_id = parsed.get("member_id") or self.user_id
```
Delete that whole block (the `billing_user_id` local is no longer needed).

Find (line 785-791):
```python
        await credit_ledger.deduct(
            billing_user_id,
            amount_microcents=marked_up,
            chat_session_id=chat_session_id,
            raw_cost_microcents=raw,
            markup_multiplier=1.4,
        )
        logger.info(
            "Deducted credits for user %s session %s: raw=%d marked_up=%d model=%s",
            billing_user_id,
            ...
        )
```
Replace:
```python
        # Credits pool at the owner level — `self.user_id` IS the container
        # owner (the connection is keyed on owner per _create_connection).
        await credit_ledger.deduct(
            self.user_id,
            amount_microcents=marked_up,
            chat_session_id=chat_session_id,
            raw_cost_microcents=raw,
            markup_multiplier=1.4,
        )
        logger.info(
            "Deducted credits for owner %s session %s: raw=%d marked_up=%d model=%s",
            self.user_id,
            chat_session_id,
            raw,
            marked_up,
            bare_model,
        )
```

- [ ] **Step 4: Update the caller** at line 683-692:

Find:
```python
            try:
                await self._maybe_deduct_credits(
                    chat_session_id=session_key,
                    member_user_id=member_user_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                )
```
Replace:
```python
            try:
                await self._maybe_deduct_credits(
                    chat_session_id=session_key,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                )
```

Also update the surrounding comment at line 679-682 to drop the "Pass the resolved member_user_id explicitly" sentence (the resolution is no longer needed for deduct).

- [ ] **Step 5: Run — expect PASS** the targeted test, then run the full credits file to catch any other tests that pass `member_user_id=`.

`cd apps/backend && uv run pytest tests/unit/gateway/test_connection_pool_credits.py -v`. If any test still passes `member_user_id=`, remove that kwarg from the call.

- [ ] **Step 6: Commit.** `git commit -m "fix(gateway): deduct from connection owner (org credits pool)"`

---

### Task 7: Provision gate balance keyed on owner

**Files:**
- Modify: `apps/backend/core/services/provision_gate.py:140`
- Modify: `apps/backend/tests/unit/services/test_provision_gate.py`

- [ ] **Step 1: Read existing test file** to learn the public function name and fixture style.

`cd apps/backend && grep -n "credits_required\|get_balance\|def test" tests/unit/services/test_provision_gate.py`

- [ ] **Step 2: Add (or extend) a test** that asserts the balance probe uses `owner_id`:

```python
@pytest.mark.asyncio
async def test_bedrock_balance_keyed_on_owner_id(monkeypatch):
    """Org members hitting /onboarding's pre-provision check must see the
    pooled org balance, not their personal user_id row."""
    from core.services import provision_gate as pg

    monkeypatch.setattr(
        "core.services.provision_gate.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"subscription_status": "active"}),
    )
    monkeypatch.setattr(
        "core.services.provision_gate._get_provider_choice",
        AsyncMock(return_value="bedrock_claude"),
    )
    captured: dict = {}

    async def fake_balance(key):
        captured["key"] = key
        return 5_000_000

    monkeypatch.setattr("core.services.provision_gate.credit_ledger.get_balance", fake_balance)
    # Adapt the entry-point name to whatever the file exposes — read first.
    gate = await pg.evaluate_provision_gate(
        owner_id="org_Y", clerk_user_id="user_member_X", owner_role="member"
    )
    assert gate is None
    assert captured["key"] == "org_Y"
```

(If the public function name in the file is different, adapt — the test should call whatever evaluates the gate.)

- [ ] **Step 3: Run — expect FAIL.**

- [ ] **Step 4: Fix.** In `provision_gate.py:140`:

Find:
```python
        balance = await credit_ledger.get_balance(clerk_user_id)
```
Replace:
```python
        # Credits pool at the owner level — bedrock orgs share one balance
        # across members. clerk_user_id remains useful for the OAuth probe
        # below since OAuth tokens are per-user.
        balance = await credit_ledger.get_balance(owner_id)
```

- [ ] **Step 5: Run — expect PASS.** `cd apps/backend && uv run pytest tests/unit/services/test_provision_gate.py -v`

- [ ] **Step 6: Commit.** `git commit -m "fix(provision-gate): bedrock balance uses owner_id"`

---

### Task 8: Rename `credit_ledger.py` parameters from `user_id` to `owner_id`

Pure rename, no behavior change. The DDB attribute name stays `user_id` (that would be a separate migration), but the Python parameter and module docstring reflect what we now write into it. Keeps future readers from re-introducing the bug.

**Files:**
- Modify: `apps/backend/core/services/credit_ledger.py` (every function signature + docstring)
- Modify: any test that asserts the function takes a kwarg named `user_id` (likely none — most calls are positional).

- [ ] **Step 1: Read** `apps/backend/core/services/credit_ledger.py` end-to-end — find each `user_id: str` parameter and each docstring reference.

- [ ] **Step 2: Rename in place.** For each public function (`get_balance`, `top_up`, `deduct`, `adjustment`, `set_auto_reload`, `should_auto_reload`):
  - Parameter name: `user_id` → `owner_id`.
  - Inside function body, every `Key={"user_id": user_id}` keeps the `"user_id"` key (DDB attr) but the variable becomes `owner_id`.
  - `_put_txn` items: `"user_id": user_id` → `"user_id": owner_id` (still writing the owner id under the legacy attr name).

Update the module docstring (top of file, lines 1-17) to clarify: "credits/credit-transactions are keyed by `owner_id` (org_id for org context, user_id for personal). The DDB attribute name remains `user_id` for backward compat."

- [ ] **Step 3: Rerun the credit ledger unit tests.**

`cd apps/backend && uv run pytest tests/unit/services/test_credit_ledger.py -v`. Expected: all green (it's a pure rename).

- [ ] **Step 4: Run the full credit-touching tests** to catch any kwarg `user_id=` callers.

`cd apps/backend && uv run pytest tests/unit/routers/test_billing_credits.py tests/unit/gateway/test_connection_pool_credits.py tests/unit/services/test_credit_ledger.py tests/unit/services/test_provision_gate.py -v`

If anything fails because a caller used `user_id=` kwarg, fix the caller.

- [ ] **Step 5: Commit.** `git commit -m "refactor(credit-ledger): rename user_id parameter to owner_id"`

---

### Task 9: Final verification

- [ ] **Step 1: Full backend tests.** `cd apps/backend && uv run pytest tests/ -v`. Expected: all green.

- [ ] **Step 2: Lint + format check.** `cd apps/backend && uv run ruff check . && uv run ruff format --check .`. Expected: clean.

- [ ] **Step 3: Open the PR** with the migration command in the description (one-shot rekey for prod admins who topped up under their personal user_id).

---

## Self-review

**Spec coverage:** every credit ledger call site identified in the diagnosis is addressed:
- `routers/billing.py:522` — Task 2
- `routers/billing.py:583` — Task 3
- `routers/billing.py:558,809,824` + `billing_service.py:285,290` — Task 4
- `connection_pool.py:1141` — Task 5
- `connection_pool.py:786` — Task 6
- `provision_gate.py:140` — Task 7
- `credit_ledger.py` parameter names — Task 8

**Placeholders:** none. Each Find/Replace shows the actual current code; the test code blocks are complete.

**Type consistency:** `resolve_owner_id(ctx)` everywhere on the router side; `owner_id` keyword on the gateway side; `self.user_id` (= owner) where the connection already holds it. `gate_chat` `owner_id` becomes required (no `: str | None = None`). `_maybe_deduct_credits` drops `member_user_id` (now unused).

**Migration callout:** prod has rows in `isol8-prod-credits` keyed on individual Clerk user_ids. Personal users are unaffected (their `user_id == owner_id`). Org admins who topped up before this fix will see balance=0 in their org context until the row is re-keyed. A one-shot migration query goes in the PR description; the user said they'll handle prod state out-of-band.
