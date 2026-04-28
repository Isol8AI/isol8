import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { ApiStack } from "./stacks/api-stack";
import { AuthStack } from "./stacks/auth-stack";
import { ContainerStack } from "./stacks/container-stack";
import { DatabaseStack } from "./stacks/database-stack";
import { NetworkStack } from "./stacks/network-stack";
import { ObservabilityStack } from "./stacks/observability-stack";
import { ServiceStack } from "./stacks/service-stack";

/**
 * LocalStage — CDK stage for local development via LocalStack.
 *
 * Skips DnsStack (no Route53 hosted-zone lookup or ACM certificate creation)
 * and passes no certificate/hostedZone to ApiStack so it falls back to raw
 * API Gateway URLs.
 */
export class LocalStage extends cdk.Stage {
  constructor(scope: Construct, id: string, props?: cdk.StageProps) {
    super(scope, id, props);

    const env = "local";

    // Populate secrets with real values from environment variables.
    // In dev/prod these are set manually in the AWS console after deploy.
    // For local dev we pass them at deploy time so the ECS backend starts correctly.
    const auth = new AuthStack(this, `isol8-${env}-auth`, {
      stackName: `isol8-${env}-auth`,
      environment: env,
      secretValues: {
        clerk_issuer: process.env.CLERK_ISSUER ?? "https://up-moth-55.clerk.accounts.dev",
        clerk_secret_key: process.env.CLERK_SECRET_KEY ?? "",
        stripe_secret_key: process.env.STRIPE_SECRET_KEY ?? "",
        stripe_webhook_secret: process.env.STRIPE_WEBHOOK_SECRET ?? "",
        encryption_key: process.env.ENCRYPTION_KEY ?? "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=",
      },
    });

    // Skip DnsStack — no Route53/ACM needed locally
    const network = new NetworkStack(this, `isol8-${env}-network`, {
      stackName: `isol8-${env}-network`,
      environment: env,
      // No certificate — NetworkStack already handles this being optional
    });

    const database = new DatabaseStack(this, `isol8-${env}-database`, {
      stackName: `isol8-${env}-database`,
      environment: env,
      kmsKey: auth.kmsKey,
      vpc: network.vpc,
    });

    const container = new ContainerStack(this, `isol8-${env}-container`, {
      stackName: `isol8-${env}-container`,
      environment: env,
      vpc: network.vpc,
      kmsKeyArn: auth.kmsKey.keyArn,
    });

    const api = new ApiStack(this, `isol8-${env}-api`, {
      stackName: `isol8-${env}-api`,
      environment: env,
      vpc: network.vpc,
      // No certificate or hostedZone — ApiStack handles these being optional
      alb: network.alb,
      albHttpListenerArn: network.albHttpListenerArn,
      albSecurityGroup: network.albSecurityGroup,
    });

    const service = new ServiceStack(this, `isol8-${env}-service`, {
      stackName: `isol8-${env}-service`,
      environment: env,
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
      },
      secretNames: {
        clerkIssuer: `isol8/${env}/clerk_issuer`,
        clerkSecretKey: `isol8/${env}/clerk_secret_key`,
        stripeSecretKey: `isol8/${env}/stripe_secret_key`,
        stripeWebhookSecret: `isol8/${env}/stripe_webhook_secret`,
        encryptionKey: `isol8/${env}/encryption_key`,
        posthogProjectApiKey: `isol8/${env}/posthog_project_api_key`,
      },
      kmsKeyArn: auth.kmsKey.keyArn,
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
      managementApiUrl: api.managementApiUrl,
      connectionsTableName: api.connectionsTableName,
      wsApiId: api.wsApiId,
      wsStage: api.wsStage,
    });

    // ObservabilityStack — alarms, dashboard, canaries, account hardening
    new ObservabilityStack(this, `isol8-${env}-observability`, {
      stackName: `isol8-${env}-observability`,
      envName: env,
      backendService: service.service,
      backendLogGroupName: `/ecs/isol8-${env}`,
      alb: network.alb,
      wsApiId: api.wsApiId,
      cluster: container.cluster,
      efsFileSystem: container.efsFileSystem,
      databaseTables: {
        usersTable: database.usersTable,
        containersTable: database.containersTable,
        billingTable: database.billingTable,
        apiKeysTable: database.apiKeysTable,
        usageCountersTable: database.usageCountersTable,
        pendingUpdatesTable: database.pendingUpdatesTable,
        channelLinksTable: database.channelLinksTable,
      },
      connectionsTableName: api.connectionsTableName,
      authorizerFunctionName: `isol8-${env}-ws-authorizer`,
    });

    cdk.Tags.of(this).add("Project", "isol8");
    cdk.Tags.of(this).add("Environment", env);
  }
}
