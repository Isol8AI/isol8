# Resilient Provisioning State Machine Implementation Plan

**Status:** Draft

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix containers getting stuck at `status="provisioning"` in DDB while running in ECS, by removing the 120s timeout on `_await_running_transition` and adding proper exit conditions driven by ECS deployment circuit breaker.

**Architecture:** (1) Enable the ECS deployment circuit breaker on per-user services so `rolloutState="FAILED"` becomes the definitive failure signal. (2) Rewrite `_await_running_transition` as a durable loop with four exit paths (healthy → `"running"`, circuit breaker tripped → `"error"`, DDB status changed externally → return, `CancelledError` → return). (3) Fire the poller from `start_user_service` (cold-start restart path) and from a startup reconciler in `main.py` lifespan so any stuck-provisioning row gets picked up after a deploy.

**Tech Stack:** Python 3.13 / FastAPI (backend), pytest + unittest.mock (tests), AWS Fargate ECS, DynamoDB.

**Related spec:** `docs/superpowers/specs/2026-04-15-resilient-provisioning-state-machine-design.md`

---

## File Structure

### Backend
- **`apps/backend/core/containers/ecs_manager.py`** — three edits: (1) add `deploymentConfiguration` to the `create_service` call around line 291, (2) rewrite `_await_running_transition` around lines 885-969, (3) fire `_await_running_transition` at the end of `start_user_service` around line 396.
- **`apps/backend/main.py`** — add a startup reconciler after `startup_containers()` in the `lifespan` handler.

### Tests
- **`apps/backend/tests/unit/containers/test_ecs_manager.py`** — extend with new-behavior tests for `create_user_service` (circuit breaker), `start_user_service` (poller fires), and a new `TestAwaitRunningTransition` class.
- **`apps/backend/tests/unit/test_main_lifespan.py`** — extend with a test for the startup reconciler.

### Pre-flight
Before starting, create a worktree per the user's workflow. From repo root:
```bash
git worktree add -b fix/resilient-provisioning-state-machine ../isol8-rpsm origin/main
cd ../isol8-rpsm
pnpm install
cd apps/backend && uv sync && cd ../..
```

All commits on this branch live in the worktree, never in the main checkout.

---

