import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { DockerImageAsset, Platform } from "aws-cdk-lib/aws-ecr-assets";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";

/**
 * Secret name strings (NOT ISecret objects) to avoid cross-stack dependency
 * cycles. ServiceStack imports them locally via fromSecretNameV2, which
 * prevents CDK from auto-granting KMS access on AuthStack's key.
 */
export interface SecretNames {
  clerkIssuer: string;
  clerkSecretKey: string;
  stripeSecretKey: string;
  stripeWebhookSecret: string;
  encryptionKey: string;
}

export interface ServiceStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  targetGroup: elbv2.IApplicationTargetGroup;
  albSecurityGroup: ec2.ISecurityGroup;
  database: {
    usersTable: dynamodb.Table;
    containersTable: dynamodb.Table;
    billingTable: dynamodb.Table;
    apiKeysTable: dynamodb.Table;
    usageCountersTable: dynamodb.Table;
    pendingUpdatesTable: dynamodb.Table;
    channelLinksTable: dynamodb.Table;
  };
  /** Pass secret names (strings) to avoid cross-stack KMS auto-grant cycles. */
  secretNames: SecretNames;
  /** Pass as string ARN to avoid cross-stack dependency cycle. */
  kmsKeyArn: string;
  container: {
    cluster: ecs.ICluster;
    cloudMapNamespace: servicediscovery.IPrivateDnsNamespace;
    cloudMapService: servicediscovery.IService;
    efsFileSystem: efs.IFileSystem;
    efsSecurityGroup: ec2.ISecurityGroup;
    containerSecurityGroup: ec2.ISecurityGroup;
    taskExecutionRole: iam.IRole;
    taskRole: iam.IRole;
    openclawTaskDef: ecs.ITaskDefinition;
  };
  managementApiUrl: string;
  connectionsTableName: string;
  wsApiId: string;
  wsStage: string;
  /** Optional: page topic ARN from ObservabilityStack (set via env var import). */
  alertPageTopicArn?: string;
}

export class ServiceStack extends cdk.Stack {
  public readonly service: ecs.FargateService;
  public readonly taskRole: iam.Role;

  constructor(scope: Construct, id: string, props: ServiceStackProps) {
    super(scope, id, props);

    const env = props.environment;

    // -------------------------------------------------------------------------
    // ECR Repository
    // -------------------------------------------------------------------------
    const repository = new ecr.Repository(this, "BackendRepo", {
      repositoryName: `isol8-${env}-backend`,
      removalPolicy:
        env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: env !== "prod",
      lifecycleRules: [
        {
          maxImageCount: 10,
          description: "Keep last 10 images",
        },
      ],
    });

    // -------------------------------------------------------------------------
    // Docker Image Asset (built & pushed by CDK Pipeline)
    // -------------------------------------------------------------------------
    const backendImage = new DockerImageAsset(this, "BackendImage", {
      directory: path.join(__dirname, "..", "..", "..", "backend"),
      platform: Platform.LINUX_AMD64,
    });

    // -------------------------------------------------------------------------
    // Service Security Group
    // -------------------------------------------------------------------------
    const serviceSg = new ec2.SecurityGroup(this, "ServiceSecurityGroup", {
      vpc: props.vpc,
      description: `Isol8 ${env} Fargate service security group`,
      allowAllOutbound: true,
    });

    // Allow traffic from ALB on port 8000
    serviceSg.addIngressRule(
      props.albSecurityGroup,
      ec2.Port.tcp(8000),
      "HTTP from ALB",
    );

    // Cross-stack security group ingress rules.
    // We use CfnSecurityGroupIngress to avoid circular dependencies between stacks.

    // Allow service to mount EFS (port 2049)
    new ec2.CfnSecurityGroupIngress(this, "EfsFromServiceIngress", {
      groupId: props.container.efsSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 2049,
      toPort: 2049,
      sourceSecurityGroupId: serviceSg.securityGroupId,
      description: "Allow NFS from Fargate service",
    });

    // Allow service to manage Fargate containers (all TCP)
    new ec2.CfnSecurityGroupIngress(this, "ContainerFromServiceIngress", {
      groupId: props.container.containerSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 0,
      toPort: 65535,
      sourceSecurityGroupId: serviceSg.securityGroupId,
      description: "Allow all TCP from Fargate service for container management",
    });

    // -------------------------------------------------------------------------
    // IAM Task Role
    // -------------------------------------------------------------------------
    this.taskRole = new iam.Role(this, "TaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${env} Fargate task role`,
    });

