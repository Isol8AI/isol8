"""
Enclave package for secure message processing.

This package provides enclave implementations:
- MockEnclave: In-process for development (ENCLAVE_MODE=mock)
- NitroEnclaveClient: Real Nitro Enclave via vsock (ENCLAVE_MODE=nitro)
"""

import asyncio
import logging
import subprocess
import json
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class HkdfContext(str, Enum):
    """
    HKDF context strings for domain separation.

    These context strings MUST match between encryption and decryption.
    They ensure that keys derived for different purposes cannot be
    confused or misused.
    """

    # Transport contexts (ephemeral per-request)
    CLIENT_TO_ENCLAVE = "client-to-enclave-transport"
    ENCLAVE_TO_CLIENT = "enclave-to-client-transport"

    # Storage contexts (long-term storage encryption)
    USER_MESSAGE_STORAGE = "user-message-storage"
    ASSISTANT_MESSAGE_STORAGE = "assistant-message-storage"

    # Agent state storage context
    AGENT_STATE_STORAGE = "agent-state-storage"

    # Key distribution contexts
    ORG_KEY_DISTRIBUTION = "org-key-distribution"
    RECOVERY_KEY_ENCRYPTION = "recovery-key-encryption"


# Import shared types
from .enclave_types import (
    EnclaveInterface,
    ProcessedMessage,
    StreamChunk,
    AgentStreamChunk,
    EnclaveInfo,
    DecryptedMessage,
    AgentRunResponse,
)

# Singleton instance
_enclave_instance: Optional[EnclaveInterface] = None


def _discover_enclave_cid() -> int:
    """Discover running enclave's CID using nitro-cli."""
    try:
        result = subprocess.run(
            ["nitro-cli", "describe-enclaves"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        enclaves = json.loads(result.stdout)
        if enclaves and len(enclaves) > 0:
            cid = enclaves[0].get("EnclaveCID")
            if cid:
                logger.info(f"Discovered enclave CID: {cid}")
                return cid
    except FileNotFoundError:
        logger.warning("nitro-cli not found - not running on Nitro-enabled instance")
    except subprocess.TimeoutExpired:
        logger.warning("nitro-cli timed out")
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse nitro-cli output: {e}")
    except Exception as e:
        logger.warning(f"Could not discover enclave CID: {e}")

    raise RuntimeError(
        "No running enclave found. "
        "Start enclave with: sudo nitro-cli run-enclave --eif-path /path/to/enclave.eif --cpu-count 2 --memory 512"
    )


def get_enclave() -> EnclaveInterface:
    """
    Get the enclave instance (NitroEnclaveClient only).

    Returns:
        NitroEnclaveClient instance
    """
    global _enclave_instance

    if _enclave_instance is None:
        from core.config import settings
        from .nitro_enclave_client import NitroEnclaveClient

        # Always auto-discover CID (ignore hardcoded .env values)
        try:
            cid = _discover_enclave_cid()
        except RuntimeError:
            # Fall back to configured CID if discovery fails (e.g. nitro-cli not found)
            cid = settings.ENCLAVE_CID
            if cid == 0:
                raise

        _enclave_instance = NitroEnclaveClient(
            enclave_cid=cid,
            enclave_port=settings.ENCLAVE_PORT,
        )
        logger.info(f"Using NitroEnclaveClient (CID={cid}, port={settings.ENCLAVE_PORT})")

    return _enclave_instance


def reset_enclave() -> None:
    """
    Reset the enclave singleton (for testing only).

    This forces a new instance to be created on next get_enclave() call.
    """
    global _enclave_instance
    _enclave_instance = None


async def startup_enclave() -> None:
    """
    Initialize enclave on application startup.

    Retries up to 5 times with 10s delays if the enclave isn't reachable
    (e.g. enclave still booting after a restart). For NitroEnclaveClient,
    starts the credential refresh background task.
    """
    from core.config import settings

    max_attempts = 5
    enclave = None
    for attempt in range(max_attempts):
        try:
            enclave = get_enclave()
            break
        except (RuntimeError, Exception) as e:
            logger.warning(f"Enclave not ready (attempt {attempt + 1}/{max_attempts}): {e}")
            reset_enclave()  # Clear failed singleton
            if attempt < max_attempts - 1:
                await asyncio.sleep(10)

    if enclave is None:
        raise RuntimeError(f"Enclave not available after {max_attempts} attempts")

    if settings.ENCLAVE_MODE == "nitro":
        from .nitro_enclave_client import NitroEnclaveClient

        if isinstance(enclave, NitroEnclaveClient):
            await enclave.start_credential_refresh()
            logger.info("Started enclave credential refresh task")


async def shutdown_enclave() -> None:
    """
    Cleanup enclave on application shutdown.

    For NitroEnclaveClient, stops the credential refresh background task.
    """
    global _enclave_instance

    if _enclave_instance is not None:
        from .nitro_enclave_client import NitroEnclaveClient

        if isinstance(_enclave_instance, NitroEnclaveClient):
            await _enclave_instance.stop_credential_refresh()
            logger.info("Stopped enclave credential refresh task")

    _enclave_instance = None


# Import agent handling classes
from .agent_handler import AgentHandler, AgentMessageRequest, AgentMessageResponse, AgentStreamRequest

__all__ = [
    "HkdfContext",
    "EnclaveInterface",
    "ProcessedMessage",
    "StreamChunk",
    "EnclaveInfo",
    "DecryptedMessage",
    "AgentRunResponse",
    "AgentStreamChunk",
    "get_enclave",
    "reset_enclave",
    "startup_enclave",
    "shutdown_enclave",
    # Agent handling
    "AgentHandler",
    "AgentMessageRequest",
    "AgentMessageResponse",
    "AgentStreamRequest",
]
