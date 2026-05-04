# Infra/Desktop/Misc Pragmatic Audit — 2026-05-04

Scope: everything outside `apps/frontend/` and `apps/backend/`.
Areas covered: `apps/infra/` (CDK + OpenClaw Dockerfile), `apps/desktop/`
(Tauri 2 + Rust sidecar), the untracked `paperclip/` upstream checkout,
the untracked `.tmp-paperclip-audit/`, root `scripts/`, the dormant
`apps/terraform/`, and `docs/superpowers/{plans,specs}/`.

Source of truth for each area:
- CDK: `apps/infra/lib/stacks/{auth,network,database,container,api,
  service,paperclip,dns,observability}-stack.ts` and `lib/{app,
  isol8-stage,local-stage}.ts`.
- Desktop: `apps/desktop/src-tauri/src/{lib,main,browser_sidecar,
  exec_approvals,node_client,node_invoke,tray}.rs` and
  `apps/desktop/src-tauri/tauri.conf.json`.
- Paperclip: `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/`
  (an untracked upstream `git@github.com:paperclipai/paperclip` clone, HEAD
  `685ee84e`) plus `apps/infra/lib/stacks/paperclip-stack.ts`,
  `apps/infra/paperclip/RUNBOOK.md`, and the backend integration in
  `apps/backend/{routers/paperclip_proxy.py,
  core/services/paperclip_*.py, core/repositories/paperclip_repo.py}`.

---

## Scores per area (0–10, one-line justification each)

- **CDK infra: 7/10.** Cross-stack KMS-cycle posture is consistently
  applied (`secretNames` strings, KMS-key ARNs, explicit `addDependency`)
  and well-commented; encryption + PITR are uniform; but lots of
  copy-paste DRY in `database-stack.ts` (10 nearly-identical
  `dynamodb.Table` blocks) and `service-stack.ts` (numerous `resources:
  ["*"]` IAM statements with hand-written ASCII justifications instead of
  helper constructs).
- **Desktop (Tauri): 8/10.** Small surface (~6 Rust files), clear
  separation of concerns, only **3** `#[tauri::command]` handlers and all
  3 are wired into `generate_handler!` (no dead commands). Production
  `unwrap()` count is low (~13 non-test, all on poisoned-Mutex paths
  where panicking is acceptable). One real footgun: the
  `tauri.conf.json` checked into git points at `dev.isol8.co` and is
  patched by CI per tag — fine for CI, but anyone running `tauri build`
  locally produces a dev-pointing prod-looking DMG.
- **Paperclip: 6/10.** Wired sensibly (Cloud Map for in-VPC reach, ALB
  host-route for public, separate Aurora cluster, separate stack with
  explicit `addDependency`s, secret name-passing + KMS-arn pattern
  matches the rest of the repo). But the upstream Paperclip source
  itself is **a 77 MB untracked sibling-of-the-monorepo git checkout
  living at `paperclip/`** at the repo root, with no `.gitignore` entry
  and no submodule registration. That's a big broken window even if it
  is intentionally a read-only reference (the `route-audit.md` sitting
  in `.tmp-paperclip-audit/` confirms it was used as such).
- **Scripts: 8/10.** Six scripts; all bash scripts use
  `set -euo pipefail` (or `set -eu` for the `/bin/sh` migrate script);
  python scripts have docstrings, dry-run defaults, and clear usage
  blocks. Minor smell: `purge_pre_cutover_users.py` is destructive,
  prod-only, and **untracked** — leaving it on disk uncommitted means
  every contributor has a slightly different copy or none at all.
- **Repo hygiene: 4/10.** Eight untracked things at the repo root
  (`paperclip/`, `.tmp-paperclip-audit/`, `.superpowers/`,
  `.hypothesis/`, `.claude/`, `apps/desktop/src-tauri/.sidecar-tmp/`,
  `scripts/purge_pre_cutover_users.py`, plus 19 untracked
  `docs/superpowers/{plans,specs}/*.md` files). The dormant
  `apps/terraform/` directory still exists with ~80 KB of stale
  `.terraform/` and `.turbo/` cache directories and contains zero `.tf`
  files. Plans/specs have **zero machine-readable status field** (no
  `Status:` header convention), so figuring out which are done /
  abandoned / WIP requires re-reading 40-page docs.