## Task 1: Enable deployment circuit breaker in `create_user_service`

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py` (the `create_service` call around line 273-291)
- Test: `apps/backend/tests/unit/containers/test_ecs_manager.py` (extend `TestCreateUserService`)

**Context for the engineer:**
- The per-user service is created via `self._ecs.create_service(**create_kwargs)` inside `create_user_service` (method starts at line 217).
- The backend's own ECS service in CDK (`apps/infra/lib/stacks/service-stack.ts:624`) already uses `circuitBreaker: { rollback: true }`. We are applying the same pattern to per-user services, but with `rollback=False` because a brand-new service has no previous deployment to roll back to.
- The ECS API parameter is `deploymentConfiguration.deploymentCircuitBreaker.enable` (a bool) and `.rollback` (a bool).
- Test style: existing tests use `pytest.mark.asyncio`, the `manager` fixture, and `patch("core.containers.ecs_manager.container_repo")`. Follow that.

- [ ] **Step 1.1: Write a failing test for the circuit breaker config**

Add to `apps/backend/tests/unit/containers/test_ecs_manager.py` inside the existing `TestCreateUserService` class:

```python
    @pytest.mark.asyncio
    async def test_create_service_enables_deployment_circuit_breaker(
        self, manager, mock_ecs_client, mock_efs_client
    ):
        """create_service MUST pass deploymentCircuitBreaker so ECS surfaces a
        rolloutState=FAILED signal when a per-user provision fails (bad image,
        crash loop). Without this, _await_running_transition has no way to
        distinguish a slow start from a permanent failure."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.upsert = AsyncMock(return_value=_make_container_dict(status="provisioning"))
            mock_repo.update_fields = AsyncMock(return_value=_make_container_dict())

            await manager.create_user_service("user_test_123", "token-abc")

            call_kwargs = mock_ecs_client.create_service.call_args.kwargs
            dc = call_kwargs.get("deploymentConfiguration") or {}
            cb = dc.get("deploymentCircuitBreaker") or {}
            assert cb.get("enable") is True, (
                "Deployment circuit breaker must be enabled so rolloutState=FAILED "
                "can be used as the failure signal by _await_running_transition."
            )
            # rollback=False: no previous deployment to roll back to on first deploy.
            assert cb.get("rollback") is False
```

- [ ] **Step 1.2: Verify the test fails**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestCreateUserService::test_create_service_enables_deployment_circuit_breaker -v`
Expected: FAIL — `AssertionError: Deployment circuit breaker must be enabled...`

- [ ] **Step 1.3: Implement the circuit breaker config**

In `apps/backend/core/containers/ecs_manager.py`, locate the `create_kwargs = dict(...)` block inside `create_user_service` (around line 273). Add a `deploymentConfiguration` key:

```python
            create_kwargs = dict(
                cluster=self._cluster,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                desiredCount=0,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self._subnets,
                        "securityGroups": self._security_groups,
                        "assignPublicIp": "DISABLED",
                    }
                },
                serviceRegistries=[{"registryArn": self._cloud_map_service_arn}],
                deploymentConfiguration={
                    "deploymentCircuitBreaker": {
                        "enable": True,
                        "rollback": False,
                    }
                },
            )
```

- [ ] **Step 1.4: Verify the test passes**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestCreateUserService -v`
Expected: All tests in `TestCreateUserService` PASS (existing + the new one).

- [ ] **Step 1.5: Commit**

```bash
git add apps/backend/core/containers/ecs_manager.py \
        apps/backend/tests/unit/containers/test_ecs_manager.py
git commit -m "feat(containers): enable deployment circuit breaker on per-user services

ECS will now mark rolloutState=FAILED after 2 failed task placements on a
per-user service, giving _await_running_transition a definitive failure
signal to distinguish a permanent failure (bad image, crash loop) from a
slow cold start. rollback=False because a brand-new service has nothing
to roll back to."
```

---

## Task 2: Rewrite `_await_running_transition` as a durable loop

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py` (`_await_running_transition` at lines ~885-969)
- Test: `apps/backend/tests/unit/containers/test_ecs_manager.py` (new `TestAwaitRunningTransition` class)

**Context for the engineer:**
- Current method signature: `async def _await_running_transition(self, user_id, *, max_attempts=30, interval_s=4.0)`. The new signature drops `max_attempts` (no artificial timeout) and keeps `interval_s` (defaulting to 10.0 for the reduced polling rate).
- The poller must:
  1. On each iteration, re-read the container row from DDB and exit silently if `status != "provisioning"` (handles external state changes).
  2. Check ECS `list_tasks(desiredStatus="RUNNING")` → `describe_tasks` → if a task is RUNNING with an IP and `is_healthy(ip)` succeeds, write `status="running"`, `substatus="gateway_healthy"`, store `task_arn`, return.
  3. If no healthy task, call `describe_services` once and inspect `services[0]["deployments"][0]["rolloutState"]`. If `"FAILED"`, write `status="error"` and return.
  4. Otherwise `await asyncio.sleep(interval_s)` and loop.
  5. Must respect `asyncio.CancelledError` for clean shutdown — re-raise or return quietly (do NOT swallow into a retry).
- `describe_services` optimisation: only call it when we didn't find a healthy running task this iteration, so the happy path doesn't pay the extra API call. (Spec "Change 2" — ECS API rate limits).
- Existing fixtures: `manager`, `mock_ecs_client`, `mock_efs_client`, `_make_container_dict`. The mock_ecs_client needs `describe_services` mocked — default return value `{"services": [{"deployments": [{"rolloutState": "IN_PROGRESS"}]}]}` so the happy path doesn't spuriously flip to error.
- Tests use `asyncio.sleep` extensively inside the poller. Use `patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock)` to make tests instantaneous.

- [ ] **Step 2.1: Update the ECS mock fixture to stub `describe_services` and `describe_tasks`**

At the top of `mock_ecs_client` fixture (around line 24-57) add, just before `client.deregister_task_definition.return_value = {}`:

```python
    client.describe_services.return_value = {
        "services": [
            {
                "serviceName": "openclaw-user_test_123-f4ae64abb2db",
                "deployments": [{"rolloutState": "IN_PROGRESS"}],
            }
        ]
    }
    client.list_tasks.return_value = {"taskArns": []}
    client.describe_tasks.return_value = {"tasks": []}
```

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py -v` — all existing tests should still PASS. Fixtures are additive.

- [ ] **Step 2.2: Write failing tests for the new `_await_running_transition` behavior**

Append a new class at the end of `apps/backend/tests/unit/containers/test_ecs_manager.py`:

```python
# ---------------------------------------------------------------------------
# _await_running_transition (durable provisioning -> running poller)
# ---------------------------------------------------------------------------


class TestAwaitRunningTransition:
    """The poller that drives provisioning -> running in the background.

    Must be durable (no fixed timeout) and have proper exit conditions so a
    container can never be left stuck at status=provisioning forever while
    actually running in ECS.
    """

    @pytest.mark.asyncio
    async def test_transitions_to_running_when_task_healthy(
        self, manager, mock_ecs_client
    ):
        """Container becomes reachable -> write status=running and exit."""
        mock_ecs_client.list_tasks.return_value = {
            "taskArns": [
                "arn:aws:ecs:us-east-1:123:task/cluster/abc"
            ]
        }
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {"name": "privateIPv4Address", "value": "10.0.1.42"}
                            ],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "running"
            assert fields["substatus"] == "gateway_healthy"
            assert fields["task_arn"] == "arn:aws:ecs:us-east-1:123:task/cluster/abc"

    @pytest.mark.asyncio
    async def test_transitions_to_error_when_circuit_breaker_trips(
        self, manager, mock_ecs_client
    ):
        """ECS deployment rolloutState=FAILED -> write status=error and exit.

        This is the definitive failure signal: the circuit breaker only trips
        after N failed task placements, so we know the provision will never
        succeed on its own (bad image, crash loop, etc.)."""
        mock_ecs_client.list_tasks.return_value = {"taskArns": []}
        mock_ecs_client.describe_services.return_value = {
            "services": [
                {"deployments": [{"rolloutState": "FAILED"}]}
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "error"

    @pytest.mark.asyncio
    async def test_exits_silently_when_ddb_status_changed_externally(
        self, manager, mock_ecs_client
    ):
        """If another actor (admin, reaper, re-provision) changed the DDB status
        under us, exit without writing anything — our job is done or obsolete."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="stopped")
            )
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_exits_silently_when_row_missing(
        self, manager, mock_ecs_client
    ):
        """Container row deleted -> exit. No row to transition."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(return_value=None)
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_keeps_polling_when_task_not_yet_healthy(
        self, manager, mock_ecs_client
    ):
        """On iteration N no running task, on iteration N+1 it's healthy -> transition.

        Regression for the 120s timeout bug: a container that takes >2 minutes
        to become reachable MUST still get transitioned when it eventually is."""
        # First poll: no tasks. Second poll: a healthy task.
        mock_ecs_client.list_tasks.side_effect = [
            {"taskArns": []},
            {"taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/abc"]},
        ]
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {"name": "privateIPv4Address", "value": "10.0.1.42"}
                            ],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_called_once()
            fields = mock_repo.update_fields.call_args.args[1]
            assert fields["status"] == "running"

    @pytest.mark.asyncio
    async def test_skips_describe_services_on_happy_path(
        self, manager, mock_ecs_client
    ):
        """When a healthy task is found immediately, we should NOT call
        describe_services — that call is only needed when we're waiting and
        need to check for failure. Avoids hitting the 20 req/s limit on
        describe_services when many containers are provisioning concurrently."""
        mock_ecs_client.list_tasks.return_value = {
            "taskArns": ["arn:aws:ecs:us-east-1:123:task/cluster/abc"]
        }
        mock_ecs_client.describe_tasks.return_value = {
            "tasks": [
                {
                    "lastStatus": "RUNNING",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {"name": "privateIPv4Address", "value": "10.0.1.42"}
                            ],
                        }
                    ],
                }
            ]
        }

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(manager, "is_healthy", return_value=True),
            patch("core.containers.ecs_manager.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )
            mock_repo.update_fields = AsyncMock()

            await manager._await_running_transition("user_test_123")

            mock_ecs_client.describe_services.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_cancellation(self, manager, mock_ecs_client):
        """Clean shutdown: if the event loop cancels the task (backend restart),
        the poller exits without raising into the caller and without writing
        a status transition."""
        import asyncio as _asyncio

        mock_ecs_client.list_tasks.return_value = {"taskArns": []}
        mock_ecs_client.describe_services.return_value = {
            "services": [{"deployments": [{"rolloutState": "IN_PROGRESS"}]}]
        }

        # asyncio.sleep raises CancelledError inside the poller loop.
        async def cancel_on_sleep(*args, **kwargs):
            raise _asyncio.CancelledError()

        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch("core.containers.ecs_manager.asyncio.sleep", side_effect=cancel_on_sleep),
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )
            mock_repo.update_fields = AsyncMock()

            # Must not swallow CancelledError — asyncio task cancellation
            # semantics require it to propagate out.
            with pytest.raises(_asyncio.CancelledError):
                await manager._await_running_transition("user_test_123")

            mock_repo.update_fields.assert_not_called()
```

- [ ] **Step 2.3: Verify the tests fail**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestAwaitRunningTransition -v`
Expected: All 7 tests FAIL — mostly because the current implementation has a fixed timeout, doesn't check `rolloutState`, and the shape of the new tests doesn't match the old `max_attempts` behavior.

- [ ] **Step 2.4: Rewrite `_await_running_transition`**

In `apps/backend/core/containers/ecs_manager.py`, replace the entire method body (currently at lines ~885-969) with:

```python
    async def _await_running_transition(
        self,
        user_id: str,
        *,
        interval_s: float = 10.0,
    ) -> None:
        """Durable background poller that drives provisioning -> running.

        Exits on one of four conditions:

        1. Container is reachable (ECS task RUNNING + gateway port open):
           write status=running, substatus=gateway_healthy, store task_arn,
           return.
        2. DDB status is no longer "provisioning" (external state change —
           admin stop, re-provision, reaper, etc.): return silently.
        3. ECS deployment rolloutState=FAILED (circuit breaker tripped — the
           provision will never succeed): write status=error, return.
        4. asyncio.CancelledError (backend shutdown): propagate.

        No fixed timeout. The container can take 10s or 10 minutes to become
        healthy — the poller keeps going until one of the above happens.
        """
        while True:
            try:
                container = await container_repo.get_by_owner_id(user_id)
                if not container or container.get("status") != "provisioning":
                    # External state change or row gone — nothing to do.
                    return

                service_name = container["service_name"]

                # Try to find a healthy running task.
                task_arn, ip = await self._poll_running_task(service_name)
                if task_arn and ip and self.is_healthy(ip):
                    await container_repo.update_fields(
                        user_id,
                        {
                            "status": "running",
                            "substatus": "gateway_healthy",
                            "task_arn": task_arn,
                        },
                    )
                    logger.info(
                        "Transitioned container %s to running (user=%s, task=%s)",
                        service_name,
                        user_id,
                        task_arn.split("/")[-1],
                    )
                    return

                # No healthy task yet — check whether the circuit breaker tripped.
                # We only issue this describe_services call on the slow path so
                # the happy path stays cheap (ECS DescribeServices is 20 req/s).
                if await self._deployment_failed(service_name):
                    await container_repo.update_fields(
                        user_id,
                        {
                            "status": "error",
                            "substatus": "deployment_failed",
                        },
                    )
                    logger.error(
                        "Deployment circuit breaker tripped for container %s (user=%s); marking error",
                        service_name,
                        user_id,
                    )
                    return

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Unexpected error in _await_running_transition for %s; will retry",
                    user_id,
                )

            await asyncio.sleep(interval_s)

    async def _poll_running_task(
        self, service_name: str
    ) -> tuple[str | None, str | None]:
        """Find a RUNNING task for the service and return (task_arn, ip).

        Returns (None, None) when no RUNNING task has an IP yet. Caller uses
        this to decide whether to check for circuit-breaker failure.
        """
        list_resp = self._ecs.list_tasks(
            cluster=self._cluster,
            serviceName=service_name,
            desiredStatus="RUNNING",
        )
        task_arns = list_resp.get("taskArns", [])
        if not task_arns:
            return None, None

        desc_resp = self._ecs.describe_tasks(
            cluster=self._cluster,
            tasks=[task_arns[0]],
        )
        tasks = desc_resp.get("tasks", [])
        if not tasks or tasks[0].get("lastStatus") != "RUNNING":
            return None, None

        for attachment in tasks[0].get("attachments", []):
            if attachment.get("type") != "ElasticNetworkInterface":
                continue
            for detail in attachment.get("details", []):
                if detail.get("name") == "privateIPv4Address":
                    return task_arns[0], detail.get("value")
        return None, None

    async def _deployment_failed(self, service_name: str) -> bool:
        """True when ECS has marked the service's latest deployment FAILED."""
        try:
            resp = self._ecs.describe_services(
                cluster=self._cluster,
                services=[service_name],
            )
            services = resp.get("services", [])
            if not services:
                return False
            deployments = services[0].get("deployments", [])
            if not deployments:
                return False
            return deployments[0].get("rolloutState") == "FAILED"
        except Exception:
            # If describe_services fails, don't flip to error — retry next cycle.
            logger.warning(
                "describe_services failed for %s; assuming not-failed", service_name
            )
            return False
