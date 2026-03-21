import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { DockerImageAsset, Platform } from "aws-cdk-lib/aws-ecr-assets";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";
import { AuthSecrets } from "./auth-stack";

export interface ServiceStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  targetGroup: elbv2.IApplicationTargetGroup;
  albSecurityGroup: ec2.ISecurityGroup;
  database: {
    dbInstance: rds.IDatabaseInstance;
    dbSecurityGroup: ec2.ISecurityGroup;
    dbSecret: secretsmanager.ISecret;
  };
  secrets: AuthSecrets;
  kmsKey: kms.IKey;
  container: {
    cluster: ecs.ICluster;
    cloudMapNamespace: servicediscovery.IPrivateDnsNamespace;
    cloudMapService: servicediscovery.IService;
    efsFileSystem: efs.IFileSystem;
    efsSecurityGroup: ec2.ISecurityGroup;
    containerSecurityGroup: ec2.ISecurityGroup;
    taskExecutionRole: iam.IRole;
    taskRole: iam.IRole;
  };
  managementApiUrl: string;
  connectionsTableName: string;
  wsApiId: string;
  wsStage: string;
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

    // Allow service to connect to database (port 5432)
    new ec2.CfnSecurityGroupIngress(this, "DbFromServiceIngress", {
      groupId: props.database.dbSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      sourceSecurityGroupId: serviceSg.securityGroupId,
      description: "Allow PostgreSQL from Fargate service",
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

    // Also allow access to the RDS auto-generated secret
    props.database.dbSecret.grantRead(this.taskRole);

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

    // Cloud Map (service discovery)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudMapAccess",
        actions: [
          "servicediscovery:RegisterInstance",
          "servicediscovery:DeregisterInstance",
          "servicediscovery:DiscoverInstances",
          "servicediscovery:GetNamespace",
          "servicediscovery:GetService",
          "servicediscovery:ListInstances",
        ],
        resources: ["*"],
      }),
    );

    // KMS
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "KmsAccess",
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: [props.kmsKey.keyArn],
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
      portMappings: [{ containerPort: 8000 }],
      environment: {
        ENVIRONMENT: env,
        AWS_REGION: "us-east-1",
        WS_MANAGEMENT_API_URL: props.managementApiUrl,
        WS_CONNECTIONS_TABLE: props.connectionsTableName,
        CORS_ORIGINS:
          env === "prod" ? "https://isol8.co" : "https://dev.isol8.co",
        STRIPE_STARTER_FIXED_PRICE_ID:
          env === "prod"
            ? "price_TODO_PROD"
            : "price_1TBm0NI54BysGS3r57fcRXOJ",
        STRIPE_PRO_FIXED_PRICE_ID:
          env === "prod"
            ? "price_TODO_PROD"
            : "price_1TBm0PI54BysGS3rFjUOtmrR",
        STRIPE_METERED_PRICE_ID:
          env === "prod"
            ? "price_TODO_PROD"
            : "price_1TBm0fI54BysGS3rrqTaZ5Zz",
        STRIPE_METER_ID:
          env === "prod"
            ? "mtr_TODO_PROD"
            : "mtr_test_61UL9xth9m1qTEaXv41I54BysGS3rJCC",
        FRONTEND_URL:
          env === "prod" ? "https://isol8.co" : "https://dev.isol8.co",
        PROXY_BASE_URL:
          env === "prod"
            ? "https://api.isol8.co/api/v1/proxy"
            : `https://api-${env}-isol8.co/api/v1/proxy`,
        DEBUG: "false",
        EFS_MOUNT_PATH: "/mnt/efs/users",
        EFS_FILE_SYSTEM_ID: props.container.efsFileSystem.fileSystemId,
        CONTAINER_EXECUTION_ROLE_ARN:
          props.container.taskExecutionRole.roleArn,
        ECS_CLUSTER_ARN: props.container.cluster.clusterArn,
        ECS_TASK_DEFINITION: `isol8-${env}-openclaw`,
        ECS_SUBNETS: privateSubnetIds,
        ECS_SECURITY_GROUP_ID:
          props.container.containerSecurityGroup.securityGroupId,
        CLOUD_MAP_NAMESPACE_ID:
          props.container.cloudMapNamespace.namespaceId,
        CLOUD_MAP_SERVICE_ID: props.container.cloudMapService.serviceId,
        CLOUD_MAP_SERVICE_ARN: props.container.cloudMapService.serviceArn,
      },
      secrets: {
        DATABASE_URL: ecs.Secret.fromSecretsManager(props.secrets.databaseUrl),
        CLERK_ISSUER: ecs.Secret.fromSecretsManager(props.secrets.clerkIssuer),
        CLERK_SECRET_KEY: ecs.Secret.fromSecretsManager(
          props.secrets.clerkSecretKey,
        ),
        CLERK_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(
          props.secrets.clerkWebhookSecret,
        ),
        STRIPE_SECRET_KEY: ecs.Secret.fromSecretsManager(
          props.secrets.stripeSecretKey,
        ),
        STRIPE_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(
          props.secrets.stripeWebhookSecret,
        ),
        PERPLEXITY_API_KEY: ecs.Secret.fromSecretsManager(
          props.secrets.perplexityApiKey,
        ),
        ENCRYPTION_KEY: ecs.Secret.fromSecretsManager(
          props.secrets.encryptionKey,
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
      desiredCount: env === "prod" ? 2 : 1,
      circuitBreaker: { rollback: true },
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [serviceSg],
      assignPublicIp: false,
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
