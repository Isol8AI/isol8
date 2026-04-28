"""Unit tests for the paperclip_proxy router (HTTP path).

T14 covers the *unit-testable* surface of the proxy:

* brand-rewrite — pattern correctness + idempotence + non-HTML
  passthrough.
* circuit-breaker — opens above threshold, stays closed below, holds
  open for the cool-down once tripped.
* Set-Cookie domain rewrite — preserves other attributes, adds
  ``Domain=`` if missing, replaces existing value, case-insensitive.
* request-header filtering — drops hop-by-hop + the auth/cookie that
  the client cannot trust to forward.

Full integration tests (FastAPI TestClient + mocked admin client +
mocked PaperclipRepo) are deferred to T18-T20's docker-compose suite,
where the upstream Paperclip server is real and the network path
mirrors production. Mocking the entire request flow at unit level
would mostly verify mocks against mocks.
"""

from __future__ import annotations

import time

import httpx
import pytest

from routers.paperclip_proxy import (
    _BRAND_REWRITES,
    _FAILURE_THRESHOLD_PCT,
    _FAILURE_WINDOW_SECONDS,
    _MIN_REQUESTS_FOR_OPEN,
    _OPEN_STATE_SECONDS,
    _brand_rewrite_html,
    _circuit_open,
    _filter_request_headers,
    _filter_response_headers,
    _record_outcome,
    _recent_5xx,
    _recent_total,
    _rewrite_set_cookie_domain,
)


# ---------------------------------------------------------------
# Brand-rewrite
# ---------------------------------------------------------------


def test_brand_rewrite_replaces_title():
    out = _brand_rewrite_html(b"<html><head><title>Paperclip</title></head></html>")
    assert b"<title>Isol8 Teams</title>" in out
    assert b"<title>Paperclip</title>" not in out


def test_brand_rewrite_replaces_title_case_insensitive():
    out = _brand_rewrite_html(b"<TITLE>PaperClip</TITLE>")
    # Case-insensitive flag should match the tag name regardless of
    # case; replacement is the canonical lowercase form.
    assert b"<title>Isol8 Teams</title>" in out


def test_brand_rewrite_replaces_og_site_name_double_quotes():
    src = b'<meta property="og:site_name" content="Paperclip">'
    out = _brand_rewrite_html(src)
    assert b'content="Isol8"' in out


def test_brand_rewrite_replaces_og_site_name_single_quotes():
    src = b"<meta property='og:site_name' content='Paperclip'>"
    out = _brand_rewrite_html(src)
    assert b"content='Isol8'" in out


def test_brand_rewrite_passes_non_html_unchanged():
    src = b'{"data":"Paperclip"}'
    # JSON happens to contain the brand string, but the patterns are
    # anchored on HTML markup so they don't match — exact passthrough.
    out = _brand_rewrite_html(src)
    assert out == src


def test_brand_rewrite_idempotent():
    src = b"<title>Paperclip</title>"
    once = _brand_rewrite_html(src)
    twice = _brand_rewrite_html(once)
    assert once == twice


def test_brand_rewrite_handles_empty_body():
    assert _brand_rewrite_html(b"") == b""


def test_brand_rewrite_patterns_are_compiled_with_ignorecase():
    # Sanity: the module-level patterns were compiled with the
    # IGNORECASE flag so admin tooling that hand-edits HTML doesn't
    # break the rewrite by varying tag case.
    import re as _re

    for pattern, _ in _BRAND_REWRITES:
        assert pattern.flags & _re.IGNORECASE


# ---------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_breaker_state():
    """Each test gets a clean breaker.

    The module-level ``_recent_*`` deques + ``_circuit_open_until``
    are process-global, so without this every test would inherit the
    counts of the previous one and order would matter.
    """
    import routers.paperclip_proxy as proxy_mod

    _recent_5xx.clear()
    _recent_total.clear()
    proxy_mod._circuit_open_until = 0.0
    yield
    _recent_5xx.clear()
    _recent_total.clear()
    proxy_mod._circuit_open_until = 0.0


def test_circuit_breaker_opens_above_threshold():
    # 7 5xx + 3 200 = 70% failure rate over 10 samples → must open.
    for _ in range(7):
        _record_outcome(503)
    for _ in range(3):
        _record_outcome(200)
    assert _circuit_open() is True


def test_circuit_breaker_stays_closed_below_threshold():
    # 2 5xx + 8 200 = 20% — well below the 50% threshold.
    for _ in range(2):
        _record_outcome(503)
    for _ in range(8):
        _record_outcome(200)
    assert _circuit_open() is False


def test_circuit_breaker_stays_closed_below_min_requests():
    # 100% 5xx but only 5 samples — below the 10-sample minimum,
    # so we don't flap the breaker on a tiny burst.
    for _ in range(5):
        _record_outcome(503)
    assert _circuit_open() is False


def test_circuit_breaker_holds_open_during_cooldown(monkeypatch):
    # Trip the breaker, then assert it stays open even if a single
    # later success would otherwise drop the rate. (Real production
    # traffic during the cool-down is small but nonzero — we don't
    # want to flap.)
    for _ in range(10):
        _record_outcome(503)
    assert _circuit_open() is True

    _record_outcome(200)
    _record_outcome(200)
    assert _circuit_open() is True


