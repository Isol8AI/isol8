"""
Lambda authorizer for WebSocket API Gateway.

Validates Clerk JWTs for browser/frontend WebSocket connections.

Returns authorization context (user_id, org_id) for API Gateway to forward to backend.
"""

import os
import logging
from typing import Any

import jwt
from jwt import PyJWKClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clerk configuration from environment
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "")
CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "")

# Cache JWKS client (reused across invocations)
_jwks_client = None


def get_jwks_client() -> PyJWKClient:
    """Get or create cached JWKS client."""
    global _jwks_client
    if _jwks_client is None:
        if not CLERK_JWKS_URL:
            raise ValueError("CLERK_JWKS_URL environment variable not set")
        _jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True)
    return _jwks_client


def generate_policy(principal_id: str, effect: str, resource: str, context: dict = None) -> dict:
    """
    Generate IAM policy document for WebSocket API authorizer.

    WebSocket APIs require IAM policy format (unlike HTTP APIs which use isAuthorized).
    """
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def handler(event: dict, context: Any) -> dict:
    """
    Lambda authorizer handler for WebSocket API.

    Validates Clerk JWTs for browser WebSocket connections.

    Args:
        event: API Gateway authorizer event containing:
            - queryStringParameters: {token: "..."}
            - methodArn: Resource ARN for policy
        context: Lambda context (unused)

    Returns:
        IAM policy document (WebSocket APIs require this format, not isAuthorized).
    """
    logger.info("Authorizer invoked")

    # methodArn is used as the resource in the policy
    method_arn = event.get("methodArn", "*")

    # Extract token from query parameters
    query_params = event.get("queryStringParameters") or {}
    token = query_params.get("token")

    if not token:
        logger.warning("No token provided in query parameters")
        return generate_policy("unauthorized", "Deny", method_arn)

    # --- Validate Clerk JWT ---
    try:
        # Get signing key from JWKS
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Decode and validate JWT
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": False,  # Clerk doesn't use audience
            }
        )

        # Extract user and org info
        user_id = payload.get("sub")
        org_id = payload.get("org_id")  # Present if user is in org context

        if not user_id:
            logger.warning("Token missing 'sub' claim")
            return generate_policy("unauthorized", "Deny", method_arn)

        logger.info(f"Authorized user_id={user_id}, org_id={org_id or 'personal'}")

        # Return IAM policy with Allow effect and user context
        return generate_policy(
            principal_id=user_id,
            effect="Allow",
            resource=method_arn,
            context={
                "userId": user_id,
                "orgId": org_id or "",
            }
        )

    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return generate_policy("unauthorized", "Deny", method_arn)
    except jwt.InvalidIssuerError:
        logger.warning("Invalid token issuer")
        return generate_policy("unauthorized", "Deny", method_arn)
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return generate_policy("unauthorized", "Deny", method_arn)
    except Exception as e:
        logger.exception(f"Unexpected error validating token: {e}")
        return generate_policy("unauthorized", "Deny", method_arn)
