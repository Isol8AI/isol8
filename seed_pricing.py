"""Seed the model_pricing table with current AWS Bedrock prices."""

import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from models.billing import ModelPricing

BEDROCK_PRICES = [
    {
        "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "display_name": "Claude 3.5 Sonnet",
        "input_cost_per_token": Decimal("0.000003"),
        "output_cost_per_token": Decimal("0.000015"),
    },
    {
        "model_id": "anthropic.claude-3-5-haiku-20241022-v1:0",
        "display_name": "Claude 3.5 Haiku",
        "input_cost_per_token": Decimal("0.0000008"),
        "output_cost_per_token": Decimal("0.000004"),
    },
    {
        "model_id": "anthropic.claude-3-opus-20240229-v1:0",
        "display_name": "Claude 3 Opus",
        "input_cost_per_token": Decimal("0.000015"),
        "output_cost_per_token": Decimal("0.000075"),
    },
    {
        "model_id": "meta.llama3-3-70b-instruct-v1:0",
        "display_name": "Llama 3.3 70B",
        "input_cost_per_token": Decimal("0.00000072"),
        "output_cost_per_token": Decimal("0.00000072"),
    },
    {
        "model_id": "meta.llama3-1-70b-instruct-v1:0",
        "display_name": "Llama 3.1 70B",
        "input_cost_per_token": Decimal("0.00000072"),
        "output_cost_per_token": Decimal("0.00000072"),
    },
    {
        "model_id": "amazon.nova-pro-v1:0",
        "display_name": "Amazon Nova Pro",
        "input_cost_per_token": Decimal("0.0000008"),
        "output_cost_per_token": Decimal("0.0000032"),
    },
    {
        "model_id": "amazon.nova-lite-v1:0",
        "display_name": "Amazon Nova Lite",
        "input_cost_per_token": Decimal("0.00000006"),
        "output_cost_per_token": Decimal("0.00000024"),
    },
    # Claude 4.6
    {
        "model_id": "anthropic.claude-opus-4-6-v1",
        "display_name": "Claude Opus 4.6",
        "input_cost_per_token": Decimal("0.000005"),
        "output_cost_per_token": Decimal("0.000025"),
    },
    # Claude 4.5 family
    {
        "model_id": "anthropic.claude-opus-4-5-20251101-v1:0",
        "display_name": "Claude Opus 4.5",
        "input_cost_per_token": Decimal("0.000005"),
        "output_cost_per_token": Decimal("0.000025"),
    },
    {
        "model_id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "display_name": "Claude Sonnet 4.5",
        "input_cost_per_token": Decimal("0.000003"),
        "output_cost_per_token": Decimal("0.000015"),
    },
    {
        "model_id": "anthropic.claude-haiku-4-5-20251001-v1:0",
        "display_name": "Claude Haiku 4.5",
        "input_cost_per_token": Decimal("0.000001"),
        "output_cost_per_token": Decimal("0.000005"),
    },
    # DeepSeek
    {
        "model_id": "deepseek.r1-v1:0",
        "display_name": "DeepSeek R1",
        "input_cost_per_token": Decimal("0.00000135"),
        "output_cost_per_token": Decimal("0.0000054"),
    },
    # OpenAI GPT-OSS (open weight)
    {
        "model_id": "openai.gpt-oss-120b-1:0",
        "display_name": "GPT-OSS 120B",
        "input_cost_per_token": Decimal("0.00000015"),
        "output_cost_per_token": Decimal("0.0000006"),
    },
    {
        "model_id": "openai.gpt-oss-20b-1:0",
        "display_name": "GPT-OSS 20B",
        "input_cost_per_token": Decimal("0.00000007"),
        "output_cost_per_token": Decimal("0.00000015"),
    },
    # Qwen3 (Alibaba)
    {
        "model_id": "qwen.qwen3-235b-a22b-2507-v1:0",
        "display_name": "Qwen3 235B",
        "input_cost_per_token": Decimal("0.00000022"),
        "output_cost_per_token": Decimal("0.00000088"),
    },
    {
        "model_id": "qwen.qwen3-32b-v1:0",
        "display_name": "Qwen3 32B",
        "input_cost_per_token": Decimal("0.00000015"),
        "output_cost_per_token": Decimal("0.0000006"),
    },
    # Mistral
    {
        "model_id": "mistral.mistral-large-2512-v1:0",
        "display_name": "Mistral Large 3",
        "input_cost_per_token": Decimal("0.0000005"),
        "output_cost_per_token": Decimal("0.0000015"),
    },
]


async def seed():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as db:
        for price_data in BEDROCK_PRICES:
            existing = await db.execute(
                select(ModelPricing).where(
                    ModelPricing.model_id == price_data["model_id"],
                    ModelPricing.is_active.is_(True),
                )
            )
            if existing.scalar_one_or_none():
                print(f"  Skipping {price_data['display_name']} (already exists)")
                continue

            pricing = ModelPricing(**price_data)
            db.add(pricing)
            print(f"  Added {price_data['display_name']}")

        await db.commit()
    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
