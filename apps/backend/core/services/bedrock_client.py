"""
Bedrock client factory.

Uses IAM role credentials by default (no credential service needed).
"""

import os

import boto3
from botocore.config import Config as BotoConfig


class BedrockClientFactory:
    """Factory for creating Bedrock clients."""

    @staticmethod
    def create_client(timeout: float = 120.0):
        """
        Create a Bedrock runtime client using IAM role credentials.
        """
        boto_config = BotoConfig(
            read_timeout=int(timeout),
            connect_timeout=10,
            retries={"max_attempts": 2},
        )

        return boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=boto_config,
        )
