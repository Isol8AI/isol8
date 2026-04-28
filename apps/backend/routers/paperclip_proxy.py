"""Reverse proxy for ``company.isol8.co`` → internal Paperclip server.

Validates the Clerk session, signs the user in to Paperclip via Better
Auth (using the per-user random password we encrypted at provisioning
time), forwards the HTTP request to the internal Paperclip server with
the resulting session token, streams the response back, and rewrites
HTML brand strings on the way out. A simple sliding-window circuit
breaker opens for 60s if the upstream 5xx rate crosses 50% in any 30s
window.

This module owns the *router* only. The host-conditional dispatch lives
in T16's middleware in ``main.py``: when an incoming request carries
``X-Forwarded-Host: company.isol8.co`` (or the env-specific equivalent)
the middleware mounts this router on the request path; for any other
host the middleware passes through to the normal Isol8 routers.

**Why ``X-Forwarded-Host`` and not ``Host`` / ``request.url.hostname``?**
API Gateway HTTP API rewrites the upstream ``Host`` header to the
integration target's DNS name (the ALB), so by the time FastAPI sees
the request the original ``company.isol8.co`` is gone from ``Host``.
T6+T7 added a parameter mapping in ``api-stack.ts`` that copies
``$context.domainName`` into ``X-Forwarded-Host`` so the original
hostname survives the integration hop. Starlette's
``request.url.hostname`` reads from the ASGI scope's reconstructed URL
and reflects the rewritten ``Host``, so it would point at the ALB DNS
— useless for dispatch. Reading the header directly is the supported
path.

**Auth model (v1, no session caching).**
Every proxied request signs the user in to Paperclip from scratch:

1. Validate the Clerk JWT (standard ``get_current_user`` dep).
2. Look up the user's ``PaperclipCompany`` row, decrypt the stored
   password.
3. Call ``admin_client.sign_in_user(email, password)`` to get a
   fresh Better Auth session token. Better Auth verifies the password
   with bcrypt server-side; the call is dominated by network RTT
   (single-digit ms inside the VPC) — no session cache needed for v1.
4. Forward the request to Paperclip with
   ``Authorization: Bearer <session_token>``. Better Auth accepts the
   session token in either a cookie or the bearer header.
5. Forward the upstream's ``Set-Cookie`` to the browser, scoped to
   ``.isol8.co`` so subsequent in-page AJAX requests carry it on
   their own. (Useful for Paperclip's own client-side fetches that
   address ``company.isol8.co`` directly without going through us
   adding the bearer.)
6. If the response is HTML, rewrite the visible brand strings
   (``<title>Paperclip</title>``, ``og:site_name``).

V2 should cache session tokens (Redis or in-memory with short TTL) and
reuse a long-lived ``httpx.AsyncClient`` so we amortize the connection
pool. T14 keeps it boring: per-request ``AsyncClient`` is only ~1ms
overhead inside the VPC and lets us defer the lifecycle/cleanup
question.

**Circuit breaker.** A small sliding-window counter (30s window, 50%
5xx threshold, 10-request minimum) opens for 60s when the upstream is
clearly degraded. While open, every proxied request returns an HTML
"Teams temporarily unavailable" page in 503 — failing fast prevents us
piling load onto a hurting backend. The counter is in-process and
process-local; that's fine for v1 with a single backend task. Multi-
task fleets get independent counters which is the conservative
(slightly less coordinated) behavior — they all break and heal
independently rather than relying on any shared state.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from websockets import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from core.auth import AuthContext, _decode_token, _extract_org_claims, get_current_user
from core.config import settings
from core.encryption import decrypt
from core.repositories.paperclip_repo import PaperclipRepo
from core.services.paperclip_admin_client import PaperclipAdminClient, PaperclipApiError

logger = logging.getLogger(__name__)
router = APIRouter()

# RFC 7230 §6.1 hop-by-hop headers — these never propagate across a proxy.
# We strip them on both directions: from the inbound request before
# forwarding upstream, and from the upstream response before returning
# to the browser. ``Host`` is also dropped (we want httpx to set its
# own based on the upstream base_url), and ``Authorization`` and
# ``Cookie`` are dropped so the browser's Clerk credentials never leak
# to Paperclip — we inject our own server-issued bearer token instead.
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Brand-rewrite patterns. Run only on responses with
# ``Content-Type: text/html``. Failure of any rewrite is logged and
# falls through to the original body — never break the page just to
# tweak the title.
_BRAND_REWRITES: tuple[tuple[re.Pattern[bytes], bytes], ...] = (
    (
        re.compile(rb"<title>Paperclip</title>", re.IGNORECASE),
        b"<title>Isol8 Teams</title>",
    ),
    (
        re.compile(
            rb'(<meta[^>]*property=["\']og:site_name["\'][^>]*content=["\'])Paperclip',
            re.IGNORECASE,
        ),
        rb"\1Isol8",
    ),
)

# --- Circuit breaker (per spec §6) ---
# Sliding window: any 5xx response from the upstream contributes to a
# 30s rolling failure-rate calculation. Once we have at least
# _MIN_REQUESTS_FOR_OPEN samples in the window AND the 5xx fraction
# crosses _FAILURE_THRESHOLD_PCT, the breaker opens for
# _OPEN_STATE_SECONDS. While open, ``_circuit_open()`` short-circuits
# ``True`` without re-checking the rate — so even if a few requests
# slip through and succeed, we hold open for the full cool-down.
_FAILURE_WINDOW_SECONDS = 30.0
_FAILURE_THRESHOLD_PCT = 0.5
_OPEN_STATE_SECONDS = 60.0
_MIN_REQUESTS_FOR_OPEN = 10

# Bounded deques: 200 samples easily covers the 30s window even at
# 5+ rps and bounds memory. Older entries are auto-evicted by
# ``maxlen``; we additionally filter by timestamp inside
# ``_circuit_open`` so the math reflects the real window, not the
# deque size.
_recent_5xx: deque[float] = deque(maxlen=200)
_recent_total: deque[float] = deque(maxlen=200)
_circuit_open_until: float = 0.0


def _record_outcome(status_code: int) -> None:
    """Log a request outcome into the circuit breaker's sample windows."""
    now = time.time()
    _recent_total.append(now)
    if status_code >= 500:
        _recent_5xx.append(now)


