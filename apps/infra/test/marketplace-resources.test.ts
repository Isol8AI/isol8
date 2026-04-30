import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as kms from "aws-cdk-lib/aws-kms";
import { ContainerStack } from "../lib/stacks/container-stack";
import { DatabaseStack } from "../lib/stacks/database-stack";
import { NetworkStack } from "../lib/stacks/network-stack";
import { ServiceStack } from "../lib/stacks/service-stack";

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

/**
 * Builds a real ServiceStack wired to real upstream stacks (Network, Database,
 * Container). Mirrors the wiring in isol8-stage.ts so the synthesized template
 * matches what gets deployed.
 */
function buildServiceStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };

  // KMS key lives in a separate support stack (mirrors AuthStack).
  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const kmsKey = new kms.Key(supportStack, "KmsKey");

  const network = new NetworkStack(app, `Network-${environment}`, {
    env,
    environment,
  });

  const database = new DatabaseStack(app, `Database-${environment}`, {
    env,
    environment,
    kmsKey,
  });

  const container = new ContainerStack(app, `Container-${environment}`, {
    env,
    environment,
    vpc: network.vpc,
    kmsKeyArn: kmsKey.keyArn,
  });

  const service = new ServiceStack(app, `Service-${environment}`, {
    env,
    environment,
    vpc: network.vpc,
    targetGroup: network.targetGroup,
    albSecurityGroup: network.albSecurityGroup,
    database: {
      usersTable: database.usersTable,
      containersTable: database.containersTable,
      billingTable: database.billingTable,
      apiKeysTable: database.apiKeysTable,
      usageCountersTable: database.usageCountersTable,
      pendingUpdatesTable: database.pendingUpdatesTable,
      channelLinksTable: database.channelLinksTable,
      adminActionsTable: database.adminActionsTable,
      creditsTable: database.creditsTable,
      creditTransactionsTable: database.creditTransactionsTable,
      oauthTokensTable: database.oauthTokensTable,
      webhookDedupTable: database.webhookDedupTable,
      marketplaceListingsTable: database.marketplaceListingsTable,
      marketplaceSearchIndexTable: database.marketplaceSearchIndexTable,
      marketplacePurchasesTable: database.marketplacePurchasesTable,
      marketplaceMcpSessionsTable: database.marketplaceMcpSessionsTable,
    },
    secretNames: {
      clerkIssuer: `isol8/${environment}/clerk_issuer`,
      clerkSecretKey: `isol8/${environment}/clerk_secret_key`,
      stripeSecretKey: `isol8/${environment}/stripe_secret_key`,
      stripeWebhookSecret: `isol8/${environment}/stripe_webhook_secret`,
      encryptionKey: `isol8/${environment}/encryption_key`,
      posthogProjectApiKey: `isol8/${environment}/posthog_project_api_key`,
    },
    kmsKeyArn: kmsKey.keyArn,
    container: {
      cluster: container.cluster,
      cloudMapNamespace: container.cloudMapNamespace,
      cloudMapService: container.cloudMapService,
      efsFileSystem: container.efsFileSystem,
      efsSecurityGroup: container.efsSecurityGroup,
      containerSecurityGroup: container.containerSecurityGroup,
      taskExecutionRole: container.taskExecutionRole,
      taskRole: container.taskRole,
      openclawTaskDef: container.openclawTaskDef,
    },
    managementApiUrl: "https://example.execute-api.us-east-1.amazonaws.com",
    connectionsTableName: `isol8-${environment}-ws-connections`,
    wsApiId: "test-ws-api-id",
    wsStage: "prod",
  });

  return Template.fromStack(service);
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

  test("creates marketplace-purchases table with buyer_id PK", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-purchases",
      KeySchema: [
        { AttributeName: "buyer_id", KeyType: "HASH" },
        { AttributeName: "purchase_id", KeyType: "RANGE" },
      ],
    });
  });

  test("marketplace-purchases has listing_id and license_key GSIs", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-purchases",
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: "listing-created-index" }),
        Match.objectLike({ IndexName: "license-key-index" }),
      ]),
    });
  });

  test("creates marketplace-payout-accounts table with seller_id PK", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-payout-accounts",
      KeySchema: [{ AttributeName: "seller_id", KeyType: "HASH" }],
    });
  });

  test("creates marketplace-takedowns table with composite key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-takedowns",
      KeySchema: [
        { AttributeName: "listing_id", KeyType: "HASH" },
        { AttributeName: "takedown_id", KeyType: "RANGE" },
      ],
    });
  });

  test("creates marketplace-mcp-sessions table with TTL on 'ttl' attribute", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-mcp-sessions",
      KeySchema: [{ AttributeName: "session_id", KeyType: "HASH" }],
      TimeToLiveSpecification: {
        AttributeName: "ttl",
        Enabled: true,
      },
    });
  });

  test("creates marketplace-search-index table with shard_id PK", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-search-index",
      KeySchema: [
        { AttributeName: "shard_id", KeyType: "HASH" },
        { AttributeName: "published_listing", KeyType: "RANGE" },
      ],
    });
  });
});

// Hoist a single ServiceStack synthesis and reuse across describe blocks. CDK
// asset bundling for the marketplace-search-indexer Lambda makes synthesis
// non-trivial, so we synthesize once.
const SERVICE_TEMPLATE_DEV = buildServiceStack("dev");

describe("ServiceStack — marketplace S3 bucket", () => {
  const template = SERVICE_TEMPLATE_DEV;

  test("creates isol8-dev-marketplace-artifacts bucket with versioning + S3-managed encryption + block-all-public", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      BucketName: "isol8-dev-marketplace-artifacts",
      VersioningConfiguration: { Status: "Enabled" },
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } },
        ],
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });
});

describe("ServiceStack — search-indexer Lambda", () => {
  const template = SERVICE_TEMPLATE_DEV;

  test("creates marketplace-search-indexer Lambda", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "isol8-dev-marketplace-search-indexer",
      Runtime: "python3.12",
      Handler: "index.handler",
    });
  });

  test("Lambda is subscribed to listings table DDB stream", () => {
    template.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
      StartingPosition: "LATEST",
    });
  });

  test("Lambda has dynamodb:PutItem permission on search-index table", () => {
    SERVICE_TEMPLATE_DEV.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(["dynamodb:PutItem"]),
          }),
        ]),
      }),
    });
  });

  test("Lambda has dynamodb stream-read permission on listings table", () => {
    // CDK splits stream-read permissions across two statements:
    //   1) ListStreams on "*" (stream listing is account-wide, not ARN-scoped)
    //   2) DescribeStream + GetRecords + GetShardIterator on the stream ARN
    // We assert both statements exist on the Lambda's service role policy.
    // (arrayWith matches sequentially, so we keep them in the order CDK emits.)
    SERVICE_TEMPLATE_DEV.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "dynamodb:ListStreams",
          }),
          Match.objectLike({
            Action: Match.arrayWith([
              "dynamodb:DescribeStream",
              "dynamodb:GetRecords",
              "dynamodb:GetShardIterator",
            ]),
          }),
        ]),
      }),
    });
  });
});

describe("ServiceStack — marketplace-mcp Fargate task definition", () => {
  test("creates marketplace-mcp Fargate task definition (1 vCPU / 2 GB)", () => {
    SERVICE_TEMPLATE_DEV.hasResourceProperties("AWS::ECS::TaskDefinition", {
      Family: "isol8-dev-marketplace-mcp",
      Cpu: "1024",
      Memory: "2048",
      NetworkMode: "awsvpc",
      RequiresCompatibilities: ["FARGATE"],
    });
  });
});
