import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as kms from "aws-cdk-lib/aws-kms";
import { DatabaseStack } from "../lib/stacks/database-stack";

function buildDbStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };
  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const kmsKey = new kms.Key(supportStack, "KmsKey");
  const dbStack = new DatabaseStack(app, `Database-${environment}`, {
    env,
    environment,
    kmsKey,
  });
  return Template.fromStack(dbStack);
}

describe("DatabaseStack — marketplace tables", () => {
  const template = buildDbStack("dev");

  test("creates marketplace-listings table with composite key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listings",
      KeySchema: [
        { AttributeName: "listing_id", KeyType: "HASH" },
        { AttributeName: "version", KeyType: "RANGE" },
      ],
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  test("marketplace-listings has all 4 expected GSIs", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listings",
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: "slug-version-index" }),
        Match.objectLike({ IndexName: "seller-created-index" }),
        Match.objectLike({ IndexName: "status-published-index" }),
        Match.objectLike({ IndexName: "tag-published-index" }),
      ]),
    });
  });

  test("creates marketplace-listing-versions table (immutable history)", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listing-versions",
      KeySchema: [
        { AttributeName: "listing_id", KeyType: "HASH" },
        { AttributeName: "version", KeyType: "RANGE" },
      ],
    });
  });

  test("dev environment uses DESTROY removal policy for marketplace tables", () => {
    template.hasResource("AWS::DynamoDB::Table", {
      Properties: { TableName: "isol8-dev-marketplace-listings" },
      DeletionPolicy: "Delete",
    });
  });
});