def _circuit_open() -> bool:
    """Return True if the breaker is currently open (or should be opened now).

    Side effect: when the failure threshold is crossed for the first
    time we set ``_circuit_open_until`` so subsequent calls in the
    same cool-down period short-circuit without recomputing the rate.
    """
    global _circuit_open_until
    now = time.time()
    if now < _circuit_open_until:
        return True
    cutoff = now - _FAILURE_WINDOW_SECONDS
    fives = sum(1 for t in _recent_5xx if t >= cutoff)
    total = sum(1 for t in _recent_total if t >= cutoff)
    if total >= _MIN_REQUESTS_FOR_OPEN and (fives / total) >= _FAILURE_THRESHOLD_PCT:
        _circuit_open_until = now + _OPEN_STATE_SECONDS
        logger.warning(
            "paperclip_proxy: circuit breaker OPEN (5xx=%d/%d in last %.0fs)",
            fives,
            total,
            _FAILURE_WINDOW_SECONDS,
        )
        return True
    return False


def _circuit_breaker_response() -> Response:
    return Response(
        content=(
            b"<!doctype html><html><body>"
            b"<h1>Teams temporarily unavailable</h1>"
            b"<p>Try again in a minute.</p>"
            b"</body></html>"
        ),
        status_code=503,
        media_type="text/html",
    )


def _provisioning_response() -> Response:
    """Returned when the user has no Paperclip company yet (or it's not active)."""
    return Response(
        content=(
            b"<!doctype html><html><body>"
            b"<h1>Your team workspace is being set up</h1>"
            b"<p>Refresh in a moment.</p>"
            b"</body></html>"
        ),
        status_code=503,
        media_type="text/html",
    )


