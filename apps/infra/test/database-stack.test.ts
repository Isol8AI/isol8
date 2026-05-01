import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import { Match, Template } from "aws-cdk-lib/assertions";
import { DatabaseStack } from "../lib/stacks/database-stack";

function buildStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };
  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const kmsKey = new kms.Key(supportStack, "KmsKey");
  const databaseStack = new DatabaseStack(app, `Database-${environment}`, {
    env,
    environment,
    kmsKey,
  });
  return Template.fromStack(databaseStack);
}

describe("DatabaseStack — admin-actions table", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("dev");
  });

  test("creates isol8-{env}-admin-actions with composite key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-admin-actions",
      KeySchema: [
        { AttributeName: "admin_user_id", KeyType: "HASH" },
        { AttributeName: "timestamp_action_id", KeyType: "RANGE" },
      ],
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  test("admin-actions has target-timestamp GSI for per-target audit queries", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-admin-actions",
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({
          IndexName: "target-timestamp-index",
          KeySchema: [
            { AttributeName: "target_user_id", KeyType: "HASH" },
            { AttributeName: "timestamp_action_id", KeyType: "RANGE" },
          ],
        }),
      ]),
    });
  });

  test("admin-actions uses customer-managed KMS encryption (matches other tables)", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-admin-actions",
      SSESpecification: Match.objectLike({
        SSEEnabled: true,
        SSEType: "KMS",
      }),
    });
  });

  test("admin-actions has point-in-time recovery enabled", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-admin-actions",
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
    });
  });

  test("admin-actions has NO TTL (audit rows kept forever per CEO review)", () => {
    // CDK omits the TimeToLiveSpecification entirely when no TTL is set.
    // Assert it's absent on this specific table.
    const tables = template.findResources("AWS::DynamoDB::Table", {
      Properties: { TableName: "isol8-dev-admin-actions" },
    });
    const tableLogicalIds = Object.keys(tables);
    expect(tableLogicalIds).toHaveLength(1);
    const props = tables[tableLogicalIds[0]].Properties;
    expect(props.TimeToLiveSpecification).toBeUndefined();
  });

  test("dev environment uses DESTROY removal policy (matches other dev tables)", () => {
    const tables = template.findResources("AWS::DynamoDB::Table", {
      Properties: { TableName: "isol8-dev-admin-actions" },
    });
    const logicalId = Object.keys(tables)[0];
    expect(tables[logicalId].DeletionPolicy).toBe("Delete");
  });
});

describe("DatabaseStack — admin-actions table — prod", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("prod");
  });

  test("prod environment uses RETAIN removal policy", () => {
    const tables = template.findResources("AWS::DynamoDB::Table", {
      Properties: { TableName: "isol8-prod-admin-actions" },
    });
    const logicalId = Object.keys(tables)[0];
    expect(tables[logicalId].DeletionPolicy).toBe("Retain");
  });
});