---

## Top 10 Wins (ranked by ROI)

1. **[high] Untracked `paperclip/` upstream clone at repo root —
   77 MB, full git working tree.** `paperclip/` (path:
   `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/`) is a
   complete clone of `git@github.com:paperclipai/paperclip` HEAD
   `685ee84e`, sitting next to `apps/`. It is **not** a submodule
   (no `.gitmodules`), it is **not** ignored (no entry in `.gitignore`),
   and it is **not** committed (it's untracked). It exists because the
   repo needs the upstream as a read-only reference (same role
   `~/Desktop/openclaw` plays for OpenClaw, per
   `reference_openclaw_source.md`). Fix: either (a) add `paperclip/` to
   `.gitignore` and document its role, mirroring the OpenClaw pattern,
   or (b) make it a real git submodule pinned at a sha. (a) is simpler
   and matches the existing OpenClaw convention.
2. **[high] `.tmp-paperclip-audit/` is leftover scratch.** Path:
   `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.tmp-paperclip-audit/`.
   Contains `route-audit.md` (the route-by-route adapter audit dated
   2026-05-02) plus 17 empty stub directories that mirror the `paperclip/`
   tree. The audit doc is real work; the stubs are useless. Fix: move
   `route-audit.md` to `docs/audit-2026-05-02-paperclip-routes.md` and
   commit it (the route filter design references it implicitly), then
   delete the directory.
3. **[high] `apps/terraform/` is a graveyard.** Path:
   `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/terraform/`.
   Contains exactly two subdirectories: `.terraform/` (CLI cache) and
   `.turbo/` (Turborepo cache). Zero `.tf` files. CLAUDE.md already
   says it's "only contains stale cache dirs and is unused." Fix:
   `git rm -r apps/terraform/` (or just `rm -rf` since it's untracked
   already — the path itself isn't in git). Delete in one PR with a
   note.
4. **[high] No `Status:` header convention on plans/specs.** Out of
   42 plans, exactly 1 has a parseable `Status:` line (and the regex
   matched a body sentence, not a header); out of 33 tracked specs,
   2 have a `Status: Draft` header. With ~75 docs and active churn
   between them, the "is this done?" question requires reading the
   doc. Fix: add a one-line `Status: {Draft|Approved|In progress|
   Done|Stale}` to every plan and spec at the top under the title.
   Codify it in CLAUDE.md and writing-plans skill. This costs an
   afternoon and pays back forever.
5. **[medium] 19 untracked `docs/superpowers/{plans,specs}/*.md`
   files.** All in `git status`. Several are clearly real WIP that
   should be committed (e.g. the four flat-fee/provider-choice/
   provision-gate plans + specs match the active branch posture).
   A few look stale (e.g. `2026-04-13-free-tier-scale-to-zero.md`
   when memory `feedback_scale_to_zero_design.md` says scale-to-zero
   was deleted in the 2026-04-27 cutover). Fix: triage in one pass.
   Commit the live ones; delete the dead ones; document the rest as
   WIP with a `Status:` header (Win #4).
6. **[medium] `tauri.conf.json` checked-in default points at dev.**
   Path: `apps/desktop/src-tauri/tauri.conf.json:9-10,23`.
   `devUrl`/`frontendDist`/`windows[0].url` all hard-code
   `https://dev.isol8.co/chat`. CI patches this per tag in
   `.github/workflows/desktop-build.yml:96-118`, so the shipped
   artefacts are correct — but anyone running `tauri build` locally
   from a clean checkout produces a "prod-looking" DMG that talks to
   dev. Fix: either commit the file with a placeholder
   (`"https://__ISOL8_FRONTEND__/chat"`) and fail the build if the CI
   patch step didn't run, or default the local build to a clearly-fake
   sentinel like `https://localhost:3000/chat`. Both make the env
   coupling explicit instead of implicit.
7. **[medium] DynamoDB table boilerplate in `database-stack.ts`.**
   Path: `apps/infra/lib/stacks/database-stack.ts`. 10 tables, each ~10
   lines, all with the same 4 lines of `billingMode` /
   `pointInTimeRecovery` / `encryption` / `encryptionKey` /
   `removalPolicy`. Fix: add a `private createTable(id: string,
   suffix: string, schema: TableSchema): dynamodb.Table` helper.
   Saves ~80 lines, removes the risk that someone forgets `pitr` or
   `encryption: CUSTOMER_MANAGED` on the next table.
8. **[low] Repeated `addEgressRule(anyIpv4, 443)` /
   `addEgressRule(anyIpv4, 80)` pattern.** Across `api-stack.ts`,
   `service-stack.ts`, `paperclip-stack.ts`. Same two-line pattern.
   Fix: a tiny `allowHttpsEgress(sg)` helper in a new
   `lib/util/security-groups.ts`. Two-line saving per call site, but
   makes intent obvious.
9. **[low] `.sidecar-tmp/` is build scratch.** Path:
   `apps/desktop/src-tauri/.sidecar-tmp/`. 24 MB of vendored Node.js
   binaries from `vendor-sidecars.sh`. Fix: add to
   `apps/desktop/.gitignore` (or root `.gitignore` if it isn't already)
   so the directory stops appearing in `git status`.
10. **[low] Compiled CDK artifacts (`*.js`, `*.d.ts`) sitting in
    `apps/infra/lib/stacks/`.** Path: `apps/infra/lib/stacks/*.js`
    and `*.d.ts`. They are correctly gitignored and not tracked, but
    they exist on disk because someone ran `tsc` directly at some
    point instead of letting `cdk synth` use ts-node. They're harmless
    but they pollute every grep and add ~480 KB. Fix: clean them up
    once and ensure local dev workflows go through `cdk synth` /
    `cdk deploy` (which use ts-node, not pre-compiled JS).

---

## Detailed Findings (grouped by area, then by lens)

### CDK Infra

#### DRY
- 10 `dynamodb.Table` blocks in `database-stack.ts` lines ~50–325 are
  identical except for name, partition key, and (sometimes) sort key.
  All set the same five other fields. Single `createTable()` helper
  saves ~80 LOC and prevents drift (e.g. if a future table forgets
  `pointInTimeRecovery: true`, the next data-loss event is on us).
- `addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443))` appears
  multiple times across `api-stack.ts`, `service-stack.ts`,
  `paperclip-stack.ts`. Wrap in `allowHttpsEgress(sg)`.
- 17 IAM statements with `resources: ["*"]` across `container-stack.ts`,
  `service-stack.ts`, `observability-stack.ts`. Each has its own
  hand-written justification comment (good). Most are AWS APIs that
  legitimately don't support resource ARNs (DiscoverInstances,
  ListFoundationModels, CloudWatch metrics writes). A few might be
  scopable — worth a one-pass review with `cdk-nag`'s
  `AwsSolutions-IAM5` rule if not already enabled.

#### Orthogonality
- The "pass secret *names* (strings) and KMS *ARNs* (strings) instead
  of `ISecret` / `IKey` to avoid cross-stack KMS auto-grant cycles"
  pattern is applied **consistently** across `api-stack.ts`,
  `service-stack.ts`, and `paperclip-stack.ts`. `isol8-stage.ts:64`
  ("for cross-stack secret refs to avoid KMS auto-grant cycles") and
  `paperclip-stack.ts:54-67` document the rationale clearly. This is
  a major orthogonality win — the stacks compose without surprise
  ordering or cycles.
- `paperclip-stack.ts` correctly takes `paperclipDbCluster:
  rds.DatabaseCluster` (concrete, not interface) because it needs
  `.secret`. Comment at `paperclip-stack.ts:46-50` calls this out.
  Good.
- `paperclip-stack.ts:71-79` also documents the deliberate
  *non*-coupling: it does NOT open ingress on its own SG from
  FastAPI; instead the rule is added on the FastAPI side via
  `ec2.CfnSecurityGroupIngress` (matching the Aurora-from-Paperclip
  pattern) to avoid cross-stack SG cycles. This is the right choice
  but easy to miss; the comment is essential.
- `isol8-stage.ts:141-144` adds explicit `paperclip.addDependency(...)`
  calls to compensate for the loose coupling (no resource refs ⇒ no
  implicit dep). Necessary; would be invisible without the comment
  block above it.

#### Tracer bullets / half-built
- `apps/infra/openclaw/` is just `Dockerfile` + `README.md` (no stale
  scaffolding). The 13 Go binaries and 8 layers are all referenced in
  the `openclaw.json` config or the upstream extension manifest.
- All 9 stacks instantiated in `isol8-stage.ts` are deployed (no
  defined-but-not-instantiated stacks).
- `paperclip-stack.ts` defines a `migrateTaskDefinition` that has no
  ECS service backing it (one-shot task invoked manually per
  `apps/infra/paperclip/RUNBOOK.md`). Documented + intentional, not
  half-built.
- `apps/infra/lambda/` has 4 lambdas (`websocket-authorizer`,
  `ws-connect`, `ws-disconnect`, `ws-message`). All referenced from
  `api-stack.ts`. None orphaned.

#### Design by contract
- `cdk-nag` does not appear to be enabled. Worth wiring once at the
  app level — would catch all the `resources: ["*"]` cases for review,
  enforce S3 SSL, validate KMS rotation, etc. Even on warnings-only
  this would surface the cases worth tightening.
- Every DynamoDB table sets `pointInTimeRecovery: true` and customer-
  managed KMS encryption. EFS uses the shared KMS key. No S3 buckets
  defined directly in the stacks reviewed (S3 lives in the legacy
  Terraform path, or implicitly via CDK assets).
- All security groups except ALB/Fargate/Paperclip task have
  `allowAllOutbound: false`. Three (ALB, Fargate service, Paperclip
  task, container task) intentionally allow all outbound — documented
  context in each case.

#### Broken windows
- `apps/infra/lib/stacks/*.js` and `*.d.ts` exist on disk but are
  gitignored. Build artifact pollution (`apps/infra/.gitignore` lines
  1–3 ignore them); not tracked but make `grep` output noisy.
- `observability-stack.ts` is **2238 lines**, larger than every other
  stack combined. Likely worth splitting (one file per "alarm
  category" or one file per "dashboard widget group") if anyone has
  to touch it again — but boring deferred work, not a blocker.
- `apps/infra/cdk.out/` (~80 entries) is the synth output; gitignored.
  Fine.

#### Reversibility
- `openclaw-version.json` (`upstream: ghcr.io/openclaw/openclaw:
  2026.4.23`) and the Dockerfile at `apps/infra/openclaw/Dockerfile:65`
  (`FROM ghcr.io/openclaw/openclaw:2026.4.23`) are **in sync today**.
  The Dockerfile comment at line 12-14 acknowledges the manual sync
  burden ("Bump UPSTREAM = `openclaw-version.json#upstream` field.
  Keep the FROM lines below in sync with that field manually until
  automation lands"). Per memory `feedback_dockerfile_from_openclaw_
  version_drift.md`, this drift bit us once (PR #418). Worth a
  pre-commit / CI check that parses both files and fails if they
  disagree (the version json already has a JSON Schema —
  `openclaw-version.schema.json` — adding a Make/CI grep would take
  10 min).

---

### Desktop App (Tauri)

#### DRY
- Three `#[tauri::command]` handlers (`send_auth_token`, `is_desktop`,
  `get_node_status`); all in `lib.rs`. No duplication.
- `update_node_status()` (`lib.rs:125`) and `update_tray_status()`
  (`tray.rs:12`) are right-sized helpers, not duplicated logic.

#### Orthogonality
- `lib.rs` is the orchestrator; `node_client.rs` does the WS
  protocol; `node_invoke.rs` dispatches RPC calls; `exec_approvals.rs`
  is the approval store; `browser_sidecar.rs` supervises the bundled
  Node subprocess; `tray.rs` is just the tray UI. Clean split.
- `exec_approvals.rs` exposes `check_approval`, `record_decision`,
  `get_snapshot` and is consumed only by `node_invoke.rs:7`. Single
  consumer, well-encapsulated.
- One spot of cross-cutting concern: `crate::log()` is a free function
  in `lib.rs:25` that opens `/tmp/isol8-desktop.log` on every call.
  Fine for a desktop app, but reaches across all modules. A `tracing`
  crate would normalize this.

#### Tracer bullets / half-built
- All three registered Tauri commands are called from the WebView
  (verified: `send_auth_token`, `is_desktop`, `get_node_status` are
  the documented JS bridge surface for desktop auth flow).
- `exec_approvals` functions are `pub` but consumed only inside the
  crate; that's fine.
- `browser_sidecar.rs:32 pub fn new_for_test(...)` is a test-only
  constructor; only called from tests in `node_invoke.rs`. Good.

#### Design by contract
- `unwrap()` count: 13 in production paths (3 in `lib.rs`,
  9 in `exec_approvals.rs`, 1 in `node_invoke.rs:199`), plus
  20+ in `#[cfg(test)]` test bodies. The `lib.rs` and
  `exec_approvals.rs` ones are all on `Mutex.lock()` — the
  `PoisonError` case only happens if a previous holder panicked,
  and panicking again is a reasonable choice. The
  `node_invoke.rs:199 argv.split_first().unwrap()` is gated by an
  earlier `if argv.is_empty()` check — safe but worth replacing
  with `if let Some((cmd, args)) = argv.split_first()` for the
  next eyes that read it. The lone production `expect()` is at
  `lib.rs:381 .expect("error while running tauri application")` —
  that's the standard Tauri convention; a panic in `Tauri::run` means
  the app failed to start, nothing useful to recover to.
- No clear API contract on what the JS bridge can call beyond the
  three handlers. `withGlobalTauri: true` in `tauri.conf.json:13`
  exposes the full Tauri JS API to the WebView. Worth narrowing.

#### Broken windows
- `apps/desktop/src-tauri/.sidecar-tmp/` (24 MB of vendored
  `node-v22.14.0-darwin-arm64{,.tar.xz}` from `vendor-sidecars.sh`).
  Untracked, gitignored implicitly (`.tmp-*`?). Worth an explicit
  `apps/desktop/src-tauri/.gitignore` entry to silence `git status`
  noise.

#### Reversibility
- `tauri.conf.json` hardcodes `dev.isol8.co` as the default. CI
  patches per tag (`desktop-build.yml:96-118`) so prod ships
  correctly. Local builds will be wrong unless the dev runs the same
  jq patch. See Win #6.
- `option_env!("ISOL8_WS_URL")` and `option_env!("ISOL8_CALLBACK_URL")`
  are read at compile time (Rust `option_env!` macro). The CI
  workflow sets these env vars in the `tauri-action` step. Good
  pattern — ensures the binary's behaviour matches the bundle config.
- AWS-specific assumptions in Tauri Rust: zero. The desktop app
  doesn't reach AWS directly; it talks to `wss://ws-dev.isol8.co`
  and `https://dev.isol8.co/auth/desktop-callback`. Reversibility OK.

---

### Paperclip — what is it?

**One paragraph:** `paperclip/` at the repo root is an untracked,
77 MB clone of `git@github.com:paperclipai/paperclip.git`, HEAD
`685ee84e` (upstream's `master`). It's the same pattern used for
OpenClaw (`~/Desktop/openclaw`, sibling to the isol8 repo, per
memory `reference_openclaw_source.md`) — a read-only reference
checkout so engineers can grep upstream without re-cloning. The
*deployed* Paperclip is the upstream Docker image
`paperclipai/paperclip:latest`, run as a single Fargate service in
`apps/infra/lib/stacks/paperclip-stack.ts` (603 LOC). The Isol8
backend integrates with it via `apps/backend/routers/paperclip_proxy.py`
plus 8 services under `apps/backend/core/services/paperclip_*.py` and
1 repo (`paperclip_repo.py`). The recent commit `3f6e5c3f feat(teams):
realtime updates — Paperclip WS broker + SWR invalidation (#518)`
is the WebSocket broker glue layered on top of this. The
`.tmp-paperclip-audit/route-audit.md` is a 50 KB security audit of
which Paperclip routes are safe to proxy through (the threat model
is real — Paperclip ships `process` and `http` adapters that allow
arbitrary shell exec / SSRF, and the audit catalogues the 124 routes
that touch `adapterType` and assigns each an ALLOW / BLOCK /
FILTER disposition).

#### Findings

##### DRY
- `paperclip-stack.ts` (603 LOC) has its own KMS-decrypt-on-task
  IAM block, log group, security group, task definition, and Fargate
  service. The pattern is similar to (but not shared with)
  `service-stack.ts`. Worth a future `lib/constructs/
  StandardFargateService.ts` once a third Fargate service appears,
  not before.

##### Orthogonality
- See "CDK Infra ▸ Orthogonality": the cross-stack KMS posture is
  consistently applied here too. Nothing new to flag.
- Backend integration is well factored: `paperclip_admin_client.py`
  (admin API), `paperclip_user_session.py` (per-user session token),
  `paperclip_event_client.py` (WS broker subscriber),
  `paperclip_provisioning.py` (lazy provision on first /teams hit),
  `paperclip_autoprovision.py` (backfill for existing containers).

##### Tracer bullets / half-built
- The teams roadmap (`docs/superpowers/specs/2026-05-04-teams-ui-
  parity-roadmap.md`) tracks 5 sub-projects; the most recent commits
  show the realtime sub-project marked Done (commit `52881186`).
  The remaining sub-projects are explicitly tracked as deferred work,
  which per the brief is *not* a broken window.
- `paperclip-stack.ts:81-92` references "T6 wires the public host
  route on the existing ALB; T14 wires the FastAPI proxy router.
  T14 NOTE: this URL resolves via Cloud Map A records with a
  10-second TTL." T6 and T14 are sub-tasks of an in-progress plan;
  the comments are forward-looking, the code is half-deployed (the
  proxy router exists at `apps/backend/routers/paperclip_proxy.py`).
  Fine.

##### Design by contract
- The `apps/infra/paperclip/RUNBOOK.md` documents the manual-invoke
  contract for the migrate task (no service backing it; operators
  invoke via `aws ecs run-task`). This is a contract by convention,
  not enforcement — easy to forget after a deploy. Future fix: a
  CDK custom resource that runs the migrate task on every
  `cdk deploy` of the Paperclip stack.

##### Broken windows
- The untracked `paperclip/` and `.tmp-paperclip-audit/` directories
  (Wins #1 and #2) are the obvious ones.
- `paperclip/.git/` is a real git working tree on disk that **could
  be committed to** by accident (e.g., a broad `git add -A` from the
  paperclip directory). Not currently a path because no one runs
  `git add -A` from there, but if `paperclip/` were a submodule the
  surface area would shrink.

##### Reversibility
- The deployed image tag isn't pinned — `paperclip-stack.ts` runs
  `paperclipai/paperclip:latest`. (Did not verify the exact tag in
  this audit; if it's `latest`, every `cdk deploy` rolls forward
  to whatever Paperclip published most recently.) Consider pinning
  to a SHA digest the same way `openclaw-version.json` pins
  OpenClaw — gets you reproducible deploys + rollback.

---

### Scripts

`scripts/` has 6 files:

| File | Tracked? | Shell type | Strict mode | Purpose |
|------|----------|------------|-------------|---------|
| `local-dev.sh` | Yes | `#!/bin/bash` | `set -euo pipefail` | LocalStack + CDK + Ollama + backend + frontend orchestration |
| `migrate-agent-workspace.sh` | Yes | `#!/bin/sh` | `set -eu` | One-shot EFS layout migration, runs inside backend ECS task |
| `publish-agent.sh` | Yes | `#!/usr/bin/env bash` | `set -euo pipefail` | Catalog publish helper |
| `seed-local-catalog.py` | Yes | python3 | n/a | Seeds local catalog into LocalStack S3 |
| `extract-ephemeral-config-files.py` | Yes | python3 | n/a | One-shot data rescue: pulls in-container config off ephemeral storage to EFS before workspace-normalization migration |
| `purge_pre_cutover_users.py` | **No (untracked)** | python3 | n/a | One-shot prod data wipe of pre-flat-fee users |

#### DRY
- No two scripts wrap each other. `local-dev.sh` does its own
  `pnpm`/`uv` orchestration; `pnpm` scripts are in `apps/*/package.json`
  not duplicated here. Good.

#### Orthogonality
- Each script is a single-purpose runner. No coupling between them.

#### Tracer bullets / half-built
- `extract-ephemeral-config-files.py` and `migrate-agent-workspace.sh`
  are paired one-shot migration scripts from the workspace-
  normalization rollout. Both have already been run in prod (per the
  CLAUDE.md "Container Re-provisioning" section). Fine to keep around
  for documentation, but neither is a tracer bullet — they're
  finished work.

#### Design by contract
- All bash scripts use `set -euo pipefail` (or `set -eu` for the
  `/bin/sh` migrate script which can't `pipefail` portably). Good.
- All python destructive scripts default to dry-run and require
  explicit `--confirm` / `--apply` to mutate. Good.

#### Broken windows
- **`scripts/purge_pre_cutover_users.py` is untracked.** Path:
  `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/scripts/
  purge_pre_cutover_users.py`. 12 KB, prod-targeted, irreversible
  (cancels Stripe subs, deletes ECS services, deletes DynamoDB rows).
  Leaving it uncommitted means: (a) other contributors don't have it,
  (b) if you change machines it disappears, (c) any "did we run X
  before Y?" audit is harder. Fix: commit it to `scripts/` with a
  `# DEPRECATED: one-shot 2026-04-27 cutover. Do not re-run.` header.

#### Reversibility
- All scripts read `AWS_PROFILE` / env vars rather than baking in
  account IDs (good — though `local-dev.sh` does hard-code
  `us-east-1` once, which is fine since LocalStack only really
  supports that region).

---

### Repo Hygiene

#### Untracked top-level entries (recommendation each)

| Path | Recommendation | Why |
|------|----------------|-----|
| `paperclip/` | `.gitignore` it + add doc note matching the `~/Desktop/openclaw` pattern | Read-only upstream reference clone, 77 MB |
| `.tmp-paperclip-audit/` | Move `route-audit.md` to `docs/audit-2026-05-02-paperclip-routes.md`, then delete the directory | Real audit doc + 17 empty stub dirs |
| `.superpowers/brainstorm/` | `.gitignore` (probably already; verify) | Tool scratch |
| `.hypothesis/unicode_data/` | `.gitignore` | Hypothesis cache |
| `.claude/` | `.gitignore` (probably already; verify) | Claude Code workspace |
| `apps/desktop/src-tauri/.sidecar-tmp/` | `.gitignore` | 24 MB of vendored Node.js binaries, build scratch |
| `scripts/purge_pre_cutover_users.py` | Commit it (with deprecation header) | Destructive prod script needs to be in version control |

#### Untracked `docs/superpowers/{plans,specs}/` files

19 untracked. One-line status guess each (read first paragraph of
each; would need a real triage pass to confirm):

Plans:
- `2026-03-29-skills-dependency-states.md` — looks done (matches the
  current SkillsPanel UI which has "Available / Installed" tabs)
- `2026-03-29-unified-settings-page.md` — looks done (the unified
  settings page exists at `/settings`)
- `2026-04-01-desktop-app.md` — done (desktop app shipped)
- `2026-04-01-mobile-responsive-fix.md` — uncertain; mobile responsive
  work has gone in incrementally
- `2026-04-13-free-tier-scale-to-zero.md` — **stale** (per memory
  `feedback_scale_to_zero_design.md`, scale-to-zero was deleted in
  the 2026-04-27 flat-fee cutover — this plan is now historical)
- `2026-04-14-config-protection.md` — uncertain
- `2026-04-16-resilient-provisioning-state-machine.md` — looks WIP /
  not yet implemented
- `2026-04-26-flat-fee-cutover.md` — done (flat-fee live in prod)
- `2026-05-03-provider-choice-per-owner.md` — current, in flight
- `2026-05-03-provision-gate-ui.md` — current, in flight (commit
  `e2ab5e26 feat(provision-gate): surface provisioning gates in chat
  UI (#519)` is recent)

Specs (matching most plans 1:1):
- 9 design specs corresponding to the 10 plans above + `2026-04-30-
  soci-cdk-restart-prompt.md` which is a one-off "restart prompt for
  the SOCI subagent" — not a normal spec

Recommendation: triage in one batch. Commit the live ones; delete the
stale-and-superseded ones (`free-tier-scale-to-zero` is the clearest
case); add `Status:` headers to all (Win #4).

#### Terraform graveyard

`apps/terraform/` contains only `.terraform/` and `.turbo/` — both
caches, no `.tf` files. CLAUDE.md already documents this. Action:
delete the directory in one PR.

#### Dockerfile vs `openclaw-version.json` drift status

- `openclaw-version.json#upstream` = `ghcr.io/openclaw/openclaw:
  2026.4.23`
- `apps/infra/openclaw/Dockerfile:65` = `FROM ghcr.io/openclaw/
  openclaw:2026.4.23`
- **In sync today.** But the only thing keeping them in sync is the
  Dockerfile comment at line 12-14 telling humans to update both.
  Per memory `feedback_dockerfile_from_openclaw_version_drift.md`,
  this drift bit us once. Add a CI guard (`scripts/check-openclaw-
  version.sh` that greps both files and exits non-zero on mismatch),
  call it from `.github/workflows/build-openclaw-image.yml` and
  `.github/workflows/deploy.yml`.

---

## Cross-Cutting Observations

1. **The "untracked" disease.** The single biggest signal across this
   audit is how many things sit on disk but not in git: `paperclip/`,
   `.tmp-paperclip-audit/`, `scripts/purge_pre_cutover_users.py`, 19
   superpowers plans/specs, and 6+ tool-cache directories. Each one
   is individually defensible (the audit script is one-shot; the
   plans are WIP; the paperclip clone is a reference). Collectively,
   they make `git status` unreadable, hide the fact that some of them
   are *meant* to be committed, and obscure which work is real WIP.
   Fix in three batches: (a) `.gitignore` everything that's truly
   tool scratch, (b) commit everything that's a real artefact
   (scripts, audit doc, live plans), (c) delete everything stale.
   This is one afternoon of work and would dramatically improve
   day-to-day code-health signal.
2. **The `Status:` header gap is the underlying cause** of the
   docs-sprawl problem. With 75+ plans/specs in `docs/superpowers/`
   and zero machine-readable status field, the only way to know
   what's done is to read each one. Adding a one-line `Status:`
   convention pays back across every future "is this implemented?"
   question — including from agents (as both writing-plans and
   executing-plans skills could check it).
3. **The CDK "secret-name-string + KMS-arn-string" pattern is gold.**
   It's the single most thoughtful piece of infra design in this
   repo. Worth distilling into a 2-page "How to add a new stack
   without creating a KMS cycle" doc — the pattern is currently
   only discoverable by reading the comments in `service-stack.ts`,
   `api-stack.ts`, and `paperclip-stack.ts`. A future "PaperclipV2"
   or "OpenClawV2" stack author will benefit.
4. **OpenClaw + Paperclip are following parallel reference-clone
   patterns** (sibling/sub-directory of the monorepo containing a
   read-only upstream checkout). Standardize this: one
   `references/{openclaw,paperclip}/` directory at the repo root,
   gitignored, with a top-level README explaining how to clone each
   one for greppable reference. Right now OpenClaw is at
   `~/Desktop/openclaw` (outside the repo) and Paperclip is at
   `paperclip/` (inside the repo, untracked). Inconsistent.
5. **Reversibility on third-party images.** `openclaw-version.json`
   pins OpenClaw to a specific tag with per-env tags for the extended
   image. Good. Paperclip is deployed as `paperclipai/paperclip:
   latest` (verify this in the stack). If true, the same pinning
   discipline should apply: a `paperclip-version.json` with `image`,
   `tag`, and per-env extended tags if/when we extend it.
