"""
Lambda authorizer for WebSocket API Gateway.

Validates two kinds of bearer tokens for WebSocket $connect:

1. Paperclip service-token JWTs (HS256, kind=paperclip_service)
   — Long-lived JWTs minted by the FastAPI backend (core/services/service_token.py),
     signed with a symmetric secret stored in Secrets Manager
     (isol8/{env}/paperclip_service_token_key). Used by Paperclip agents to
     reach a specific user's OpenClaw container via the existing WebSocket
     gateway. Checked FIRST because symmetric verify is far cheaper than
     a JWKS round-trip.

2. Clerk JWTs (RS256, browser sessions)
   — Standard end-user browser auth. Verified against Clerk's JWKS.

Returns IAM policy (WebSocket APIs require this format, not isAuthorized) plus
authorization context (userId, orgId, authKind) for the backend.
"""

import json
import logging
import os
import time
from typing import Any, Optional

import boto3
import jwt
from jwt import PyJWKClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clerk configuration from environment
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "")
CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "")

# Paperclip service-token configuration
SERVICE_TOKEN_KIND = "paperclip_service"
PAPERCLIP_SERVICE_TOKEN_KEY_SECRET_ARN = os.environ.get(
    "PAPERCLIP_SERVICE_TOKEN_KEY_SECRET_ARN", ""
)

# Cache JWKS client (reused across invocations)
_jwks_client = None

# Boto client for Secrets Manager (initialized lazily)
_secrets_client = None


def _get_secrets_client():
    global _secrets_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def _emit_metric(metric_name: str, value: int) -> None:
    """Emit a CloudWatch EMF metric to stdout.

    Lambda's log driver picks up Embedded Metric Format JSON automatically
    and publishes the metric without an explicit PutMetricData call. We use
    this so an alarm can fire on `ServiceTokenKeyLoadFailure > 0` without
    needing to wire CloudWatch SDK creds into the Lambda role.
    """
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Isol8/Authorizer",
                            "Dimensions": [["FunctionName"]],
                            "Metrics": [{"Name": metric_name, "Unit": "Count"}],
                        }
                    ],
                },
                "FunctionName": os.environ.get(
                    "AWS_LAMBDA_FUNCTION_NAME", "unknown"
                ),
                metric_name: value,
            }
        )
    )


def _load_service_token_key() -> str:
    """Fetch the Paperclip service-token signing key from Secrets Manager.

    Called once at cold-start. Returns "" on missing config or fetch failure
    (the service-token branch will then short-circuit to None and the
    Clerk path runs unchanged).
    """
    arn = PAPERCLIP_SERVICE_TOKEN_KEY_SECRET_ARN
    if not arn:
        return ""
    try:
        resp = _get_secrets_client().get_secret_value(SecretId=arn)
        return resp.get("SecretString", "") or ""
    except Exception as e:  # noqa: BLE001 — best-effort cold-start fetch
        # Use error (not warning) so log-metric-filters and alarms can pick
        # up the signal — a silent fall-through here disables service tokens
        # platform-wide with no other observable symptom.
        logger.error(f"Failed to load service-token signing key: {e}")
        return ""


# Cold-start: load the symmetric key once per Lambda container
PAPERCLIP_SERVICE_TOKEN_KEY = _load_service_token_key()
_emit_metric(
    "ServiceTokenKeyLoadSuccess"
    if PAPERCLIP_SERVICE_TOKEN_KEY
    else "ServiceTokenKeyLoadFailure",
    1,
)


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


def _try_service_token(token: str) -> Optional[dict]:
    """Validate a Paperclip service-token JWT.

    Returns the claims dict if the token is a valid service token; returns
    None if the token is not a service token (so the caller can fall through
    to the Clerk JWT path) or if signing-key config is missing.
    """
    if not PAPERCLIP_SERVICE_TOKEN_KEY:
        return None
    try:
        claims = jwt.decode(
            token,
            PAPERCLIP_SERVICE_TOKEN_KEY,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        return None
    if claims.get("kind") != SERVICE_TOKEN_KIND:
        return None
    if not claims.get("sub"):
        return None
    return claims


def handler(event: dict, context: Any) -> dict:
    """
    Lambda authorizer handler for WebSocket API.

    Validates Paperclip service tokens (cheap symmetric verify, checked first)
    and Clerk JWTs (RS256 via JWKS).

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

    # --- Try Paperclip service token first (cheap symmetric verify) ---
    service_claims = _try_service_token(token)
    if service_claims:
        user_id = service_claims["sub"]
        logger.info(f"Authorized via service token user_id={user_id}")
        return generate_policy(
            principal_id=user_id,
            effect="Allow",
            resource=method_arn,
            context={
                "userId": user_id,
                "orgId": "",
                "authKind": SERVICE_TOKEN_KIND,
            },
        )

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
        # Clerk v2 JWTs nest org claims under "o" key: {"id", "rol", "slg", "per"}
        org_claims = payload.get("o", {})
        org_id = org_claims.get("id") if isinstance(org_claims, dict) else None

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
                "authKind": "clerk_user",
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
