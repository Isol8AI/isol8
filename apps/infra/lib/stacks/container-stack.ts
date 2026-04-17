import * as path from "path";
import * as fs from "fs";
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";

// Single source of truth for the pinned OpenClaw container image.
// Bump openclaw-version.json at the repo root to upgrade.
type OpenClawVersionConfig = {
  upstream: string;
  image: string;
  tag: string;
  full: string;
  extendedImage: string;
  dev: { tag: string };
  prod: { tag: string };
  notes?: string;
};
const OPENCLAW_VERSION: OpenClawVersionConfig = JSON.parse(
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
  public readonly openclawExtendedRepo: ecr.IRepository;

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

    // ECS Exec — lets us aws ecs execute-command into per-user OpenClaw
    // containers for live debugging (skill installs, workspace state, etc.).
    // Paired with enableExecuteCommand=true on each per-user service in
    // ecs_manager.py.
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ],
        resources: ["*"],
      }),
    );

    // Extended OpenClaw image — built and pushed by
    // .github/workflows/build-openclaw-image.yml. Per-env tags live in
    // openclaw-version.json (extendedImage + dev.tag/prod.tag). After the
    // extended-image migration completes, this stack reads the env-appropriate
    // tag and uses it as the per-user container image.
    //
    // The repository is account-scoped, so we create it only in the dev stack
    // and reference it by name in prod. This keeps a single source of truth
    // for image tags (one ECR repo, two env-tagged image references).
    //
    // Initialized BEFORE the container task def so the image-selection
    // expression below can dereference it.
    if (props.environment === "dev") {
      const repo = new ecr.Repository(this, "OpenclawExtendedRepo", {
        repositoryName: "isol8/openclaw-extended",
        imageScanOnPush: true,
        imageTagMutability: ecr.TagMutability.IMMUTABLE,
        lifecycleRules: [
          {
            description: "Keep the most recent 30 images",
            maxImageCount: 30,
          },
        ],
        // The repo holds prod-deployed images even when the dev infra stack
        // gets torn down for redeploy — RETAIN to avoid losing image history.
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });
      this.openclawExtendedRepo = repo;

      // OIDC role for the build-openclaw-image workflow. Scoped to this repo
      // so the existing isol8-dev-github-actions role (which only has
      // sts:AssumeRole on cdk-* roles) doesn't need broader ECR perms.
      const oidcProviderArn = `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`;
      const oidcProvider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
        this,
        "GithubOidcProvider",
        oidcProviderArn,
      );
      const builderRole = new iam.Role(this, "OpenclawImageBuilderRole", {
        roleName: "isol8-openclaw-image-builder",
        assumedBy: new iam.OpenIdConnectPrincipal(oidcProvider, {
          StringLike: {
            "token.actions.githubusercontent.com:sub": "repo:Isol8AI/isol8:*",
          },
          StringEquals: {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          },
        }),
        description: "Used by .github/workflows/build-openclaw-image.yml to push to ECR",
        maxSessionDuration: cdk.Duration.minutes(60),
      });
      builderRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["ecr:GetAuthorizationToken"],
          resources: ["*"],
        }),
      );
      repo.grantPullPush(builderRole);
    } else {
      // Prod (and any non-dev env) references the same repo by name.
      this.openclawExtendedRepo = ecr.Repository.fromRepositoryName(
        this,
        "OpenclawExtendedRepo",
        "isol8/openclaw-extended",
      );
    }

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

    // Startup command — almost everything (apt packages, pip, npm globals,
    // gh, uv) is now baked into the extended OpenClaw image. We only:
    //   1. Install markdown-converter via clawhub (lives at clawhub.com,
    //      not bundled in the image — landing dir comes from
    //      CLAWHUB_WORKDIR=/home/node/.openclaw, set as a container env var).
    //   2. Launch the gateway.
    // Cold-start drops from ~30s to ~5s.
    const startupCommand = [
      "clawhub install markdown-converter --no-input 2>/dev/null",
      "exec node /app/openclaw.mjs gateway --port 18789 --bind lan",
    ].join("; ");

    // Image selection: use the extended ECR image once the per-env tag has been
    // promoted past the "bootstrap" placeholder. Until then, fall back to the
    // legacy upstream image so the env keeps deploying. This lets us flip dev
    // and prod independently via openclaw-version.json bumps without coupling.
    // Unknown envs (e.g. "local") default to legacy via the optional chain.
    const envCfg =
      props.environment === "dev" || props.environment === "prod"
        ? OPENCLAW_VERSION[props.environment]
        : undefined;
    const envTag = envCfg?.tag ?? "bootstrap";
    const containerImage =
      envTag === "bootstrap"
        ? ecs.ContainerImage.fromRegistry(OPENCLAW_VERSION.full)
        : ecs.ContainerImage.fromEcrRepository(this.openclawExtendedRepo, envTag);

    const openclawContainer = openclawTaskDef.addContainer("openclaw", {
      image: containerImage,
      essential: true,
      command: ["sh", "-c", startupCommand],
      user: "0:0",
      workingDirectory: "/home/node",
      environment: {
        HOME: "/home/node",
        CHOKIDAR_USEPOLLING: "true",
        // Redirect clawhub installs to the OpenClaw managed-skills directory
        // (~/.openclaw/skills) so they're scanned by every agent. Without
        // this, clawhub falls through to agents.defaults.workspace and lands
        // at /home/node/.openclaw/workspaces/skills — a path no scanner checks.
        CLAWHUB_WORKDIR: "/home/node/.openclaw",
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
