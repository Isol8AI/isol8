"""
OpenClaw configuration generator for per-user containers.

Generates openclaw.json with Bedrock provider, tools, and memory search
configured. Reuses the same config structure as the shared gateway
(core/gateway/manager.py) but parameterized per user.
"""

import json


def write_openclaw_config(
    region: str = "us-east-1",
    brave_api_key: str = "",
    primary_model: str = "amazon-bedrock/us.anthropic.claude-opus-4-5-20251101-v1:0",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        brave_api_key: Brave Search API key (optional).
        primary_model: Default model for agents.

    Returns:
        JSON string of the openclaw.json config.
    """
    config = {
        "gateway": {
            "mode": "local",
            "auth": {"mode": "none"},
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
                            "id": "us.anthropic.claude-opus-4-5-20251101-v1:0",
                            "name": "Claude Opus 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                    ],
                },
            },
            "bedrockDiscovery": {"enabled": False},
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": primary_model,
                },
                "memorySearch": {
                    "enabled": True,
                    "provider": "bedrock",
                    "model": "amazon.nova-2-multimodal-embeddings-v1:0",
                    "sources": ["memory", "sessions"],
                    "store": {
                        "driver": "sqlite",
                    },
                    "sync": {"watch": False, "onSessionStart": True, "onSearch": True},
                    "query": {
                        "maxResults": 20,
                        "hybrid": {"enabled": True, "vectorWeight": 0.7, "textWeight": 0.3},
                    },
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
