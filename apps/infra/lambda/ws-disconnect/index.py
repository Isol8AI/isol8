"""WebSocket $disconnect handler — removes connection from DynamoDB, notifies backend."""
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

    logger.info("WebSocket disconnect: connection_id=%s", connection_id)

    try:
        table.delete_item(Key={"connectionId": connection_id})
    except Exception as e:
        logger.warning("Failed to remove connection from DynamoDB: %s", e)

    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/disconnect",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning("Failed to notify backend of disconnect: %s", e)

    return {"statusCode": 200}
