"""WebSocket $connect handler — stores connection in DynamoDB, notifies backend."""
import os
import urllib.request
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    authorizer = event["requestContext"].get("authorizer", {})
    user_id = authorizer.get("userId", "")
    org_id = authorizer.get("orgId", "")

    logger.info("WebSocket connect: connection_id=%s user_id=%s", connection_id, user_id)

    table.put_item(Item={
        "connectionId": connection_id,
        "userId": user_id,
        "orgId": org_id or "",
        "connectedAt": str(event["requestContext"].get("connectedAt", "")),
    })

    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/connect",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "x-user-id": user_id,
                "x-org-id": org_id or "",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning("Failed to notify backend of connect: %s", e)

    return {"statusCode": 200}
