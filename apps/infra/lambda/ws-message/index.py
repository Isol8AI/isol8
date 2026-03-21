"""WebSocket $default handler — forwards message body to backend via ALB."""
import os
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = event.get("body", "") or ""

    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/message",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "Content-Type": "application/json",
            },
            data=body.encode("utf-8") if body else b"{}",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return {"statusCode": resp.status}
    except Exception as e:
        logger.error("Failed to forward message: %s", e)
        return {"statusCode": 500}