def test_circuit_breaker_reopens_path_constants_make_sense():
    # Light defensive check on the constants — tests serve as
    # documentation if anyone changes them.
    assert 0 < _FAILURE_THRESHOLD_PCT <= 1
    assert _FAILURE_WINDOW_SECONDS > 0
    assert _OPEN_STATE_SECONDS > 0
    assert _MIN_REQUESTS_FOR_OPEN >= 1


def test_circuit_breaker_recloses_after_cooldown_window(monkeypatch):
    # Trip the breaker.
    for _ in range(10):
        _record_outcome(503)
    assert _circuit_open() is True

    # Fast-forward time past the cool-down. We monkey-patch
    # ``time.time`` inside the proxy module so the cool-down + the
    # rate-window cutoff both shift.
    import routers.paperclip_proxy as proxy_mod

    fake_now = time.time() + _OPEN_STATE_SECONDS + _FAILURE_WINDOW_SECONDS + 1
    monkeypatch.setattr(proxy_mod.time, "time", lambda: fake_now)

    # All the recorded 5xx samples are now older than the window,
    # so the rate calc returns 0/0 and we skip re-opening.
    assert _circuit_open() is False


# ---------------------------------------------------------------
# Set-Cookie domain rewrite
# ---------------------------------------------------------------


def test_rewrite_set_cookie_replaces_existing_domain():
    src = "session=abc; Path=/; Domain=paperclip.internal; HttpOnly; Secure"
    out = _rewrite_set_cookie_domain(src)
    assert "Domain=.isol8.co" in out
    assert "paperclip.internal" not in out
    # Other attributes preserved.
    assert "Path=/" in out
    assert "HttpOnly" in out
    assert "Secure" in out


def test_rewrite_set_cookie_appends_domain_if_missing():
    src = "session=abc; Path=/; HttpOnly; Secure"
    out = _rewrite_set_cookie_domain(src)
    assert out.endswith("; Domain=.isol8.co")
    # Original attributes are not mutated when appending.
    assert "Path=/" in out
    assert "HttpOnly" in out
    assert "Secure" in out


def test_rewrite_set_cookie_case_insensitive():
    src = "session=abc; domain=other.example; Secure"
    out = _rewrite_set_cookie_domain(src)
    # Existing lowercase ``domain=`` is matched and rewritten — only
    # one occurrence, no duplicate. We preserve the upstream's
    # original attribute-name casing (``\1`` in the regex) since
    # cookies are case-insensitive per RFC 6265 §5.2; browsers honor
    # either form.
    assert out.lower().count("domain=") == 1
    assert ".isol8.co" in out
    assert "other.example" not in out
    # Original case preserved on the attribute name.
    assert "domain=.isol8.co" in out


def test_rewrite_set_cookie_preserves_samesite():
    src = "tok=v; Path=/; SameSite=Lax; HttpOnly"
    out = _rewrite_set_cookie_domain(src)
    assert "SameSite=Lax" in out
    assert "; Domain=.isol8.co" in out


def test_rewrite_set_cookie_custom_target_domain():
    src = "tok=v; Domain=foo"
    out = _rewrite_set_cookie_domain(src, target_domain=".example.com")
    assert "Domain=.example.com" in out
    assert "foo" not in out


# ---------------------------------------------------------------
# Request / response header filtering
# ---------------------------------------------------------------


class _FakeRequest:
    """Minimal stand-in for starlette.Request that exposes ``.headers``.

    The real Request has loads of state (scope, body, query, etc.)
    but ``_filter_request_headers`` only touches ``headers``, so a
    bare object with a dict-of-dicts is enough for the unit assertion.
    """

    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_filter_request_headers_drops_hop_by_hop():
    req = _FakeRequest(
        headers={
            "Host": "company.isol8.co",
            "Connection": "keep-alive",
            "Authorization": "Bearer clerk-token",
            "Cookie": "__session=abc",
            "User-Agent": "test/1.0",
            "Transfer-Encoding": "chunked",
            "X-Forwarded-Host": "company.isol8.co",
        }
    )
    out = _filter_request_headers(req)
    # Stripped:
    assert "Host" not in out and "host" not in out
    assert "Connection" not in out
    assert "Authorization" not in out
    assert "Cookie" not in out
    assert "Transfer-Encoding" not in out
    # Kept:
    assert out.get("User-Agent") == "test/1.0"
    assert out.get("X-Forwarded-Host") == "company.isol8.co"


def test_filter_response_headers_drops_set_cookie_and_content_length():
    # We strip Set-Cookie at this layer because it's re-attached
    # separately after Domain= rewriting; double-attaching would
    # produce two cookies on the wire.
    headers = httpx.Headers(
        [
            ("content-length", "123"),
            ("set-cookie", "session=abc"),
            ("transfer-encoding", "chunked"),
            ("content-type", "text/html"),
        ]
    )
    out = _filter_response_headers(headers)
    assert "content-length" not in {k.lower() for k in out}
    assert "set-cookie" not in {k.lower() for k in out}
    assert "transfer-encoding" not in {k.lower() for k in out}
    assert out.get("content-type") == "text/html"