def _filter_request_headers(req: Request) -> dict[str, str]:
    """Strip hop-by-hop + auth headers from the inbound request.

    Authorization and Cookie are stripped so the browser's Clerk
    credentials don't leak to Paperclip — we inject our own
    server-issued Better Auth bearer instead. Host is stripped so
    httpx sets it based on the upstream base_url.
    """
    out: dict[str, str] = {}
    for name, value in req.headers.items():
        lower = name.lower()
        if lower in _HOP_BY_HOP_HEADERS or lower in {"host", "authorization", "cookie", "content-length"}:
            continue
        out[name] = value
    return out


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    """Strip hop-by-hop headers from the upstream response.

    ``Content-Length`` is also dropped because the brand-rewrite step
    can change body length. FastAPI/Starlette will recompute it from
    the new body when the Response is serialized. ``Set-Cookie`` is
    handled separately (we may rewrite the Domain= attribute) and
    re-attached by the caller, so we drop it here to avoid duplicates.
    """
    out: dict[str, str] = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower in _HOP_BY_HOP_HEADERS or lower in {"content-length", "set-cookie"}:
            continue
        out[name] = value
    return out


def _brand_rewrite_html(body: bytes) -> bytes:
    """Replace Paperclip brand strings with Isol8 equivalents in HTML bytes.

    Only safe for ``text/html`` bodies — the patterns are anchored on
    HTML markup. Idempotent: the rewritten output never matches the
    original patterns again, so re-running the function is a no-op.
    """
    out = body
    for pattern, replacement in _BRAND_REWRITES:
        out = pattern.sub(replacement, out)
    return out


def _rewrite_set_cookie_domain(set_cookie: str, target_domain: str = ".isol8.co") -> str:
    """Force the Domain attribute on a Set-Cookie header to ``target_domain``.

    Goal: the cookie should be sent by the browser on subsequent
    requests to any ``*.isol8.co`` subdomain (chat.isol8.co,
    company.isol8.co, etc.) so Paperclip's in-page AJAX that
    addresses ``company.isol8.co`` directly carries the session
    without going through our bearer-injection path.

    Strategy:
      * If a ``Domain=`` attribute already exists, replace its value
        with ``target_domain``.
      * Otherwise append ``; Domain=<target_domain>``.

    We deliberately keep ``HttpOnly``, ``Secure``, ``SameSite``, and
    ``Path`` exactly as the upstream set them. The regex is
    case-insensitive on the attribute name (cookies are
    case-insensitive per RFC 6265 §5.2). Single-cookie input is
    expected — httpx stores multi-Set-Cookie responses as a list of
    headers we iterate separately at the call site.

    Edge case: a cookie with ``Domain=`` whose value contains a
    semicolon would confuse the simple regex, but real-world Domain
    values are restricted to host names per RFC 6265 §4.1.2.3, so
    the simple pattern is safe.
    """
    if re.search(r"(?i)domain=", set_cookie):
        return re.sub(
            r"(?i)(Domain=)[^;]+",
            r"\1" + target_domain,
            set_cookie,
            count=1,
        )
    return f"{set_cookie}; Domain={target_domain}"