    // ECR pull
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcrAccess",
        actions: [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ],
        resources: ["*"],
      }),
    );

    // ECS management (per-user Fargate tasks)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsManagement",
        actions: [
          "ecs:CreateService",
          "ecs:UpdateService",
          "ecs:DeleteService",
          "ecs:DescribeServices",
          "ecs:DescribeTasks",
          "ecs:ListServices",
          "ecs:ListTasks",
          "ecs:ExecuteCommand",
        ],
        resources: ["*"],
        conditions: {
          ArnEquals: {
            "ecs:cluster": props.container.cluster.clusterArn,
          },
        },
      }),
    );

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsTaskDefinition",
        actions: [
          "ecs:RegisterTaskDefinition",
          "ecs:DeregisterTaskDefinition",
          "ecs:DescribeTaskDefinition",
        ],
        resources: ["*"],
      }),
    );

    // IAM PassRole for ECS task roles (both execution role and task role)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "IamPassRole",
        actions: ["iam:PassRole"],
        resources: [
          props.container.taskExecutionRole.roleArn,
          props.container.taskRole.roleArn,
        ],
      }),
    );

    // Secrets Manager
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SecretsAccess",
        actions: [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:isol8/${env}/*`,
        ],
      }),
    );

    // DynamoDB tables
    props.database.usersTable.grantReadWriteData(this.taskRole);
    props.database.containersTable.grantReadWriteData(this.taskRole);
    props.database.billingTable.grantReadWriteData(this.taskRole);
    props.database.apiKeysTable.grantReadWriteData(this.taskRole);
    props.database.usageCountersTable.grantReadWriteData(this.taskRole);
    props.database.pendingUpdatesTable.grantReadWriteData(this.taskRole);
    props.database.channelLinksTable.grantReadWriteData(this.taskRole);

    // Bedrock
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "BedrockInvoke",
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: [
          "arn:aws:bedrock:*::foundation-model/*",
          `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
          "arn:aws:bedrock:*:*:inference-profile/*",
        ],
      }),
    );

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "BedrockList",
        actions: [
          "bedrock:ListFoundationModels",
          "bedrock:ListInferenceProfiles",
        ],
        resources: ["*"],
      }),
    );

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "Marketplace",
        actions: [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe",
          "aws-marketplace:Unsubscribe",
        ],
        resources: ["*"],
      }),
    );

    // CloudWatch Logs
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudWatchLogs",
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "cloudwatch:PutMetricData",
        ],
        resources: ["*"],
      }),
    );

    // Cloud Map (service discovery) — constrained to namespace + service
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudMapAccess",
        actions: [
          "servicediscovery:RegisterInstance",
          "servicediscovery:DeregisterInstance",
          "servicediscovery:GetNamespace",
          "servicediscovery:GetService",
          "servicediscovery:ListInstances",
        ],
        resources: [
          props.container.cloudMapNamespace.namespaceArn,
          props.container.cloudMapService.serviceArn,
        ],
      }),
    );
    // DiscoverInstances is not resource-scoped — it requires "*"
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudMapDiscover",
        actions: ["servicediscovery:DiscoverInstances"],
        resources: ["*"],
      }),
    );

    // KMS (use string ARN to avoid cross-stack dependency)
    //
    // kms:Encrypt is required so the provision flow can seal per-container
    // secrets (operator device Ed25519 seeds, gateway tokens) before writing
    // them to the containers DynamoDB table. kms:Decrypt is the pre-existing
    // permission for reading them back at handshake time.
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "KmsAccess",
        actions: ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
        resources: [props.kmsKeyArn],
      }),
    );

    // EC2 self-discovery + CloudFormation read
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "Ec2SelfDiscovery",
        actions: [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
          "cloudformation:DescribeStacks",
        ],
        resources: ["*"],
      }),
    );

    // STS
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "StsAccess",
        actions: ["sts:GetCallerIdentity", "sts:AssumeRole"],
        resources: ["*"],
      }),
    );

    // EFS access points management
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EfsAccessPoints",
        actions: [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:CreateAccessPoint",
          "elasticfilesystem:DescribeAccessPoints",
          "elasticfilesystem:TagResource",
        ],
        resources: [props.container.efsFileSystem.fileSystemArn],
      }),
    );

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EfsDeleteAccessPoints",
        actions: [
          "elasticfilesystem:DeleteAccessPoint",
          "elasticfilesystem:TagResource",
        ],
        resources: [
          `arn:aws:elasticfilesystem:*:${this.account}:access-point/*`,
        ],
      }),
    );

    // S3 (OpenClaw config bucket)
    // Per-user path scoping via IAM policy variables (${aws:userid}) is not
    // feasible: aws:userid resolves to the IAM role unique ID, not the app-
    // level Clerk user ID that keys the S3 paths. The bucket is already
    // constrained to isol8-${env}-openclaw-configs so the blast radius is
    // limited to this bucket. Application-level authorization enforces per-
    // user access.
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "S3Access",
        actions: [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ],
        resources: [
          `arn:aws:s3:::isol8-${env}-openclaw-configs`,
          `arn:aws:s3:::isol8-${env}-openclaw-configs/*`,
        ],
      }),
    );

    // WebSocket push (execute-api:ManageConnections)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "WebSocketManageConnections",
        actions: ["execute-api:ManageConnections"],
        resources: [
          `arn:aws:execute-api:${this.region}:${this.account}:${props.wsApiId}/${props.wsStage}/*`,
        ],
      }),
    );

    // SNS (page topic — for backend-initiated alerts like fleet patch audits)
    if (props.alertPageTopicArn) {
      this.taskRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "SnsPublishPageTopic",
          actions: ["sns:Publish"],
          resources: [props.alertPageTopicArn],
        }),
      );
    }

    // DynamoDB CRUD on connections table
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDbConnections",
        actions: [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ],
        resources: [
          `arn:aws:dynamodb:${this.region}:${this.account}:table/${props.connectionsTableName}`,
        ],
      }),
    );

    // -------------------------------------------------------------------------
    // Agent Catalog S3 Bucket
    //
    // Stores published agent bundles (agent.tar.gz + manifest.json) that users
    // can one-click deploy into their own containers. Versioned so we can roll
    // back a bad publish without losing history.
    // -------------------------------------------------------------------------
    const agentCatalogBucket = new s3.Bucket(this, "AgentCatalogBucket", {
      bucketName: `isol8-${env}-agent-catalog`,
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy:
        env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: env !== "prod",
    });

    agentCatalogBucket.grantReadWrite(this.taskRole);

    // -------------------------------------------------------------------------
    // Task Execution Role
    // -------------------------------------------------------------------------
    const taskExecutionRole = new iam.Role(this, "TaskExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${env} Fargate task execution role`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });

    // Allow execution role to pull secrets for container injection
    taskExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SecretsManagerForEcs",
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:isol8/${env}/*`,
        ],
      }),
    );

    // Allow execution role to decrypt secrets encrypted with KMS
    // (manual grant instead of CDK auto-grant to avoid cross-stack cycle)
    taskExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "KmsDecryptForSecrets",
        actions: ["kms:Decrypt"],
        resources: [props.kmsKeyArn],
      }),
    );

    // -------------------------------------------------------------------------
    // Log Group
    // -------------------------------------------------------------------------
    const logGroup = new logs.LogGroup(this, "LogGroup", {
      logGroupName: `/ecs/isol8-${env}`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy:
        env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // -------------------------------------------------------------------------
    // Fargate Task Definition
    // -------------------------------------------------------------------------
    const privateSubnetIds = props.vpc
      .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
      .subnetIds.join(",");

    const taskDef = new ecs.FargateTaskDefinition(this, "TaskDef", {
      family: `isol8-${env}-backend`,
      cpu: env === "prod" ? 2048 : 1024,
      memoryLimitMiB: env === "prod" ? 4096 : 2048,
      taskRole: this.taskRole,
      executionRole: taskExecutionRole,
    });

    // EFS Volume
    taskDef.addVolume({
      name: "efs-users",
      efsVolumeConfiguration: {
        fileSystemId: props.container.efsFileSystem.fileSystemId,
        transitEncryption: "ENABLED",
        authorizationConfig: { iam: "ENABLED" },
      },
    });

    // Container definition
    const container = taskDef.addContainer("backend", {
      image: ecs.ContainerImage.fromDockerImageAsset(backendImage),
      // Run as root — backend writes to EFS user directories
      user: "0:0",
      portMappings: [{ containerPort: 8000 }],
      environment: {
        ENVIRONMENT: env,
        AWS_REGION: "us-east-1",
        WS_MANAGEMENT_API_URL: props.managementApiUrl,
        WS_CONNECTIONS_TABLE: props.connectionsTableName,
        CORS_ORIGINS:
          env === "local"
            ? "http://localhost:3000"
            : env === "prod"
              ? "https://isol8.co"
              : "https://dev.isol8.co",
        FREE_TIER_MODEL: "minimax.minimax-m2.5",
        // Per-container secrets CMK — used by core/crypto/kms_secrets.py to
        // encrypt operator device seeds + gateway tokens at rest. Reuses the
        // same CMK as the BYOK Fernet layer since the blast radius is the same
        // (any principal with kms:Decrypt on this key can read any of them).
        CONTAINER_SECRETS_KMS_KEY_ID: props.kmsKeyArn,
        STRIPE_STARTER_PRICE_ID:
          env === "prod"
            ? "price_1TF5MkI54BysGS3rLYE6K0fZ"
            : "price_1TF5MDI54BysGS3rlT80MMI8",
        STRIPE_PRO_PRICE_ID:
          env === "prod"
            ? "price_1TF5MkI54BysGS3regYBZj6a"
            : "price_1TF5MEI54BysGS3rAxoFnoeX",
        STRIPE_ENTERPRISE_PRICE_ID:
          env === "prod"
            ? "price_1TF5GiI54BysGS3rJ2n5EyNw"
            : "price_1TF5ARI54BysGS3rPkwQYZ6L",
        STRIPE_METERED_PRICE_ID:
          env === "prod"
            ? "price_1TF5HOI54BysGS3r5Jp56FV5"
            : "price_1TBm0fI54BysGS3rrqTaZ5Zz",
        STRIPE_METER_ID:
          env === "prod"
            ? "mtr_61UOTDUyCfar5AIY541I54BysGS3rToW"
            : "mtr_test_61UL9xth9m1qTEaXv41I54BysGS3rJCC",
        FRONTEND_URL:
          env === "local"
            ? "http://localhost:3000"
            : env === "prod"
              ? "https://isol8.co"
              : "https://dev.isol8.co",
        DEBUG: env === "local" ? "true" : "false",
        // LocalStack needs this to redirect boto3 calls inside the ECS container
        ...(env === "local" ? { AWS_ENDPOINT_URL: "http://localhost.localstack.cloud:4566" } : {}),
        BEDROCK_ENABLED: env === "local" ? "false" : "true",
        EFS_MOUNT_PATH: "/mnt/efs/users",
        EFS_FILE_SYSTEM_ID: props.container.efsFileSystem.fileSystemId,
        CONTAINER_EXECUTION_ROLE_ARN:
          props.container.taskExecutionRole.roleArn,
        ECS_CLUSTER_ARN: props.container.cluster.clusterArn,
        // Use the family name (inlined static string) rather than the full
        // revision ARN so we don't create a cross-stack Fn::ImportValue that
        // CFN locks on every task-def bump. The backend's cloner resolves
        // latest-in-family at runtime; per-user clones register into the same
        // family, but access points are always overridden in the clone so no
        // cross-user leakage, and per-user clones inherit the CDK base's env
        // vars so the CLAWHUB_WORKDIR drift PR #299 was reacting to can no
        // longer recur under current code. If we later want the ARN-revision
        // pinning back, route it through an SSM parameter so the value isn't
        // tied to a consumer-imported export.
        ECS_TASK_DEFINITION: `isol8-${env}-openclaw`,
        ECS_SUBNETS: privateSubnetIds,
        ECS_SECURITY_GROUP_ID:
          props.container.containerSecurityGroup.securityGroupId,
        CLOUD_MAP_NAMESPACE_ID:
          props.container.cloudMapNamespace.namespaceId,
        CLOUD_MAP_SERVICE_ID: props.container.cloudMapService.serviceId,
        CLOUD_MAP_SERVICE_ARN: props.container.cloudMapService.serviceArn,
        DYNAMODB_TABLE_PREFIX: `isol8-${env}-`,
        AGENT_CATALOG_BUCKET: agentCatalogBucket.bucketName,
        // Observability: page topic ARN for backend-initiated SNS alerts.
        // Populated after first deploy via Fn.importValue from ObservabilityStack.
        ...(props.alertPageTopicArn
          ? { ALERT_PAGE_TOPIC_ARN: props.alertPageTopicArn }
          : {}),
      },
      secrets: {
        // Import secrets by name (NOT cross-stack ISecret) to avoid CDK
        // auto-granting KMS decrypt on AuthStack's key, which causes a
        // circular dependency: auth -> service -> container -> auth.
        //
        CLERK_ISSUER: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportClerkIssuer", props.secretNames.clerkIssuer),
        ),
        CLERK_SECRET_KEY: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportClerkSecretKey", props.secretNames.clerkSecretKey),
        ),
        STRIPE_SECRET_KEY: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportStripeSecretKey", props.secretNames.stripeSecretKey),
        ),
        STRIPE_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportStripeWebhookSecret", props.secretNames.stripeWebhookSecret),
        ),
        ENCRYPTION_KEY: ecs.Secret.fromSecretsManager(
          secretsmanager.Secret.fromSecretNameV2(this, "ImportEncryptionKey", props.secretNames.encryptionKey),
        ),
      },
      healthCheck: {
        command: [
          "CMD-SHELL",
          "curl -f http://localhost:8000/health || exit 1",
        ],
      },
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "backend",
        logGroup,
      }),
    });

    // EFS mount point
    container.addMountPoints({
      containerPath: "/mnt/efs",
      sourceVolume: "efs-users",
      readOnly: false,
    });

    // -------------------------------------------------------------------------
    // Fargate Service
    // -------------------------------------------------------------------------
    this.service = new ecs.FargateService(this, "Service", {
      cluster: props.container.cluster,
      taskDefinition: taskDef,
      desiredCount: 1,
      circuitBreaker: { rollback: true },
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [serviceSg],
      assignPublicIp: false,
      enableExecuteCommand: true,
    });

    // Register with ALB target group
    this.service.attachToApplicationTargetGroup(props.targetGroup);

    // -------------------------------------------------------------------------
    // Tags
    // -------------------------------------------------------------------------
    cdk.Tags.of(this.service).add("Name", `isol8-${env}-backend`);
    cdk.Tags.of(this.service).add("Project", "isol8");
    cdk.Tags.of(this.service).add("Environment", env);
  }
}
