"""Pydantic schemas for agent API."""

from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from schemas.encryption import EncryptedPayloadSchema


class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    soul_content: Optional[str] = Field(None, max_length=10000)
    model: str = Field(default="us.anthropic.claude-opus-4-5-20251101-v1:0")
    encryption_mode: Literal["zero_trust", "background"] = Field(
        default="zero_trust",
        description="Encryption mode: zero_trust (user key, default) or background (KMS, opt-in)",
    )


class AgentResponse(BaseModel):
    """Agent details response."""

    agent_name: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    tarball_size_bytes: Optional[int] = None
    encryption_mode: Literal["zero_trust", "background"] = Field(
        default="zero_trust",
        description="Encryption mode for this agent",
    )

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    """List of agents response."""

    agents: List[AgentResponse]


class SendAgentMessageRequest(BaseModel):
    """Request to send a message to an agent."""

    encrypted_message: EncryptedPayloadSchema
    model: str = Field(default="us.anthropic.claude-opus-4-5-20251101-v1:0")
    # For zero_trust mode: client decrypts state, re-encrypts to enclave transport key
    encrypted_state: Optional[EncryptedPayloadSchema] = Field(
        default=None,
        description="Agent state encrypted to enclave transport key (zero_trust mode only)",
    )


class AgentMessageResponse(BaseModel):
    """Response from agent message."""

    success: bool
    encrypted_response: Optional[EncryptedPayloadSchema] = None
    error: Optional[str] = None


class AgentChatWSRequest(BaseModel):
    """WebSocket request for streaming agent chat."""

    agent_name: str = Field(..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    encrypted_message: EncryptedPayloadSchema
    client_transport_public_key: str
    user_public_key: str = Field(..., description="User's long-term public key for state encryption (zero_trust mode)")
    # Optional: encrypted soul/personality content for first message (new agent)
    # Encrypted to enclave's public key so server cannot read it
    encrypted_soul_content: Optional[EncryptedPayloadSchema] = None
    # For zero_trust mode: client provides decrypted state re-encrypted to enclave
    # Can be sent inline (small states) or via state_ref (large states that exceed
    # API Gateway's 32KB WebSocket frame limit)
    encrypted_state: Optional[EncryptedPayloadSchema] = Field(
        default=None,
        description="Agent state encrypted to enclave transport key (zero_trust mode only)",
    )
    state_ref: Optional[str] = Field(
        default=None,
        description="Reference UUID for state uploaded via REST (used when state exceeds WebSocket frame limit)",
    )


class UploadStateRequest(BaseModel):
    """Request to upload re-encrypted agent state for zero_trust mode."""

    encrypted_state: EncryptedPayloadSchema


class UploadStateResponse(BaseModel):
    """Response with reference UUID for uploaded state."""

    state_ref: str


class UpdateAgentStateRequest(BaseModel):
    """Request to update agent encrypted state (e.g. after editing SOUL.md)."""

    encrypted_state: EncryptedPayloadSchema


class AgentStateResponse(BaseModel):
    """Response from GET /agents/{agent_name}/state."""

    agent_name: str = Field(..., description="Agent name")
    encryption_mode: str = Field(..., description="'zero_trust' or 'background'")
    has_state: bool = Field(..., description="Whether agent has saved state")
    encrypted_tarball: Optional[str] = Field(None, description="JSON-serialized encrypted state (hex)")


class ExtractAgentFilesRequest(BaseModel):
    """Request to extract files from a background-mode agent's encrypted tarball."""

    ephemeral_public_key: str = Field(..., description="Client transport public key (hex)")


class ExtractAgentFilesResponse(BaseModel):
    """Response with encrypted file manifest from agent tarball."""

    encrypted_files: EncryptedPayloadSchema


class AgentFileEntry(BaseModel):
    """A single file to write into an agent tarball."""

    path: str = Field(..., description="Relative file path within agent directory")
    encrypted_content: EncryptedPayloadSchema = Field(
        ..., description="File content encrypted to enclave transport key"
    )


class PackAgentFilesRequest(BaseModel):
    """Request to pack files into a new agent tarball (background mode)."""

    files: List[AgentFileEntry] = Field(..., description="Files to pack into the tarball")
