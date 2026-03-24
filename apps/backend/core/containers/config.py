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
    provider: str = "bedrock",
    ollama_base_url: str = "",
) -> str:
    """Generate an openclaw.json config string for a user's container.

    Args:
        region: AWS region for Bedrock.
        primary_model: Default model for agents.
        gateway_token: Token used as API key for the search proxy.
        proxy_base_url: Base URL for the tool proxy (Perplexity search, etc.).
        provider: LLM provider to use ("bedrock" or "ollama").
        ollama_base_url: Base URL for Ollama server (e.g. "http://ollama:11434").

    Returns:
        JSON string of the openclaw.json config.
    """
    # Trusted proxy auth — backend is the only path to the container (private subnet).
    # OpenClaw trusts connections from the VPC CIDR and reads user identity from header.
    auth = {
        "mode": "trusted-proxy",
        "trustedProxy": {
            "userHeader": "x-forwarded-user",
        },
    }

    # Build search plugin config — Perplexity via our proxy (v2026.3.22+ format)
    search_plugin = {}
    if gateway_token:
        search_plugin = {
            "perplexity": {
                "enabled": True,
                "config": {
                    "webSearch": {
                        "apiKey": gateway_token,
                        "baseUrl": f"{proxy_base_url}/search",
                    },
                },
            },
        }

    # Build provider-specific models config
    if provider == "ollama":
        providers_config = {
            "ollama": {
                "baseUrl": ollama_base_url,
                "api": "ollama",
                "apiKey": "ollama-local",
                "models": [
                    {
                        "id": "qwen2.5:14b",
                        "name": "Qwen 2.5 14B (Local)",
                        "contextWindow": 32768,
                        "maxTokens": 4096,
                        "reasoning": False,
                        "input": ["text"],
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    },
                ],
            },
        }
        bedrock_discovery = {"enabled": False}
        agent_models = {
            primary_model: {"alias": "Qwen 2.5 14B"},
        }
    else:
        providers_config = {
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
        }
        bedrock_discovery = {"enabled": True}
        agent_models = {
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
        }

    config = {
        "gateway": {
            "mode": "local",
            "bind": "lan",
            "auth": auth,
            "trustedProxies": ["10.0.0.0/8"],
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
            "providers": providers_config,
            "bedrockDiscovery": bedrock_discovery,
        },
        "agents": {
            "defaults": {
                "model": {
                    "primary": primary_model,
                },
                "models": agent_models,
                "memorySearch": {
                    "enabled": True,
                },
            },
        },
        "memory": {
            "backend": "qmd",
            "citations": "auto",
            "qmd": {
                "command": "/home/node/.npm-global/bin/qmd",
                "includeDefaultMemory": True,
                "searchMode": "search",
                "update": {
                    "interval": "5m",
                    "debounceMs": 15000,
                    "onBoot": True,
                    "waitForBootSync": False,
                },
                "limits": {
                    "maxResults": 6,
                    "timeoutMs": 4000,
                },
                "scope": {
                    "default": "deny",
                    "rules": [
                        {"action": "allow", "match": {"chatType": "direct"}},
                    ],
                },
            },
        },
        "tools": {
            "profile": "full",
            "deny": ["canvas", "nodes"],
            "web": {
                "search": {"enabled": bool(gateway_token), "provider": "perplexity"}
                if gateway_token
                else {"enabled": False},
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
            "slots": {},
            "entries": search_plugin,
        },
        "channels": {
            "telegram": {
                "enabled": False,
                "dmPolicy": "pairing",
            },
            "whatsapp": {
                "enabled": False,
                "dmPolicy": "pairing",
            },
            "discord": {
                "enabled": False,
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
