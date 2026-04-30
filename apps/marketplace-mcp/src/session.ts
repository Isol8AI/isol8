import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, PutCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";
import { randomUUID } from "node:crypto";

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));

export async function createSession(opts: {
  table: string;
  licenseKey: string;
  listingId: string;
  version: number;
}): Promise<string> {
  const sessionId = randomUUID();
  const now = Math.floor(Date.now() / 1000);
  await ddb.send(new PutCommand({
    TableName: opts.table,
    Item: {
      session_id: sessionId,
      license_key: opts.licenseKey,
      listing_id: opts.listingId,
      listing_version: opts.version,
      started_at: now,
      last_activity_at: now,
      ttl: now + 24 * 60 * 60,
    },
  }));
  return sessionId;
}

export async function touchSession(opts: { table: string; sessionId: string }) {
  const now = Math.floor(Date.now() / 1000);
  await ddb.send(new UpdateCommand({
    TableName: opts.table,
    Key: { session_id: opts.sessionId },
    UpdateExpression: "SET last_activity_at = :now",
    ExpressionAttributeValues: { ":now": now },
  }));
}