```

Also make sure the file's call site for the old signature (`max_attempts=30, interval_s=4.0`) is removed. The only existing call is inside `provision_user_container` (around line 881) and it passes no kwargs — no edit required there.

- [ ] **Step 2.5: Verify the tests pass**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestAwaitRunningTransition -v`
Expected: All 7 tests PASS.

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py -v`
Expected: All tests in the file still PASS (no regressions in `TestCreateUserService`, `TestStopUserService`, etc.).

- [ ] **Step 2.6: Commit**

```bash
git add apps/backend/core/containers/ecs_manager.py \
        apps/backend/tests/unit/containers/test_ecs_manager.py
git commit -m "refactor(containers): make _await_running_transition durable

Root-cause fix for containers stuck at status=provisioning in DDB while
running in ECS. The old poller gave up after 30 attempts x 4s = 120s,
leaving the DDB row permanently mis-stated for any container whose ECS
task took longer than 2 minutes to become healthy.

New behavior: poll indefinitely at 10s intervals. Four exit paths, all
driven by real state transitions rather than an arbitrary timer:

- Healthy task     -> status=running  (success)
- rolloutState=FAILED -> status=error (circuit breaker tripped)
- DDB status changed externally -> return silently
- CancelledError   -> propagate (clean shutdown)

describe_services is only called on the slow path, so the happy-path
API cost stays at list_tasks + describe_tasks per iteration."
```

---

## Task 3: Fire `_await_running_transition` from `start_user_service`

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py` (`start_user_service` around lines 363-396)
- Test: `apps/backend/tests/unit/containers/test_ecs_manager.py` (new test inside existing `TestStartUserService` class; create the class if it doesn't exist)

**Context for the engineer:**
- `POST /container/provision` for a stopped container calls `start_user_service` (`routers/container.py:114`). Today that path sets `status="provisioning"` via `update_status` but never fires the transition poller — so a cold-start restart has the same stuck-provisioning risk that Task 2 fixed for the new-provision path.
- The invariant we're enforcing: any code path that sets `status="provisioning"` must ensure a transition poller is running.
- The existing `provision_user_container` (around line 881) already does `asyncio.create_task(self._await_running_transition(user_id))` — we mirror that.
- Check whether `TestStartUserService` exists in the test file first (grep). If not, create the class following the style of `TestStopUserService`.

- [ ] **Step 3.1: Check for an existing `TestStartUserService` class**

Run: `grep -n "class TestStartUserService" apps/backend/tests/unit/containers/test_ecs_manager.py`

If it does NOT exist, add a new class at the bottom of the file, after the existing tests but before `TestAwaitRunningTransition`. If it does, append the new test inside it. The step below assumes you're creating it fresh — adapt if the class already exists.

- [ ] **Step 3.2: Write a failing test**

Add to `apps/backend/tests/unit/containers/test_ecs_manager.py`:

```python
# ---------------------------------------------------------------------------
# start_user_service (cold-start restart path)
# ---------------------------------------------------------------------------


class TestStartUserService:
    """Scaling a stopped service back to desiredCount=1."""

    @pytest.mark.asyncio
    async def test_start_scales_to_one(self, manager, mock_ecs_client):
        """start_user_service calls update_service with desiredCount=1."""
        with patch("core.containers.ecs_manager.container_repo") as mock_repo:
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="stopped")
            )
            mock_repo.update_status = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )

            await manager.start_user_service("user_test_123")

            mock_ecs_client.update_service.assert_called_once_with(
                cluster=manager._cluster,
                service="openclaw-user_test_123-f4ae64abb2db",
                desiredCount=1,
                forceNewDeployment=True,
            )
            mock_repo.update_status.assert_called_once_with("user_test_123", "provisioning")

    @pytest.mark.asyncio
    async def test_start_fires_running_transition_poller(
        self, manager, mock_ecs_client
    ):
        """Cold-start restart MUST fire _await_running_transition, or the cold-
        started container will get stuck at status=provisioning forever when
        its ECS task takes >10s to become healthy and the user leaves before
        making another request."""
        with (
            patch("core.containers.ecs_manager.container_repo") as mock_repo,
            patch.object(
                manager, "_await_running_transition", new_callable=AsyncMock
            ) as mock_await,
        ):
            mock_repo.get_by_owner_id = AsyncMock(
                return_value=_make_container_dict(status="stopped")
            )
            mock_repo.update_status = AsyncMock(
                return_value=_make_container_dict(status="provisioning")
            )

            await manager.start_user_service("user_test_123")

            # Give the fire-and-forget task a chance to be scheduled.
            # asyncio.create_task schedules it immediately; a yield is enough.
            import asyncio as _asyncio
            await _asyncio.sleep(0)

            mock_await.assert_called_once_with("user_test_123")
```

- [ ] **Step 3.3: Verify the new test fails**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestStartUserService::test_start_fires_running_transition_poller -v`
Expected: FAIL — `mock_await.assert_called_once_with("user_test_123")` — `_await_running_transition` was never called.

- [ ] **Step 3.4: Fire the poller from `start_user_service`**

In `apps/backend/core/containers/ecs_manager.py`, edit `start_user_service` (around lines 363-396). After the `container_repo.update_status(user_id, "provisioning")` call and the final `logger.info(...)`, add the fire-and-forget task:

```python
    async def start_user_service(self, user_id: str) -> None:
        """Scale a user's ECS service to 1 (running) with forced new deployment.

        Fires _await_running_transition afterwards so the provisioning -> running
        transition happens eventually even if the user disconnects before the
        ECS task finishes warming up. Without this, cold-start restart rows
        get stuck at status=provisioning forever.

        Args:
            user_id: Clerk user ID.

        Raises:
            EcsManagerError: If the ECS update_service call fails.
        """
        service_name = self._service_name(user_id)
        put_metric("container.lifecycle.state_change", dimensions={"state": "starting"})

        try:
            with timing("container.lifecycle.latency", {"op": "start"}):
                self._ecs.update_service(
                    cluster=self._cluster,
                    service=service_name,
                    desiredCount=1,
                    forceNewDeployment=True,
                )
        except Exception as e:
            logger.error(
                "Failed to start ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to start ECS service: {e}", user_id)

        container = await container_repo.get_by_owner_id(user_id)
        if container:
            await container_repo.update_status(user_id, "provisioning")

        logger.info("Started ECS service %s for user %s", service_name, user_id)

        # Fire the durable poller. Any code path that sets status=provisioning
        # MUST ensure a transition poller is running, otherwise a slow ECS
        # cold-start leaves the row stuck.
        asyncio.create_task(self._await_running_transition(user_id))
```

- [ ] **Step 3.5: Verify the new test passes**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py::TestStartUserService -v`
Expected: Both tests PASS.

- [ ] **Step 3.6: Run the full ecs_manager test file to check for regressions**

Run: `cd apps/backend && uv run pytest tests/unit/containers/test_ecs_manager.py -v`
Expected: All tests PASS.

- [ ] **Step 3.7: Commit**

```bash
git add apps/backend/core/containers/ecs_manager.py \
        apps/backend/tests/unit/containers/test_ecs_manager.py
git commit -m "fix(containers): fire _await_running_transition from start_user_service

Cold-start restart (POST /container/provision for a stopped container)
sets status=provisioning but previously did not fire the transition
poller -- only provision_user_container did. That left any cold-started
container whose ECS task took >10s to become healthy permanently stuck
at status=provisioning when the user disconnected before the first
successful RPC.

The invariant now holds across every entry point: any code that sets
status=provisioning also ensures a transition poller is running."
```

---

## Task 4: Startup reconciler in `main.py` lifespan

**Files:**
- Modify: `apps/backend/main.py` (the `lifespan` context manager around lines 67-91)
- Test: `apps/backend/tests/unit/test_main_lifespan.py` (extend the existing file)

**Context for the engineer:**
- `lifespan` at `main.py:67` currently does: `startup_containers()`, `create_task(run_scheduled_worker())`, `create_task(_safe_idle_checker())`, then yields. We add a reconciler step before the yield.
- The reconciler reads `container_repo.get_by_status("provisioning")` and kicks off `_await_running_transition` for each row. This covers any container that was mid-transition when the backend last shut down (deploy, crash, scale event).
- The existing `test_main_lifespan.py` already imports `main._safe_idle_checker`. Follow that import style.
- For testability, factor the reconciler into a module-level function so the test can call it directly without going through the full `lifespan` context manager. The `lifespan` function calls this helper.
- `get_ecs_manager()` is already imported as part of the `core.containers` import tree (see `main.py:22`: `from core.containers import get_gateway_pool, startup_containers, shutdown_containers`). Add `get_ecs_manager` to that import. `container_repo` import: `from core.repositories import container_repo`.

- [ ] **Step 4.1: Write failing tests**

Append to `apps/backend/tests/unit/test_main_lifespan.py`:

```python
@pytest.mark.asyncio
async def test_resume_provisioning_transitions_kicks_off_poller_per_row():
    """After a backend restart any container still in status=provisioning in
    DDB MUST have its transition poller resumed. Without this, a deploy that
    lands mid-provision permanently strands the container at status=provisioning
    because the original asyncio task was killed on shutdown."""
    from main import _resume_provisioning_transitions

    provisioning_rows = [
        {"owner_id": "user_a", "status": "provisioning"},
        {"owner_id": "user_b", "status": "provisioning"},
    ]

    mock_ecs = MagicMock()
    mock_ecs._await_running_transition = AsyncMock()

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=provisioning_rows,
        ) as mock_get,
        patch("main.get_ecs_manager", return_value=mock_ecs),
    ):
        await _resume_provisioning_transitions()

        # Give fire-and-forget tasks a chance to be scheduled and awaited.
        import asyncio as _asyncio
        await _asyncio.sleep(0)

        mock_get.assert_awaited_once_with("provisioning")
        assert mock_ecs._await_running_transition.await_count == 2
        awaited_users = {
            call.args[0] for call in mock_ecs._await_running_transition.await_args_list
        }
        assert awaited_users == {"user_a", "user_b"}


@pytest.mark.asyncio
async def test_resume_provisioning_transitions_tolerates_empty():
    """Zero provisioning rows -> no-op, no error."""
    from main import _resume_provisioning_transitions

    mock_ecs = MagicMock()
    mock_ecs._await_running_transition = AsyncMock()

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("main.get_ecs_manager", return_value=mock_ecs),
    ):
        await _resume_provisioning_transitions()

        mock_ecs._await_running_transition.assert_not_called()


@pytest.mark.asyncio
async def test_resume_provisioning_transitions_tolerates_ddb_failure():
    """get_by_status raising MUST NOT crash backend startup -- reconciliation
    is best-effort; a transient DDB error should be logged and shrug off."""
    from main import _resume_provisioning_transitions

    with (
        patch(
            "main.container_repo.get_by_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ddb transient"),
        ),
        patch("main.get_ecs_manager") as mock_get_ecs,
    ):
        # Must not raise.
        await _resume_provisioning_transitions()

        mock_get_ecs.assert_not_called()
```

- [ ] **Step 4.2: Verify the tests fail**

Run: `cd apps/backend && uv run pytest tests/unit/test_main_lifespan.py -v`
Expected: The three new tests FAIL with `ImportError: cannot import name '_resume_provisioning_transitions' from 'main'`.

- [ ] **Step 4.3: Implement the reconciler and wire it into `lifespan`**

In `apps/backend/main.py`:

1. Update the `core.containers` import (around line 22) to also expose `get_ecs_manager`:

```python
from core.containers import (
    get_ecs_manager,
    get_gateway_pool,
    startup_containers,
    shutdown_containers,
)
```

2. Add `container_repo` import (alongside `core.observability.metrics`, around line 23):

```python
from core.repositories import container_repo
```

3. Add a new module-level helper right after `_safe_idle_checker` (around line 65):

```python
async def _resume_provisioning_transitions() -> None:
    """Resume the provisioning -> running poller for any containers that were
    mid-transition when the backend last shut down.

    ``_await_running_transition`` is an in-process asyncio task — a deploy or
    crash kills it mid-poll. DDB ``status="provisioning"`` is the durable
    marker that the transition hasn't completed; on startup we find those
    rows and re-kick the poller. The poller itself is idempotent (if the
    container is already healthy, the first iteration transitions it to
    running and exits).
    """
    try:
        rows = await container_repo.get_by_status("provisioning")
    except Exception:
        logger.warning(
            "Could not resume provisioning transitions on startup", exc_info=True
        )
        return

    ecs = get_ecs_manager()
    for row in rows:
        owner_id = row["owner_id"]
        asyncio.create_task(ecs._await_running_transition(owner_id))
        logger.info("Resumed provisioning -> running poller for %s", owner_id)
```

4. Call it inside `lifespan` right after `startup_containers()`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting application...")
    await startup_containers()
    await _resume_provisioning_transitions()
    worker_task = asyncio.create_task(run_scheduled_worker())

    idle_checker_task = asyncio.create_task(_safe_idle_checker())

    yield

    # Shutdown
    logger.info("Shutting down application...")
    idle_checker_task.cancel()
    worker_task.cancel()
    try:
        await idle_checker_task
    except asyncio.CancelledError:
        pass
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await shutdown_containers()
```

- [ ] **Step 4.4: Verify the tests pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_main_lifespan.py -v`
Expected: All tests PASS (the original `test_safe_idle_checker_emits_crash_metric_on_exception` plus the three new ones).

- [ ] **Step 4.5: Run the full backend test suite to check for regressions**

Run: `cd apps/backend && uv run pytest -v`
Expected: All tests PASS. No existing tests should have been affected.

- [ ] **Step 4.6: Commit**

```bash
git add apps/backend/main.py apps/backend/tests/unit/test_main_lifespan.py
git commit -m "feat(main): resume provisioning -> running pollers on startup

On backend startup, scan DDB for any containers stuck in status=provisioning
and re-kick _await_running_transition for each. Handles the case where a
deploy, crash, or scale event killed the in-process poller mid-transition.

Combined with the durable poller (previous commit) and the cold-start
firing (also previous commit), this closes every remaining path that
could leave a container stuck at status=provisioning forever."
```

---

## Self-Review Checklist

Run through this before handing off to execution:

1. **Spec coverage** — each section of `docs/superpowers/specs/2026-04-15-resilient-provisioning-state-machine-design.md` maps to:
   - "Change 1: Enable deployment circuit breaker" → Task 1.
   - "Change 2: Make `_await_running_transition` durable" → Task 2.
   - "Change 3: Fire the poller from `start_user_service`" → Task 3.
   - "Change 4: Startup reconciler" → Task 4.
   - Unit tests 1–4 (`_await_running_transition`) → Task 2.
   - Unit test 5 (`start_user_service`) → Task 3.
   - Unit test 6 (startup reconciler) → Task 4.
   - Prod verification → Manual post-deploy step (below), not a TDD step.

2. **Placeholders** — none. Every code block is complete, every command is exact.

3. **Type/method consistency** —
   - `_await_running_transition(self, user_id, *, interval_s=10.0)` signature is consistent in Task 2 (definition), Task 3 (fire site), Task 4 (fire site, reconciler).
   - The two new helpers `_poll_running_task` and `_deployment_failed` are only referenced inside `_await_running_transition` (Task 2) — no dangling references in later tasks.
   - Field names on `update_fields`: `status`, `substatus`, `task_arn` — match what `resolve_running_container` uses (line 667).
   - Test imports: `from main import _resume_provisioning_transitions` and `from main import _safe_idle_checker` both require the helpers to be module-level — handled in Task 4 Step 4.3.

4. **Ambiguity** — none intentional. One explicit note in Task 3.1 about checking whether `TestStartUserService` already exists; instructions adapt.

5. **Commits** — five commits, each focused on a single logical change, each with a descriptive message.

---

## Post-implementation verification (not TDD-amenable — run manually)

### Integration in dev

After deploying to dev, verify the fix against the stuck dev container:

1. Check the dev DDB row for `user_3CGfQjbn8P3n6ZzGxz1txeqEFzC`:
   ```bash
   aws dynamodb get-item \
     --table-name isol8-dev-containers \
     --key '{"owner_id": {"S": "user_3CGfQjbn8P3n6ZzGxz1txeqEFzC"}}' \
     --profile isol8-admin --region us-east-1 \
     --query 'Item.{status: status.S, last_active_at: last_active_at.S}'
   ```
   Expected (pre-deploy): `status="provisioning"`.
   Expected (post-deploy, within ~60s of backend start): `status="running"` (the startup reconciler re-kicked the poller; the container was healthy so the first iteration transitioned it).

2. Force a failing provision (bad image). Set the task definition's image to `alpine/openclaw:does-not-exist-v9999` and provision. Expected: within ~30s (2 failed task placements × ~15s each), DDB row flips to `status="error"` and the poller exits. CloudWatch logs show `"Deployment circuit breaker tripped"`.

### Prod smoke (read-only, post-deploy)

1. Check prod DDB for the stuck `user_3CNDd8aX7xssuRvFFLz5ufXzsZl` row — should transition to `status="running"` on first backend restart after deploy.
2. Check prod `gateway.idle.scale_to_zero` metric — should eventually fire for the free orphan once it transitions (the reaper only sees `status="running"` containers; this fix unblocks it).
3. `aws ecs list-services --cluster isol8-prod-container-ClusterEB0386A7-SUcNtlaTmUuw` — the orphan and free containers should eventually (within 5 min of transition + reaper cycle) have `desiredCount=0`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-resilient-provisioning-state-machine.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
