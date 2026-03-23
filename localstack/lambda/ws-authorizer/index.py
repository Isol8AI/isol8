"""WebSocket API Gateway Lambda Authorizer for LocalStack.
Validates Clerk JWTs from the query string (token parameter).
"""

import json
import os
import time

import jwt
import requests

CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "")
_jwks_cache = {"keys": [], "fetched_at": 0}


def _get_jwks():
    """Fetch and cache Clerk JWKS keys (1 hour TTL)."""
    now = time.time()
    if now - _jwks_cache["fetched_at"] < 3600 and _jwks_cache["keys"]:
        return _jwks_cache["keys"]
    try:
        resp = requests.get(f"{CLERK_ISSUER}/.well-known/jwks.json", timeout=5)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json().get("keys", [])
        _jwks_cache["fetched_at"] = now
    except Exception as e:
        print(f"JWKS fetch failed: {e}")
    return _jwks_cache["keys"]


def handler(event, context):
    """Lambda authorizer handler for WebSocket $connect."""
    token = event.get("queryStringParameters", {}).get("token", "")
    method_arn = event.get("methodArn", "arn:aws:execute-api:us-east-1:000000000000:local/local/$connect")

    if not token:
        return _deny(method_arn)

    try:
        jwks = _get_jwks()
        if not jwks:
            return _deny(method_arn)

        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")

        key = None
        for k in jwks:
            if k.get("kid") == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
                break

        if not key:
            return _deny(method_arn)

        payload = jwt.decode(token, key, algorithms=["RS256"], issuer=CLERK_ISSUER)
        user_id = payload.get("sub", "")
        return _allow(method_arn, user_id, payload)

    except jwt.ExpiredSignatureError:
        print("Token expired")
        return _deny(method_arn)
    except Exception as e:
        print(f"Auth failed: {e}")
        return _deny(method_arn)


def _allow(method_arn, principal_id, context_data):
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": "Allow", "Resource": method_arn}],
        },
        "context": {
            "userId": context_data.get("sub", ""),
            "orgId": context_data.get("org_id", ""),
        },
    }


def _deny(method_arn):
    return {
        "principalId": "unauthorized",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": "Deny", "Resource": method_arn}],
        },
    }
