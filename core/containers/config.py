"""
OpenClaw configuration generator for per-user containers.

Generates openclaw.json with Bedrock provider and tools configured.
Each container gets a gateway auth token so it can bind to LAN
(required for Docker port mapping).
"""

import json


def write_openclaw_config(
    region: str = "us-east-1",
    brave_api_key: str = "",
    primary_model: str = "amazon-bedrock/anthropic.claude-opus-4-5-20251101-v1:0",
    gateway_token: str = "",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        brave_api_key: Brave Search API key (optional).
        primary_model: Default model for agents.
        gateway_token: Auth token for the gateway HTTP API.

    Returns:
        JSON string of the openclaw.json config.
    """
    auth = {"mode": "token", "token": gateway_token} if gateway_token else {"mode": "none"}
    config = {
        "gateway": {
            "mode": "local",
            "auth": auth,
            "controlUi": {"enabled": True},
            "http": {
                "endpoints": {
                    "chatCompletions": {"enabled": True},
                },
            },
        },
        "models": {
            "providers": {
                "amazon-bedrock": {
                    "baseUrl": f"https://bedrock-runtime.{region}.amazonaws.com",
                    "api": "bedrock-converse-stream",
                    "auth": "aws-sdk",
                    "models": [
                        {
                            "id": "anthropic.claude-opus-4-5-20251101-v1:0",
                            "name": "Claude Opus 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
                            "name": "Claude Sonnet 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "anthropic.claude-haiku-4-5-20251001-v1:0",
                            "name": "Claude Haiku 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                    ],
                },
            },
            "bedrockDiscovery": {"enabled": True},
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": primary_model,
                },
                "models": {
                    primary_model: {"alias": "Opus 4.5"},
                    "amazon-bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0": {"alias": "Sonnet 4.5"},
                    "amazon-bedrock/anthropic.claude-haiku-4-5-20251001-v1:0": {"alias": "Haiku 4.5"},
                },
                "memorySearch": {
                    "enabled": True,
                    "provider": "local",
                    "local": {
                        "modelPath": "hf:ggml-org/embeddinggemma-300m-qat-q8_0-GGUF/embeddinggemma-300m-qat-Q8_0.gguf",
                    },
                    "fallback": "none",
                    "sources": ["memory", "sessions"],
                },
            },
        },
        "tools": {
            "web": {
                "search": {"enabled": bool(brave_api_key), "provider": "brave"},
                "fetch": {"enabled": True},
            },
            "media": {
                "image": {"enabled": False},
                "audio": {"enabled": False},
                "video": {"enabled": False},
            },
        },
        "browser": {"enabled": False},
        "update": {"checkOnStart": False},
    }

    return json.dumps(config, indent=2)


def patch_openclaw_config(
    existing_config: dict,
    updates: dict,
) -> dict:
    """Apply partial updates to an existing openclaw.json config.

    Performs a shallow merge at the top-level section keys (gateway, models,
    agents, tools, browser, update). Nested dicts within each section are
    deep-merged.

    Args:
        existing_config: Current openclaw.json as dict.
        updates: Partial config dict with sections to update.

    Returns:
        Merged config dict.
    """
    merged = dict(existing_config)
    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
