import * as path from "path";
import * as fs from "fs";
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";

// Single source of truth for the pinned OpenClaw container image.
// Bump openclaw-version.json at the repo root to upgrade.
const OPENCLAW_VERSION: { full: string; image: string; tag: string } = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "..", "..", "openclaw-version.json"), "utf8"),
);

export interface ContainerStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  /** Pass as string ARN to avoid cross-stack dependency cycle. */
  kmsKeyArn: string;
}

const ENV_CONFIG: Record<
  string,
  { removalPolicy: cdk.RemovalPolicy }
> = {
  dev: { removalPolicy: cdk.RemovalPolicy.DESTROY },
  prod: { removalPolicy: cdk.RemovalPolicy.RETAIN },
};

export class ContainerStack extends cdk.Stack {
  public readonly cluster: ecs.Cluster;
  public readonly cloudMapNamespace: servicediscovery.PrivateDnsNamespace;
  public readonly cloudMapService: servicediscovery.Service;
  public readonly efsFileSystem: efs.FileSystem;
  public readonly efsSecurityGroup: ec2.SecurityGroup;
  public readonly containerSecurityGroup: ec2.SecurityGroup;
  public readonly taskExecutionRole: iam.Role;
  public readonly taskRole: iam.Role;

  constructor(scope: Construct, id: string, props: ContainerStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;

    // Import KMS key by ARN to avoid cross-stack dependency cycle
    const kmsKey = kms.Key.fromKeyArn(this, "ImportedKmsKey", props.kmsKeyArn);

    // ECS Fargate cluster — Container Insights disabled to avoid per-service
    // metric explosion (~15 metrics × N user containers = thousands of
    // CloudWatch metric streams).  We use AWS/ECS standard metrics
    // (CPUUtilization, MemoryUtilization) for the backend service alarms
    // and custom EMF metrics for everything else.
    this.cluster = new ecs.Cluster(this, "Cluster", {
      vpc: props.vpc,
      containerInsights: false,
    });

    // Cloud Map private DNS namespace
    this.cloudMapNamespace = new servicediscovery.PrivateDnsNamespace(
      this,
      "Namespace",
      {
        name: `isol8-${props.environment}.local`,
        vpc: props.vpc,
        description: `Isol8 ${props.environment} service discovery namespace`,
      },
    );

    // Cloud Map service for container registration
    this.cloudMapService = this.cloudMapNamespace.createService(
      "ContainerService",
      {
        dnsRecordType: servicediscovery.DnsRecordType.A,
        dnsTtl: cdk.Duration.seconds(10),
        description: `Isol8 ${props.environment} container service discovery`,
      },
    );

    // EFS security group
    this.efsSecurityGroup = new ec2.SecurityGroup(this, "EfsSecurityGroup", {
      vpc: props.vpc,
      description: `Isol8 ${props.environment} EFS security group`,
      allowAllOutbound: false,
    });

    // EFS filesystem
    this.efsFileSystem = new efs.FileSystem(this, "FileSystem", {
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroup: this.efsSecurityGroup,
      encrypted: true,
      kmsKey,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,
      removalPolicy: config.removalPolicy,
    });

    // Container (Fargate task) security group
    this.containerSecurityGroup = new ec2.SecurityGroup(
      this,
      "ContainerSecurityGroup",
      {
        vpc: props.vpc,
        description: `Isol8 ${props.environment} Fargate container security group`,
        allowAllOutbound: true,
      },
    );

    // Allow containers to mount EFS
    this.efsSecurityGroup.addIngressRule(
      this.containerSecurityGroup,
      ec2.Port.tcp(2049),
      "Allow NFS from Fargate containers",
    );

    // ECS task execution role (used by ECS agent)
    this.taskExecutionRole = new iam.Role(this, "TaskExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${props.environment} ECS task execution role`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });

    this.taskExecutionRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "secretsmanager:GetSecretValue",
        ],
        resources: ["*"],
      }),
    );

    // ECS task role (used by the container itself)
    this.taskRole = new iam.Role(this, "TaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${props.environment} ECS task role`,
    });

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: ["*"],
      }),
    );

    // EFS client access — required for IAM-authenticated EFS mounts
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess",
        ],
        resources: ["*"],
      }),
    );

    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ],
        resources: ["*"],
      }),
    );

    // Base OpenClaw task definition — the backend clones this per user,
    // replacing the EFS access point for data isolation.
    const env = props.environment;
    const openclawLogGroup = new cdk.aws_logs.LogGroup(this, "OpenClawLogGroup", {
      logGroupName: `/isol8/${env}/openclaw`,
      retention: cdk.aws_logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const openclawTaskDef = new ecs.FargateTaskDefinition(this, "OpenClawTaskDef", {
      family: `isol8-${env}-openclaw`,
      cpu: 1024,
      memoryLimitMiB: 2048,
      taskRole: this.taskRole,
      executionRole: this.taskExecutionRole,
    });

    // Startup command installs runtime dependencies before launching the
    // OpenClaw gateway.  Mirrors the Terraform task definition in
    // apps/terraform/modules/ecs/main.tf so both infra paths stay in sync.
    const startupCommand = [
      // System packages
      "apt-get update -qq && apt-get install -y -qq socat python3-pip sqlite3 build-essential python3 > /dev/null 2>&1",
      "pip install --break-system-packages websockets > /dev/null 2>&1",
      // npm global prefix + PATH for the node user
      "export NPM_CONFIG_PREFIX=/home/node/.npm-global && export PATH=$NPM_CONFIG_PREFIX/bin:$PATH",
      // npm packages: MCP bridge, skill hub, OpenAI compat, QMD memory backend
      "npm i -g --ignore-scripts mcporter clawhub openai 2>/dev/null",
      "npm i -g @tobilu/qmd 2>/dev/null",
      // GitHub CLI
      'GH_VER=2.65.0 && wget -qO- https://github.com/cli/cli/releases/download/v${GH_VER}/gh_${GH_VER}_linux_amd64.tar.gz | tar xz -C /tmp && cp /tmp/gh_${GH_VER}_linux_amd64/bin/gh $NPM_CONFIG_PREFIX/bin/gh 2>/dev/null',
      // uv (Python package manager)
      "wget -qO- https://astral.sh/uv/install.sh | HOME=/home/node sh 2>/dev/null && export PATH=/home/node/.local/bin:$PATH",
      // Bundled skills
      "clawhub install markdown-converter --no-input 2>/dev/null",
      // Launch gateway
      "exec node /app/openclaw.mjs gateway --port 18789 --bind lan",
    ].join("; ");

    const openclawContainer = openclawTaskDef.addContainer("openclaw", {
      image: ecs.ContainerImage.fromRegistry(OPENCLAW_VERSION.full),
      essential: true,
      command: ["sh", "-c", startupCommand],
      user: "0:0",
      workingDirectory: "/home/node",
      environment: {
        HOME: "/home/node",
        CHOKIDAR_USEPOLLING: "true",
      },
      portMappings: [{ containerPort: 18789, protocol: ecs.Protocol.TCP }],
      logging: ecs.LogDrivers.awsLogs({
        logGroup: openclawLogGroup,
        streamPrefix: "openclaw",
      }),
    });

    // Mount EFS workspace — OpenClaw reads openclaw.json and agent files from here
    openclawContainer.addMountPoints({
      containerPath: "/home/node/.openclaw",
      sourceVolume: "openclaw-workspace",
      readOnly: false,
    });

    // Add EFS volume — the backend replaces the access point per user
    openclawTaskDef.addVolume({
      name: "openclaw-workspace",
      efsVolumeConfiguration: {
        fileSystemId: this.efsFileSystem.fileSystemId,
        transitEncryption: "ENABLED",
        authorizationConfig: { iam: "ENABLED" },
      },
    });
  }
}