# --- Routes ---


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy(
    path: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> Response:
    """Forward ``request`` to the internal Paperclip server.

    Returns the Paperclip response (HTML brand-rewritten if applicable),
    a 503 stub if the circuit breaker is open or the user's company
    isn't provisioned yet, or a 502 if the upstream request itself
    fails (DNS, connection refused, etc.).
    """
    if _circuit_open():
        return _circuit_breaker_response()

    # ---- Look up the user's Paperclip company row ----
    repo = PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")
    company = await repo.get(auth.user_id)
    if company is None or company.status != "active":
        return _provisioning_response()

    # Email comes from the Clerk JWT (``email`` claim). The Isol8
    # ``users`` DynamoDB row only stores ``user_id`` + ``created_at``
    # — there is no email column to fall back on, so if the JWT lacks
    # the claim we cannot sign the user in.
    email = (auth.email or "").strip()
    if not email:
        logger.warning(
            "paperclip_proxy: user %s has no email claim on JWT; cannot sign in to Paperclip",
            auth.user_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Email claim missing from auth token",
        )

    try:
        password = decrypt(company.paperclip_password_encrypted)
    except ValueError as e:
        # Encryption key rotated, or row was written under a different
        # key. The user needs to be reprovisioned — surface a clear 500
        # rather than a confusing upstream auth failure.
        logger.error(
            "paperclip_proxy: failed to decrypt password for user %s: %s",
            auth.user_id,
            e,
        )
        raise HTTPException(status_code=500, detail="Could not decrypt session credentials")

    # ---- Sign in to Paperclip + forward the request ----
    # Per-request httpx.AsyncClient: simple lifecycle, no shared-state
    # gotchas. Cloud Map A-record TTL is 10s so DNS is re-resolved
    # often enough; v2 should hoist this into a long-lived shared
    # client to amortize TLS + connection-pool setup.
    async with httpx.AsyncClient(
        base_url=settings.PAPERCLIP_INTERNAL_URL,
        timeout=30.0,
    ) as client:
        admin = PaperclipAdminClient(http_client=client, admin_token=settings.PAPERCLIP_ADMIN_TOKEN)
        try:
            signin = await admin.sign_in_user(email=email, password=password)
        except PaperclipApiError as e:
            logger.exception(
                "paperclip_proxy: sign_in failed for user=%s status=%s body=%s",
                auth.user_id,
                e.status_code,
                e.body,
            )
            _record_outcome(e.status_code)
            raise HTTPException(status_code=502, detail="Could not authenticate to Paperclip")

        session_token = signin.get("token") or ""
        if not session_token:
            logger.error(
                "paperclip_proxy: Better Auth response had no token for user %s",
                auth.user_id,
            )
            raise HTTPException(status_code=502, detail="Paperclip auth response malformed")

        # Build forwarding headers. We add X-Forwarded-* so Paperclip's
        # access logs reflect the real client identity (not the ALB
        # IP). The original X-Forwarded-Host is preserved if present
        # so Paperclip can render absolute URLs that point back at
        # company.isol8.co rather than the ALB.
        forwarded_host = request.headers.get(
            "x-forwarded-host",
            request.headers.get("host", ""),
        )
        client_host = request.client.host if request.client else ""
        upstream_headers: dict[str, str] = {
            **_filter_request_headers(request),
            "Authorization": f"Bearer {session_token}",
            "X-Forwarded-Host": forwarded_host,
            "X-Forwarded-Proto": "https",
        }
        if client_host:
            upstream_headers["X-Forwarded-For"] = client_host

        # httpx accepts a leading ``/`` in the path even when base_url
        # already has a trailing ``/`` — it normalizes correctly.
        upstream_url = f"/{path}"
        body_bytes = await request.body()
        try:
            upstream = await client.request(
                method=request.method,
                url=upstream_url,
                params=request.query_params,
                content=body_bytes,
                headers=upstream_headers,
            )
        except httpx.HTTPError as e:
            logger.exception(
                "paperclip_proxy: upstream request failed user=%s method=%s path=%s: %s",
                auth.user_id,
                request.method,
                path,
                e,
            )
            _record_outcome(502)
            return Response(
                content=b"Bad gateway",
                status_code=502,
                media_type="text/plain",
            )

    _record_outcome(upstream.status_code)

    # ---- Build the response back to the browser ----
    response_body = upstream.content
    content_type = upstream.headers.get("content-type", "")
    if "text/html" in content_type and response_body:
        try:
            response_body = _brand_rewrite_html(response_body)
        except Exception as e:  # noqa: BLE001 - never break the page
            logger.warning(
                "paperclip_proxy: brand-rewrite raised (passing through): %s",
                e,
            )

    response_headers = _filter_response_headers(upstream.headers)

    # Re-attach Set-Cookie (potentially many) with rewritten Domain.
    # httpx preserves the original ordering of repeated headers via
    # ``get_list``; we round-trip each through the rewriter and
    # carry them across as a list. FastAPI's ``Response`` accepts a
    # mapping so we serialize multiple Set-Cookie via raw mutation
    # of ``response.headers`` after construction.
    set_cookies = upstream.headers.get_list("set-cookie") if hasattr(upstream.headers, "get_list") else []
    if not set_cookies:
        # httpx.Headers may not expose get_list in some versions; fall
        # back to the single-value accessor so we degrade gracefully.
        single = upstream.headers.get("set-cookie")
        if single:
            set_cookies = [single]

    rewritten_cookies = [_rewrite_set_cookie_domain(sc) for sc in set_cookies]

    response = Response(
        content=response_body,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=content_type or None,
    )
    for cookie in rewritten_cookies:
        # raw_headers append preserves multi-Set-Cookie semantics —
        # ``response.headers["set-cookie"] = ...`` would only retain
        # the last value.
        response.raw_headers.append((b"set-cookie", cookie.encode("latin-1")))

    return response


# ---------------------------------------------------------------------------
# WebSocket relay — paired upstream WS for Paperclip live-events
# ---------------------------------------------------------------------------
#
# Why a separate route from the HTTP one?
#
# 1. **Auth source.** Browser-issued WebSocket upgrades cannot carry an
#    ``Authorization: Bearer`` header (the WebSocket JS API has no hook
#    for it), so the only credential we get is the Clerk session cookie
#    that already rides along on cross-origin requests to ``*.isol8.co``.
#    That means we can't use ``Depends(get_current_user)`` here — we
#    have to read ``websocket.cookies`` and validate the JWT manually
#    via ``_decode_token``.
# 2. **Different transport.** httpx can't proxy a WebSocket upgrade,
#    and FastAPI dispatches WS upgrades to ``@router.websocket(...)``
#    routes, not ``@router.api_route(...)`` ones. Both can register the
#    same ``{path:path}`` because Starlette's matcher checks the
#    ``websocket.scope["type"]`` and routes accordingly.
#
# Auth flow (mirrors the HTTP path's sign-in):
#   1. Read ``__session`` cookie (Clerk's default JWT cookie name).
#   2. Decode + validate with ``_decode_token`` → extract ``sub`` + ``email``.
#   3. Look up the user's PaperclipCompany row, decrypt the password.
#   4. Sign in to Paperclip (Better Auth) → session token.
#   5. Open paired upstream WS with ``Authorization: Bearer <token>``.
#   6. asyncio.gather two relay coroutines (browser→upstream and
#      upstream→browser) until either side closes.
#
# Close codes follow RFC 6455 + the "private application" range
# (4000-4999): 4401 unauthenticated, 4400 missing email claim, 4502
# Paperclip auth failed, 4503 not provisioned. They're informational
# only — the browser usually just sees an immediate close — but they
# make CloudWatch traces readable.

# Clerk's default cookie name. Verified against ``core/auth.py``: the
# HTTP path uses Bearer (HTTPAuthorizationCredentials) so there's no
# direct cookie reference in the codebase, but Clerk's documented
# session-cookie name across their JS SDKs is ``__session``. If a future
# Clerk upgrade renames it we centralize the constant here.
_CLERK_SESSION_COOKIE = "__session"

# Max WebSocket frame size we accept from either side. 10 MB matches
# Paperclip's own server limit; bigger frames are almost certainly a
# bug or abuse, so we let the websockets library reject them upstream
# of the relay loop.
_WS_MAX_FRAME_SIZE = 10 * 1024 * 1024


@router.websocket("/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str) -> None:
    """Bidirectional WebSocket relay for Paperclip live-events.

    Auth via Clerk session cookie on the upgrade frame (browsers cannot
    attach an Authorization header to a JS-initiated WebSocket open, so
    cookie auth is the only viable channel). Same DB lookup + Better
    Auth sign-in dance as the HTTP path; differs in that the upstream
    leg is also a WebSocket and we relay frames bidirectionally instead
    of round-tripping a single request/response.
    """
    # ---- Step 1: Extract + validate Clerk session cookie ----
    clerk_token = websocket.cookies.get(_CLERK_SESSION_COOKIE)
    if not clerk_token:
        await websocket.close(code=4401, reason="Missing Clerk session cookie")
        return

    try:
        payload = await _decode_token(clerk_token)
    except Exception as e:  # noqa: BLE001 - opaque to caller; we close.
        logger.warning("paperclip_proxy_ws: invalid Clerk token: %s", e)
        await websocket.close(code=4401, reason="Invalid Clerk token")
        return

    user_id = payload.get("sub")
    email = (payload.get("email") or "").strip()
    if not user_id:
        await websocket.close(code=4401, reason="Token missing subject")
        return
    if not email:
        # Same constraint as the HTTP path — Better Auth needs email +
        # password to sign the user in, and the Isol8 ``users`` row has
        # no email column to fall back on.
        logger.warning(
            "paperclip_proxy_ws: user %s has no email claim on JWT; cannot sign in",
            user_id,
        )
        await websocket.close(code=4400, reason="Email claim missing")
        return

    # Resolve the owner the same way ``resolve_owner_id`` does for the
    # HTTP path, so a user in an org context hits their org's row.
    org_claims = _extract_org_claims(payload)
    owner_id = org_claims["org_id"] or user_id

    # ---- Step 2: Look up Paperclip company + decrypt password ----
    repo = PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")
    company = await repo.get(owner_id)
    if company is None or company.status != "active":
        await websocket.close(code=4503, reason="Paperclip not provisioned")
        return

    try:
        password = decrypt(company.paperclip_password_encrypted)
    except ValueError as e:
        logger.error(
            "paperclip_proxy_ws: failed to decrypt password for owner %s: %s",
            owner_id,
            e,
        )
        await websocket.close(code=4500, reason="Credential decrypt failed")
        return

    # ---- Step 3: Sign in to Paperclip via Better Auth ----
    async with httpx.AsyncClient(
        base_url=settings.PAPERCLIP_INTERNAL_URL,
        timeout=15.0,
    ) as client:
        admin = PaperclipAdminClient(
            http_client=client,
            admin_token=settings.PAPERCLIP_ADMIN_TOKEN,
        )
        try:
            signin = await admin.sign_in_user(email=email, password=password)
        except PaperclipApiError as e:
            logger.exception(
                "paperclip_proxy_ws: sign_in failed for owner=%s status=%s body=%s",
                owner_id,
                e.status_code,
                e.body,
            )
            await websocket.close(code=4502, reason="Paperclip auth failed")
            return

        session_token = signin.get("token") or ""
        if not session_token:
            logger.error(
                "paperclip_proxy_ws: Better Auth response had no token for owner %s",
                owner_id,
            )
            await websocket.close(code=4502, reason="Paperclip auth response malformed")
            return

    # ---- Step 4: Open paired upstream WS ----
    # Translate the http(s)://host base URL into ws(s)://host so we
    # connect on the WebSocket transport. Paperclip's live-events
    # endpoint lives under the same host as its HTTP API.
    upstream_base = settings.PAPERCLIP_INTERNAL_URL.replace("https://", "wss://").replace("http://", "ws://")
    # Ensure exactly one slash between base and path. Paperclip is
    # forgiving about double slashes, but a clean URL keeps logs sane.
    upstream_url = f"{upstream_base.rstrip('/')}/{path.lstrip('/')}"

    await websocket.accept()

    try:
        async with ws_connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {session_token}"},
            max_size=_WS_MAX_FRAME_SIZE,
            open_timeout=15,
            close_timeout=5,
        ) as upstream:
            # ---- Step 5: Bidirectional relay ----
            #
            # We use ``asyncio.gather(..., return_exceptions=True)``
            # rather than ``asyncio.wait(FIRST_COMPLETED)`` so that an
            # exception in one leg doesn't tear down the other leg
            # mid-frame — gather collects results, the outer ``finally``
            # closes both sides cleanly.

            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        msg_type = msg.get("type")
                        if msg_type == "websocket.disconnect":
                            return
                        # FastAPI's ``receive()`` returns the raw ASGI
                        # event dict; either ``text`` or ``bytes`` is
                        # populated for a ``websocket.receive`` event.
                        if "text" in msg and msg["text"] is not None:
                            await upstream.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await upstream.send(msg["bytes"])
                except WebSocketDisconnect:
                    return
                except ConnectionClosed:
                    return
                except Exception as e:  # noqa: BLE001 - log + bail
                    logger.warning(
                        "paperclip_proxy_ws: client→upstream relay error owner=%s: %s",
                        owner_id,
                        e,
                    )

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except ConnectionClosed:
                    return
                except WebSocketDisconnect:
                    return
                except Exception as e:  # noqa: BLE001 - log + bail
                    logger.warning(
                        "paperclip_proxy_ws: upstream→client relay error owner=%s: %s",
                        owner_id,
                        e,
                    )

            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
                return_exceptions=True,
            )
    except Exception as e:  # noqa: BLE001 - top-level guard
        logger.exception(
            "paperclip_proxy_ws: connection failed owner=%s path=%s: %s",
            owner_id,
            path,
            e,
        )
    finally:
        # ``websocket.close()`` is idempotent in Starlette — safe to call
        # even if the relay loop already saw a disconnect.
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
