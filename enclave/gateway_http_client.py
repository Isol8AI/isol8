"""
HTTP client for the OpenClaw gateway's OpenAI-compatible endpoint.

Uses stdlib urllib.request (no extra dependencies) to communicate with
the persistent OpenClaw gateway running inside the enclave.

Supports:
  - Streaming (SSE) responses via chat_stream()
  - Non-streaming responses via chat()
  - Per-request agent routing via x-openclaw-agent-id header
  - Per-request session isolation via x-openclaw-session-key header
"""

import json
import socket as _socket
import urllib.request
import urllib.error
from typing import Generator, Optional
from uuid import uuid4


# Default timeout for non-streaming requests
_DEFAULT_TIMEOUT = 90

# Timeout for streaming requests — tool execution (web search, memory search)
# can cause long pauses between SSE events, so this must be generous.
_STREAM_TIMEOUT = 300

# Default timeout for establishing SSE connection
_STREAM_CONNECT_TIMEOUT = 30


class GatewayRequestError(Exception):
    """Raised when the gateway returns an error response."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class GatewayHttpClient:
    """HTTP client for the OpenClaw gateway."""

    def __init__(self, base_url: str = "http://127.0.0.1:18789"):
        self._base_url = base_url.rstrip("/")

    def chat_stream(
        self,
        message: str,
        agent_id: str,
        session_key: Optional[str] = None,
        timeout: int = _STREAM_TIMEOUT,
    ) -> Generator[Optional[str], None, None]:
        """
        Send a message and stream the response via SSE.

        Args:
            message: User message text.
            agent_id: Agent identifier (used as x-openclaw-agent-id header).
            session_key: Session key for conversation continuity.
                         If None, a unique key is generated.
            timeout: Request timeout in seconds.

        Yields:
            Text chunks (str) from the assistant's response, or None as a
            heartbeat sentinel when the SSE stream is silent (e.g. during
            tool execution).

        Raises:
            GatewayRequestError: If the gateway returns an error.
        """
        if session_key is None:
            session_key = f"agent:{agent_id}:enclave:{uuid4().hex[:12]}"

        url = f"{self._base_url}/v1/chat/completions"

        body = json.dumps(
            {
                "model": "openclaw",
                "messages": [{"role": "user", "content": message}],
                "stream": True,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "x-openclaw-agent-id": agent_id,
            "x-openclaw-session-key": session_key,
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                pass
            raise GatewayRequestError(
                f"Gateway returned HTTP {e.code}: {error_body}",
                status_code=e.code,
            )
        except urllib.error.URLError as e:
            raise GatewayRequestError(f"Gateway connection failed: {e.reason}")

        try:
            # Set a short per-read timeout for heartbeat detection.
            # If no SSE data arrives within this window (e.g. during tool
            # execution), we yield a None sentinel so downstream layers
            # can emit keepalive events and prevent socket timeouts.
            _HEARTBEAT_INTERVAL = 15  # seconds
            underlying_sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
            if underlying_sock is not None:
                underlying_sock.settimeout(_HEARTBEAT_INTERVAL)

            # Parse SSE stream using readline() so we can catch per-read timeouts
            buffer = ""
            while True:
                try:
                    raw_line = resp.readline()
                except _socket.timeout:
                    # No data within heartbeat interval — yield sentinel
                    yield None
                    continue

                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace")
                buffer += line

                # SSE events are separated by double newlines
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    event_str = event_str.strip()

                    if not event_str:
                        continue

                    # Extract data lines
                    for event_line in event_str.split("\n"):
                        event_line = event_line.strip()

                        if event_line == "data: [DONE]":
                            return

                        if event_line.startswith("data: "):
                            data_str = event_line[6:]  # Strip "data: " prefix
                            try:
                                data = json.loads(data_str)
                                # Extract text from OpenAI chat completion chunk
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield content

                                    # Check for finish_reason
                                    finish = choices[0].get("finish_reason")
                                    if finish is not None:
                                        return
                            except json.JSONDecodeError:
                                # Skip malformed SSE data
                                continue

            # Process any remaining buffer
            if buffer.strip():
                for event_line in buffer.strip().split("\n"):
                    event_line = event_line.strip()
                    if event_line == "data: [DONE]":
                        return
                    if event_line.startswith("data: "):
                        try:
                            data = json.loads(event_line[6:])
                            choices = data.get("choices", [])
                            if choices:
                                content = choices[0].get("delta", {}).get("content")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        finally:
            resp.close()

    def chat(
        self,
        message: str,
        agent_id: str,
        session_key: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> str:
        """
        Send a message and return the full response (non-streaming).

        Args:
            message: User message text.
            agent_id: Agent identifier.
            session_key: Session key for conversation continuity.
            timeout: Request timeout in seconds.

        Returns:
            The assistant's response text.

        Raises:
            GatewayRequestError: If the gateway returns an error.
        """
        if session_key is None:
            session_key = f"agent:{agent_id}:enclave:{uuid4().hex[:12]}"

        url = f"{self._base_url}/v1/chat/completions"

        body = json.dumps(
            {
                "model": "openclaw",
                "messages": [{"role": "user", "content": message}],
                "stream": False,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "x-openclaw-agent-id": agent_id,
            "x-openclaw-session-key": session_key,
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
                choices = response_data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                pass
            raise GatewayRequestError(
                f"Gateway returned HTTP {e.code}: {error_body}",
                status_code=e.code,
            )
        except urllib.error.URLError as e:
            raise GatewayRequestError(f"Gateway connection failed: {e.reason}")
