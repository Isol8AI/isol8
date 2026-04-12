# ORR Track C — Backend Security Fixes + Docs Cleanup Design

**Status:** Draft
**Date:** 2026-04-11
**Master spec:** [2026-04-11-operational-readiness-review-design.md](./2026-04-11-operational-readiness-review-design.md)
**Parent issue:** Isol8AI/isol8#190
**Branch:** `worktree-track-c-security` (when teammate runs)

---

## 1. Goal

Implement the 15 backend security fixes from #190 §3 (CRITICAL items 1-6, HIGH items 7-9 and 11-13, MEDIUM items 14-17; item 10 is IAM, lives in Track B). Build the DynamoDB throttle wrapper helper. Update CLAUDE.md to reflect current architecture (Fargate, CDK, DynamoDB, pinned OpenClaw version, fleet-patch admin warning).

**IAM tightening (#190 §3 item 10) is NOT in this track** — it lives in Track B alongside the other CDK work.

**Frontend observability is NOT in this track** — deferred to Isol8AI/isol8#231.

The success criterion: after this track ships, every CRITICAL finding in #190 §3 has a fix verified by tests, the dynamodb_helper wrapper is the canonical entry point for boto3 DynamoDB calls, and CLAUDE.md no longer makes false claims about the architecture.

## 2. Reads (do not duplicate)

- [Master spec §3](./2026-04-11-operational-readiness-review-design.md#3-scope) — what's in vs. out of scope
- [Master spec §6.3](./2026-04-11-operational-readiness-review-design.md#63-full-metric-catalog) — DynamoDB throttle metric definitions (`dynamodb.throttle`, `dynamodb.error`)
- [Master spec §7](./2026-04-11-operational-readiness-review-design.md#7-alarm-catalog) — security alarms that depend on the metrics added by this track
- Issue #190 §3 — full list of security findings with file references
- Isol8AI/isol8#190 — original audit
- Isol8AI/isol8#231 — Track D (so the teammate doesn't accidentally pull in frontend work)

## 3. Cross-track coordination

Track A's `core/observability/metrics.put_metric` is the canonical metric emit API. Track C's helper wrappers and security fixes import and call it. **Track C cannot start until Track A's `core/observability/` module exists**, OR Track C stubs the import and Track A's module satisfies it later.

Two safe approaches:

1. **Stub-and-rebase:** Track C imports `from core.observability.metrics import put_metric, timing` from day 1 even though the module doesn't exist on its branch. Rebase onto Track A's branch before merging.
2. **Define the API contract first:** the master spec §6 already pins the function signatures. Track C imports against the contract; the import works once both branches merge.

**Recommendation:** approach 2. The import will fail under Track C's branch tests in isolation, so Track C's tests are not run until after Track A's branch lands and Track C rebases. The lead handles the rebase manually.

Files where Track A and Track C both edit (merge will be touchy):

- `apps/backend/routers/updates.py`
- `apps/backend/routers/debug.py`
- `apps/backend/routers/proxy.py`
- `apps/backend/routers/billing.py`
- `apps/backend/routers/webhooks.py`
- `apps/backend/core/auth.py`
- `apps/backend/core/containers/workspace.py`

**Conflict pattern:** Track A adds metric emit calls at function boundaries. Track C adds logic changes (idempotency dedup, rate limit, bounds check) inside the same functions. The two are at different lines but in the same files. Standard 3-way merge usually handles this. Lead reviews any conflicts and resolves.

## 4. Security fixes — item by item

Each fix below cites the #190 §3 item number, the file/lines, the change, and the test that proves the fix works.

### 4.1 CRITICAL items

#### Item 1 — Fleet-wide config patch has no rate limit / approval

**Files:** `apps/backend/routers/updates.py:163-206`

**Change:** add to `PATCH /container/config` (no owner_id):

1. **Rate limit:** 1 invocation per hour, enforced by a DynamoDB-backed token bucket. Use a new helper `core/services/rate_limiter.py` (or inline if simple). Reject with 429 if exceeded.
2. **Audit log:** **There is no existing `audit_logs` model** — the codebase uses plain DynamoDB dicts, not ORM models. Instead, emit a structured log line at `logger.warning` level with fields: `action="fleet_patch"`, `actor_id=caller_user_id`, `payload_hash=sha256(body)`, `timestamp=now()`. This will be captured by CloudWatch Logs and is queryable via CloudWatch Insights. If a dedicated audit table is needed later, that's a follow-up — for now, structured logging + the `update.fleet_patch.invoked` metric provides the detection and record.
3. **SNS notification:** invoke the page topic via boto3 SNS publish. The topic ARN comes from a new env var `ALERT_PAGE_TOPIC_ARN` — **Track B must wire this** by adding the observability stack's page topic ARN as a container environment variable in `service-stack.ts`. Coordinate via SendMessage at start of work.
4. **Confirmation header:** require an `X-Confirm-Fleet-Patch: yes-i-am-sure` header. Reject 400 if absent.
5. **Metric:** Track A emits `update.fleet_patch.invoked` from this same site. This track ensures the emit happens AFTER all checks pass (not before — we don't want the metric/alarm firing for rejected attempts).

**Test:** `test_updates.py::test_fleet_patch_requires_confirmation_header` — POST without header, assert 400. `test_fleet_patch_rate_limited` — invoke twice in <1h, assert 429. `test_fleet_patch_writes_audit_log` — invoke once, assert structured log line with `action="fleet_patch"` appears in captured log output (use `caplog` — there is no audit_logs table).

#### Item 2 — Single-user config patch trusts org admin across users

**Files:** `apps/backend/routers/updates.py:142-160`

**Change:** to `PATCH /container/config/{owner_id}`, after the existing `require_org_admin()` check, add:

```python
# Tenant scoping: caller's org must own the target user
target_user = await user_repo.get(owner_id)
if not target_user or target_user.org_id != current_user.org_id:
    raise HTTPException(403, "Cannot patch user outside your organization")
```

**Test:** `test_updates.py::test_single_patch_blocks_cross_tenant` — admin from org A patches user in org B, assert 403.

#### Item 3 — Debug endpoints gated on string equality

**Files:** `apps/backend/routers/debug.py:48` and `core/auth.py` (where `require_non_production` lives if it's there)

**Change:** `require_non_production` is a FastAPI dependency applied via `dependencies=[Depends(require_non_production)]` at lines 37, 98, 181. Modify the dependency function (located at ~line 23-26):

```python
# Old: simple equality check
# New:
PROD_ENVIRONMENTS = {"prod", "production", "staging"}

def require_non_production():
    env = (settings.ENVIRONMENT or "").lower().strip()
    if env in PROD_ENVIRONMENTS:
        # Defensive: emit metric (should never fire since FastAPI returns 403 first)
        put_metric("debug.endpoint.prod_hit", dimensions={"endpoint": "unknown"})
        raise HTTPException(403, "Debug endpoints disabled in production")
```

**Note on the `endpoint` dimension:** the dependency function does not have access to the route name. Either (a) emit with a fixed dimension value of `"debug"` (sufficient for the alarm), or (b) refactor to a parameterized dependency factory: `def require_non_production(endpoint: str)` called as `Depends(lambda: require_non_production("provision"))`.

**Test:** `test_debug.py::test_debug_endpoints_blocked_in_prod` — set `ENVIRONMENT=prod`, hit each debug endpoint, assert 403.

#### Item 4 — Path traversal off-by-one in workspace

**Files:** `apps/backend/core/containers/workspace.py:123`

**Change:**

```python
# Old:
# if not str(resolved).startswith(str(user_dir) + "/"):
#     raise ValueError("Path escapes user dir")

# New:
try:
    resolved.relative_to(user_dir)  # raises ValueError if not under user_dir
except ValueError:
    put_metric("workspace.path_traversal.attempt")
    raise HTTPException(403, "Path traversal blocked")
```

**Test:** `test_workspace.py::test_path_traversal_blocked` — feed 10 known escape patterns (`../`, `../../`, `/etc/passwd`, `alice_evil/foo` while user is `alice`, etc.); assert each raises and the metric counter increments.

#### Item 5 — Proxy budget enforcement removed during DynamoDB migration

**Files:** `apps/backend/routers/proxy.py:56-61`

**Change:** re-implement the budget check that was simplified out during migration. Use `usage_service.check_budget(user_id, plan_tier="free", category="proxy")`.

```python
if user.tier == "free":
    if not await check_budget(user.id, "proxy"):
        put_metric("proxy.budget_check.fail")
        raise HTTPException(429, "Free tier proxy budget exceeded")
```

**Test:** `test_proxy.py::test_free_tier_blocked_when_over_budget` — create a free-tier user, set their proxy spend over budget in DDB, assert proxy call returns 429 + metric increments.

#### Item 6 — Stripe webhook lacks idempotency

**Files:** `apps/backend/routers/billing.py:304-360`

**Change:**

1. Add a new DynamoDB table `isol8-{env}-stripe-event-dedup` (Track B has TTL infrastructure; this table needs a 30-day TTL on `expires_at`). The table is added to `database-stack.ts` by Track C — note this is the only Track C touch of CDK. Coordinate with Track B via SendMessage.
2. In the webhook handler, before processing:
   ```python
   try:
       await dedup_table.put_item(
           Item={"event_id": event.id, "expires_at": int(time.time()) + 30*86400},
           ConditionExpression="attribute_not_exists(event_id)",
       )
   except ClientError as e:
       if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
           put_metric("stripe.webhook.duplicate")
           return Response(status_code=200)  # idempotent ack
       raise
   ```

**Test:** `test_billing.py::test_stripe_webhook_idempotent` — replay the same Stripe event 5×, assert only one call processes (verify by counting rows in audit log or by mocking the downstream side effect).

**Coordination note:** because Track C adds a new DynamoDB table, this is a Track C → Track B handoff. Either:
- Track C adds the table to `database-stack.ts` directly (and Track B reviews the change at integration), OR
- Track C SendMessages Track B with the table name + key schema + TTL attribute, and Track B adds it to its own branch

Lead picks at integration. Recommendation: Track C adds it inline to avoid blocking; Track B reviews.

### 4.2 HIGH items

#### Item 7 — JWKS cache stale-fallback on fetch error

**Files:** `apps/backend/core/auth.py:43`

**Change:** the current cache serves stale JWKS forever on fetch failure. Cap staleness at 15 minutes; fail closed thereafter.

```python
async def get_jwks():
    now = time.time()
    if _cache.value and (now - _cache.fetched_at) < JWKS_TTL_SECONDS:
        return _cache.value
    try:
        new_jwks = await fetch_jwks()
        _cache.value = new_jwks
        _cache.fetched_at = now
        put_metric("auth.jwks.refresh", dimensions={"status": "ok"})
        return new_jwks
    except Exception as e:
        put_metric("auth.jwks.refresh", dimensions={"status": "error"})
        # Allow stale up to 15 min from last successful fetch
        if _cache.value and (now - _cache.fetched_at) < 15 * 60:
            return _cache.value
        raise  # Fail closed
```

**Test:** `test_auth.py::test_jwks_stale_fallback_capped` — mock fetch to raise, assert serves stale within 15 min, raises after.

#### Item 8 — JWKS TTL 1h is too long

**Files:** `apps/backend/core/auth.py:38`

**Change:** lower `JWKS_TTL_SECONDS` from 3600 to 300.

**Test:** trivial constant change; covered by existing tests.

#### Item 9 — Gateway token stored plaintext in DynamoDB

**Files:** `apps/backend/core/services/key_service.py`, `apps/backend/core/containers/config_store.py`, `models/container.py`

**Change:** encrypt the `gateway_token` field in the `containers` table using the existing AuthStack KMS key (envelope encryption via Fernet, same pattern as BYOK keys).

1. Add `encrypt_gateway_token(token: str) -> str` and `decrypt_gateway_token(blob: str) -> str` to `key_service.py`
2. Migrate write paths to call `encrypt_*` before storing
3. Migrate read paths to call `decrypt_*` after fetching
4. Backfill: a one-shot script in `apps/backend/scripts/backfill_gateway_token_encryption.py` that reads each container row, encrypts the existing plaintext token, writes back. Idempotent (skips if already encrypted — detect via prefix marker)

**Test:** `test_key_service.py::test_gateway_token_roundtrip` — encrypt then decrypt, assert original. `test_container_repo.py::test_gateway_token_persists_encrypted` — assert raw DDB value differs from plaintext.

#### Item 11 — Control UI session hijack surface

**Files:** `apps/backend/routers/control_ui_proxy.py:118-146`

**Change:** session token currently in URL query string; `Referer` leaks to upstream. Move to:

1. **Authorization header** for API calls (already standard; just enforce it)
2. **HttpOnly cookie** for browser-rendered control UI (set by a new POST endpoint that exchanges the session token for a cookie)
3. Strip the `Referer` header on outbound proxy calls
4. Rate-limit session lookup (50/min/IP)

**Test:** `test_control_ui.py::test_session_token_not_in_query`, `test_referer_stripped`.

#### Item 12 — WS Origin not validated

**Files:** the Lambda authorizer in CDK (Track B's territory? — no, it's in `apps/infra/lib/lambdas/ws-authorizer/index.ts` which is shared. Track C edits the JS code; Track B doesn't need to redeploy the stack.)

**Note: the Lambda authorizer is PYTHON, not TypeScript.** Actual location: `apps/infra/lambda/websocket-authorizer/index.py` (NOT `lib/lambdas/ws-authorizer/index.ts` as originally cited in #190).

Keep in Track C — the security logic belongs with the other security fixes. Track B owns CDK wiring but not in-Lambda business logic. Lead resolves any merge friction.

**Change:** in `apps/infra/lambda/websocket-authorizer/index.py`, add Origin allow-list check:

```python
ALLOWED_ORIGINS = [
    'https://app.isol8.co',
    'https://dev.isol8.co',
    'https://app-dev.isol8.co',
    'http://localhost:3000',  # local dev
]

# At the top of the handler, before JWT validation:
origin = event.get('headers', {}).get('Origin') or event.get('headers', {}).get('origin')
if not origin or origin not in ALLOWED_ORIGINS:
    return generate_policy('user', 'Deny', event['methodArn'])
```

**Test:** integration test against the deployed authorizer (Track B's snapshot tests cover the structure; runtime test happens at deploy validation).

#### Item 13 — BYOK single master key, no access audit

**Files:** `apps/backend/core/services/key_service.py`

**Change:**
1. Per-decrypt audit log: emit a structured log line at `logger.info` level with fields: `action="byok_decrypt"`, `actor_id=user_id`, `key_id=key_id`, `request_id=request_id_var.get()`. Queryable via CloudWatch Insights. (There is no `audit_log` table — structured logging is the audit mechanism.)
2. Anomaly metric: `byok_decrypt.rate` per user (cardinality concern — actually emit as a structured log field, alarm via log metric filter rather than custom metric, so we don't blow up dimensions)
3. Plan key rotation: a written runbook at `docs/ops/runbooks/byok-key-rotation.md` (no code change; just documentation of the rotation procedure)

**Test:** `test_key_service.py::test_decrypt_writes_audit_log`.

### 4.3 MEDIUM items

#### Item 14 — PII in CloudWatch logs

**Files:** Track A's `core/observability/logging.py` JsonFormatter

**Change:** Track A owns the formatter. This item asks: do we want to redact `user_id` from logs entirely, or move long-retention to S3 with KMS while keeping CW retention short?

**Decision:** keep `user_id` in logs (it's needed for debugging), but **shorten CloudWatch log retention from 2 weeks to 3 days** in CDK (Track B owns this — `service-stack.ts:446`). For longer-term archive, ship logs to S3 with KMS encryption via a CDK `LogGroup → Kinesis Firehose → S3` pipeline (also Track B).

**Track C action:** none. This item migrates to Track B (CW retention) and master spec annotates.

**Note to lead:** update the master spec to move item 14 from Track C to Track B if not already done. Done in §3.1 above? Let me check... no, item 14 is split: the policy decision (keep user_id but shorten retention) is documented here, and the implementation (CDK retention change + Firehose pipeline) lands in Track B. **Coordinate via SendMessage at start of work.**

#### Item 15 — `workspace.py:160` writes mcporter.json with default umask

**Files:** `apps/backend/core/containers/workspace.py:160`

**Change:** explicit `os.chmod(path, 0o600)` after write.

**Test:** `test_workspace.py::test_mcporter_file_mode_is_0600`.

#### Item 16 — `/health` endpoint has no rate limit

**Files:** `apps/backend/main.py:264` (or `routers/health.py` if it exists)

**Change:** add a per-IP rate limiter (100 req/min/IP) using a simple in-memory token bucket. For prod robustness, use the WAF rule via Track B (CDK), not the in-process limiter.

**Decision:** in-process is fine for now. WAF is a Track B follow-up if needed. Document in the runbook.

**Test:** `test_health.py::test_health_rate_limited` — fire 200 requests, assert 429 after 100.

#### Item 17 — PyJWT validation has no leeway

**Files:** `apps/backend/core/auth.py`

**Change:** add `leeway=30` to the `jwt.decode()` call to tolerate 30s of clock skew.

**Test:** `test_auth.py::test_jwt_leeway_tolerates_skew` — generate a token with `iat = now + 25`, assert validation succeeds.

## 5. New helper: DynamoDB throttle wrapper

**File:** `apps/backend/core/services/dynamodb_helper.py` (new)

**Purpose:** wrap all boto3 DynamoDB calls in a helper that catches `ProvisionedThroughputExceededException` and `ThrottlingException`, emits the `dynamodb.throttle` metric, and retries with exponential backoff. Catch other client errors and emit `dynamodb.error`.

```python
# core/services/dynamodb_helper.py

import asyncio
from functools import partial

from botocore.exceptions import ClientError
from core.observability.metrics import put_metric

THROTTLE_CODES = {"ProvisionedThroughputExceededException", "ThrottlingException"}

async def call_with_metrics(table_name: str, op: str, fn, *args, **kwargs):
    """
    Call a boto3 DynamoDB op, emitting throttle/error metrics.
    Retries throttles up to 3× with exponential backoff.

    IMPORTANT: boto3 calls are SYNCHRONOUS. This wrapper uses
    asyncio.to_thread to avoid blocking the event loop, matching
    the existing codebase pattern (see core/dynamodb.py run_in_thread).
    """
    for attempt in range(3):
        try:
            # Run synchronous boto3 call in a thread pool
            return await asyncio.to_thread(partial(fn, *args, **kwargs))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in THROTTLE_CODES:
                put_metric("dynamodb.throttle", dimensions={"table": table_name, "op": op})
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            else:
                put_metric("dynamodb.error", dimensions={
                    "table": table_name, "op": op, "error_code": code,
                })
                raise
```

**Migration strategy:** replace direct `table.get_item(...)` calls with `await call_with_metrics(table.name, "get", table.get_item, ...)` across the repo. Migrate all tables fully — the wrapper is small, the change is mechanical, and a half-migrated state is confusing.

Files affected (**corrected filenames** — search for `boto3.resource('dynamodb')` or `Table(`):
- `core/repositories/user_repo.py` (NOT `users_repo.py`)
- `core/repositories/container_repo.py`
- `core/repositories/billing_repo.py`
- `core/repositories/api_key_repo.py` (verify exact name)
- `core/repositories/usage_repo.py` (NOT `usage_counters_repo.py`)
- `core/repositories/update_repo.py` (NOT `pending_updates_repo.py`)
- `core/repositories/channel_link_repo.py` (missed in original list)
- `core/services/connection_service.py` (NOT a repo file — WS connection logic lives here, no `ws_connections_repo.py` exists)

**Test:** `test_dynamodb_helper.py::test_throttle_retry`, `test_throttle_metric_emitted`, `test_error_metric_emitted_for_other_errors`.

## 6. CLAUDE.md cleanup

**File:** `CLAUDE.md`

Changes to make (reading the file in the worktree first to identify exact lines):

1. **Backend infrastructure:** "Backend uses RDS PostgreSQL" → "Backend uses DynamoDB (8 tables, see database-stack.ts)"
2. **Backend deploy target:** "EC2 (m5.xlarge)" → "ECS Fargate (FargateService in service-stack.ts)"
3. **Database section:** remove all references to Supabase, Postgres async, init_db.py — replace with DynamoDB equivalents
4. **Local dev:** verify the LocalStack CDK section is current; the script `./scripts/local-dev.sh` is referenced
5. **Terraform section:** delete entirely; replace with "Infrastructure: AWS CDK in `apps/infra/`"
6. **Pinned OpenClaw version:** confirm `OPENCLAW_IMAGE=alpine/openclaw:2026.3.24` is the current pin; update if newer
7. **Add fleet-patch admin warning:** new section under Critical Rules: "Fleet config patch (`PATCH /container/config` no owner_id) is rate-limited to 1/hour, requires `X-Confirm-Fleet-Patch` header, writes an audit log row, and pages on-call. Never call from a script — always manual."
8. **Desktop app:** verify references say "Tauri (not Electron)" — already noted in user memory

**No test required** — manual review by lead during PR.

## 7. Test strategy

Each fix above includes its own unit/integration test. Aggregate coverage:

```bash
cd apps/backend && uv run pytest tests/ -v --cov=core --cov=routers
```

Target: 100% line coverage on new files (`dynamodb_helper.py`, `rate_limiter.py` if created, the encryption functions in `key_service.py`).

For the cross-file fixes (idempotency, traversal, debug allow-list), prefer **integration tests** over unit tests — they exercise the actual router → service → repo → DDB chain.

## 8. Files affected (summary)

**New files:**
- `apps/backend/core/services/dynamodb_helper.py`
- `apps/backend/scripts/backfill_gateway_token_encryption.py`
- `apps/backend/tests/test_dynamodb_helper.py`
- `apps/backend/tests/test_security_fixes.py` (combines tests for items 1-9, 11-17)
- `docs/ops/runbooks/byok-key-rotation.md`

**Modified files:**
- `apps/backend/routers/updates.py` — items 1, 2
- `apps/backend/routers/debug.py` — item 3
- `apps/backend/core/auth.py` — items 3, 7, 8, 17
- `apps/backend/core/containers/workspace.py` — items 4, 15
- `apps/backend/routers/proxy.py` — item 5
- `apps/backend/routers/billing.py` — item 6
- `apps/backend/routers/webhooks.py` — Clerk webhook idempotency (parallel to item 6)
- `apps/backend/core/services/key_service.py` — items 9, 13
- `apps/backend/core/containers/config_store.py` — item 9
- `apps/backend/models/container.py` — item 9 (if schema annotation exists)
- `apps/backend/routers/control_ui_proxy.py` — item 11
- `apps/infra/lib/lambdas/ws-authorizer/index.ts` — item 12
- `apps/backend/main.py` — item 16 (or new `routers/health.py`)
- `apps/backend/core/repositories/*.py` — DynamoDB wrapper migration (8 files)
- `CLAUDE.md` — §6 above
- `apps/infra/lib/stacks/database-stack.ts` — new dedup table (item 6) — coordinate with Track B
- (Track B coordinates item 14: CloudWatch log retention from 2wk → 3 days)

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Track A's metric module not yet on Track C's branch → tests fail | Stub-import, rebase before merge (see §3) |
| DynamoDB wrapper migration breaks a repo file (subtle await/sync mismatch) | Migrate one repo at a time, run tests after each |
| Gateway token encryption backfill fails partway through | Backfill script is idempotent (skips already-encrypted rows); safe to re-run |
| Item 6 dedup table not yet in CDK when tests run | Tests use moto/localstack to provision the table for unit tests |
| Item 12 (WS Origin) breaks legitimate clients | Verify the allow-list against current production frontend origins before merge |
| CLAUDE.md edits collide with other unrelated branches | Track C touches CLAUDE.md last; lead resolves any merge collisions |

## 10. Definition of done

- [ ] All 6 CRITICAL items (#190 §3 1-6) fixed and tested
- [ ] All 5 HIGH items (#190 §3 7-9, 11-13) fixed and tested
- [ ] All 4 MEDIUM items (#190 §3 14-17) fixed (item 14 partially in Track B)
- [ ] Clerk webhook idempotency implemented (reuses `webhook-event-dedup` table with `clerk:` prefix)
- [ ] DynamoDB throttle wrapper exists; all 8 repo files migrated
- [ ] Gateway token encryption deployed; backfill script run successfully against dev
- [ ] CLAUDE.md updated and reviewed
- [ ] All new tests pass (`turbo run test --filter=@isol8/backend`)
- [ ] Branch builds cleanly under `turbo run lint`
- [ ] Manual smoke test in dev: chat session works, billing webhook works, debug endpoints return 403 if env=prod simulated

## 11. Open questions for the lead

- **Item 6 dedup table location** — **DECIDED: Track C adds the `stripe-event-dedup` table to `database-stack.ts` directly.** Track B reviews the change at integration time. This avoids a blocking handoff.
- **Item 12 (WS Origin) — DECIDED: Track C.** The Lambda is Python at `apps/infra/lambda/websocket-authorizer/index.py`. The security logic belongs with the other security fixes; Track B owns CDK structure but not in-Lambda business logic.
- **Clerk webhook idempotency** — **DECIDED: reuse the same `stripe-event-dedup` DynamoDB table** with a partition key prefix (`clerk:{event_id}` vs `stripe:{event_id}`) rather than creating a second table. The table is renamed to `isol8-{env}-webhook-event-dedup` to reflect its broader purpose. TTL attribute (30 days) applies to both Stripe and Clerk events.
- **DynamoDB wrapper migration scope** — fully migrate all 8 repo files this pass, or only the highest-traffic 3? Recommendation: full migration. The change is mechanical and a half-migrated state is confusing.
