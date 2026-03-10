"""
OpenClaw configuration generator for per-user containers.

Generates openclaw.json with Bedrock provider and tools configured.
Each container gets a gateway auth token so it can bind to LAN
(required for Docker port mapping).
"""

import json


def write_openclaw_config(
    region: str = "us-east-1",
    primary_model: str = "amazon-bedrock/us.anthropic.claude-opus-4-6-v1",
    gateway_token: str = "",
    proxy_base_url: str = "https://api.isol8.co/api/v1/proxy",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        primary_model: Default model for agents.
        gateway_token: Auth token for the gateway HTTP API.
        proxy_base_url: Base URL for the tool proxy (Perplexity search, etc.).

    Returns:
        JSON string of the openclaw.json config.
    """
    auth = {"mode": "token", "token": gateway_token} if gateway_token else {"mode": "none"}

    # Build search config — Perplexity via our proxy
    if gateway_token:
        search_config = {
            "enabled": True,
            "provider": "perplexity",
            "perplexity": {
                "apiKey": gateway_token,
                "baseUrl": f"{proxy_base_url}/search",
            },
        }
    else:
        search_config = {"enabled": False}

    config = {
        "gateway": {
            "mode": "local",
            "auth": auth,
            "controlUi": {
                "enabled": False,
            },
            "http": {
                "endpoints": {
                    "chatCompletions": {"enabled": False},
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
                        # --- Claude (Anthropic) ---
                        {
                            "id": "us.anthropic.claude-opus-4-6-v1",
                            "name": "Claude Opus 4.6",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.anthropic.claude-opus-4-5-20251101-v1:0",
                            "name": "Claude Opus 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                            "name": "Claude Sonnet 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                            "name": "Claude Haiku 4.5",
                            "contextWindow": 200000,
                            "maxTokens": 16384,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- DeepSeek ---
                        {
                            "id": "us.deepseek.r1-v1:0",
                            "name": "DeepSeek R1",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- Meta Llama ---
                        {
                            "id": "us.meta.llama3-3-70b-instruct-v1:0",
                            "name": "Llama 3.3 70B",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": False,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- Amazon Nova ---
                        {
                            "id": "us.amazon.nova-pro-v1:0",
                            "name": "Amazon Nova Pro",
                            "contextWindow": 300000,
                            "maxTokens": 5120,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.amazon.nova-lite-v1:0",
                            "name": "Amazon Nova Lite",
                            "contextWindow": 300000,
                            "maxTokens": 5120,
                            "reasoning": False,
                            "input": ["text", "image"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- OpenAI (GPT-OSS open weight) ---
                        {
                            "id": "us.openai.gpt-oss-120b-1:0",
                            "name": "GPT-OSS 120B",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.openai.gpt-oss-20b-1:0",
                            "name": "GPT-OSS 20B",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- Qwen (Alibaba) ---
                        {
                            "id": "us.qwen.qwen3-235b-a22b-2507-v1:0",
                            "name": "Qwen3 235B",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        {
                            "id": "us.qwen.qwen3-32b-v1:0",
                            "name": "Qwen3 32B",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                            "reasoning": True,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        },
                        # --- Mistral ---
                        {
                            "id": "us.mistral.mistral-large-2512-v1:0",
                            "name": "Mistral Large 3",
                            "contextWindow": 128000,
                            "maxTokens": 8192,
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
                    # Claude
                    primary_model: {"alias": "Opus 4.6"},
                    "amazon-bedrock/us.anthropic.claude-opus-4-5-20251101-v1:0": {"alias": "Opus 4.5"},
                    "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0": {"alias": "Sonnet 4.5"},
                    "amazon-bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0": {"alias": "Haiku 4.5"},
                    # DeepSeek
                    "amazon-bedrock/us.deepseek.r1-v1:0": {"alias": "DeepSeek R1"},
                    # Meta
                    "amazon-bedrock/us.meta.llama3-3-70b-instruct-v1:0": {"alias": "Llama 3.3 70B"},
                    # Amazon
                    "amazon-bedrock/us.amazon.nova-pro-v1:0": {"alias": "Nova Pro"},
                    "amazon-bedrock/us.amazon.nova-lite-v1:0": {"alias": "Nova Lite"},
                    # OpenAI (GPT-OSS)
                    "amazon-bedrock/us.openai.gpt-oss-120b-1:0": {"alias": "GPT-OSS 120B"},
                    "amazon-bedrock/us.openai.gpt-oss-20b-1:0": {"alias": "GPT-OSS 20B"},
                    # Qwen
                    "amazon-bedrock/us.qwen.qwen3-235b-a22b-2507-v1:0": {"alias": "Qwen3 235B"},
                    "amazon-bedrock/us.qwen.qwen3-32b-v1:0": {"alias": "Qwen3 32B"},
                    # Mistral
                    "amazon-bedrock/us.mistral.mistral-large-2512-v1:0": {"alias": "Mistral Large 3"},
                },
                "memorySearch": {
                    "enabled": False,
                },
            },
        },
        "tools": {
            "profile": "full",
            "deny": ["canvas", "nodes"],
            "web": {
                "search": search_config,
                "fetch": {"enabled": True},
            },
            "media": {
                "image": {"enabled": True},
                "audio": {"enabled": False},
                "video": {"enabled": False},
            },
        },
        "skills": {
            "install": {
                "nodeManager": "npm",
            },
        },
        "hooks": {
            "internal": {
                "entries": {
                    "command-logger": {"enabled": True},
                    "session-memory": {"enabled": True},
                },
            },
        },
        "plugins": {
            "slots": {
                "memory": "memory-lancedb" if gateway_token else "memory-core",
            },
            "entries": {
                "memory-lancedb": {
                    "enabled": bool(gateway_token),
                    "config": {
                        "embedding": {
                            "apiKey": gateway_token or "disabled",
                            "model": "titan-embed-v2",
                            "baseUrl": f"{proxy_base_url}/embeddings",
                            "dimensions": 1024,
                        },
                        "autoCapture": True,
                        "autoRecall": True,
                        "captureMaxChars": 2000,
                    },
                },
            },
        },
        "channels": {
            "telegram": {
                "dmPolicy": "pairing",
            },
            "whatsapp": {
                "dmPolicy": "pairing",
            },
            "discord": {
                "dmPolicy": "pairing",
            },
        },
        "web": {
            "enabled": True,
        },
        "browser": {"enabled": False},
        "update": {"checkOnStart": False},
    }

    return json.dumps(config, indent=2)


def write_mcporter_config(servers: dict | None = None) -> str:
    """Generate a mcporter.json config string.

    Args:
        servers: Optional dict of server entries. Defaults to empty.

    Returns:
        JSON string of the mcporter config.
    """
    config = {"servers": servers or {}}
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
