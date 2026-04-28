import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";

/**
 * PaperclipStack — runs the upstream `paperclipai/paperclip:latest` Docker
 * image as a single Fargate service inside the Isol8 VPC.
 *
 * Reachability: the FastAPI backend talks to Paperclip over Cloud Map
 * service discovery. The service registers as `paperclip` inside the
 * existing private DNS namespace (`isol8-${env}.local`) created by
 * ContainerStack — same pattern OpenClaw containers use. Backend resolves
 * `http://paperclip.isol8-${env}.local:3100/`.
 *
 * Why Cloud Map and not an internal ALB listener?
 *  - The repo's NetworkStack only exposes a single public ALB (HTTP+HTTPS
 *    listeners on isol8.co / dev.isol8.co). Adding an "internal" listener
 *    would require new SG rules + a private Route 53 record, neither of
 *    which exist today.
 *  - Cloud Map is already the canonical service-discovery surface for the
 *    fleet (OpenClaw containers), which keeps T14's proxy router code
 *    consistent across providers.
 *  - The public host route (`company.isol8.co` → Paperclip) is wired in T6
 *    on the existing public ALB and is independent of how FastAPI reaches
 *    Paperclip internally.
 *
 * Cross-stack KMS posture: AuthStack's BetterAuth secret is encrypted with
 * the shared CMK. We import it by *name* (NOT ISecret) to avoid the same
 * cross-stack auto-grant cycle that service-stack.ts mitigates with
 * `secretNames`. The Aurora cluster's master secret is owned by
 * DatabaseStack and reaches us via `props.paperclipDbCluster.secret`,
 * which is fine because there is no ambient KMS dependency on AuthStack.
 */
export interface PaperclipStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  cluster: ecs.ICluster;
  /** Cloud Map private DNS namespace owned by ContainerStack. */
  cloudMapNamespace: servicediscovery.IPrivateDnsNamespace;
  /**
   * Concrete cluster (not IDatabaseCluster) — we read `.secret` to wire
   * PGPASSWORD, and that property only exists on the concrete base class
   * `DatabaseClusterBase` exposed by `rds.DatabaseCluster`.
   */
  paperclipDbCluster: rds.DatabaseCluster;
  paperclipDbSecurityGroup: ec2.ISecurityGroup;
  /**
   * Pass the secret *name* (not an ISecret) to avoid CDK auto-granting
   * KMS decrypt on AuthStack's CMK, which would create a cross-stack
   * dependency cycle. Same pattern as service-stack.ts.
   */
  paperclipBetterAuthSecretName: string;
}

export class PaperclipStack extends cdk.Stack {
  public readonly service: ecs.FargateService;
  // T14 NOTE: T14's proxy router must add an ingress rule on this SG
  // allowing port 3100 from FastAPI's service SG. PaperclipStack
  // deliberately does NOT open ingress here — it doesn't have FastAPI's
  // SG handle, and granting it would create a cross-stack SG cycle.
  // T14 should add the rule from the service stack side using
  // `ec2.CfnSecurityGroupIngress` (matching the Aurora-from-Paperclip
  // pattern below) once it has both SG IDs in scope.
  public readonly taskSecurityGroup: ec2.SecurityGroup;
  /**
   * Internal URL FastAPI uses to reach Paperclip (T14 reads this).
   *
   * T14 NOTE: this URL resolves via Cloud Map A records with a 10-second
   * TTL (see `cloudMapOptions` on the FargateService below). During
   * rolling ECS deploys, task IPs change, so T14's HTTP client MUST NOT
   * cache DNS forever. With `aiohttp`, use
   * `aiohttp.TCPConnector(ttl_dns_cache=10)` (or `use_dns_cache=False`).
   * With `httpx`, ensure no Python-layer DNS cache is wrapping the client
   * — httpx itself doesn't cache DNS, but a custom transport might.
   */
  public readonly internalUrl: string;

  constructor(scope: Construct, id: string, props: PaperclipStackProps) {
    super(scope, id, props);

    const env = props.environment;

    // ─────────────────────────────────────────────────────────────────
    // Log group
    // ─────────────────────────────────────────────────────────────────
    const logGroup = new logs.LogGroup(this, "PaperclipLogs", {
      logGroupName: `/isol8/${env}/paperclip`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy:
        env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // ─────────────────────────────────────────────────────────────────
    // Task security group
    // Egress is open (Aurora + Secrets Manager + ECR + CloudWatch).
    // Ingress is granted by T6 (public ALB host rule for company.isol8.co)
    // and by Cloud Map peers (FastAPI backend SG → Paperclip:3100). We add
    // the FastAPI ingress in T14 / future wiring; nothing else has the
    // SG handle today, so leaving that to the consumer keeps blast radius
    // tight.
    // ─────────────────────────────────────────────────────────────────
    this.taskSecurityGroup = new ec2.SecurityGroup(this, "PaperclipTaskSg", {
      vpc: props.vpc,
      description: `Isol8 ${env} Paperclip task SG — Aurora egress + ALB/FastAPI ingress`,
      allowAllOutbound: true,
    });

    // Aurora ingress: the Paperclip task must reach Postgres on 5432.
    // Use CfnSecurityGroupIngress (NOT addIngressRule) for the same reason
    // service-stack.ts does — addIngressRule on a cross-stack SG creates
    // mutual Refs that CDK reports as a cyclic stack dependency. The Cfn
    // form takes raw IDs and emits a single-direction reference.
    new ec2.CfnSecurityGroupIngress(this, "AuroraFromPaperclipIngress", {
      groupId: props.paperclipDbSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      sourceSecurityGroupId: this.taskSecurityGroup.securityGroupId,
      description: "Paperclip task → Aurora",
    });

    // ─────────────────────────────────────────────────────────────────
    // IAM: task execution role (ECR pull + CloudWatch + secrets fetch)
    // ─────────────────────────────────────────────────────────────────
    const executionRole = new iam.Role(this, "PaperclipTaskExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${env} Paperclip Fargate task execution role`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });

    // Grant secret read for the two we hand to the container. Scoped
    // tightly to the secret ARNs we actually consume — no `isol8/${env}/*`
    // wildcard.
    executionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "PaperclipExecutionSecretsRead",
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:isol8/${env}/paperclip_better_auth_secret-*`,
          // Aurora's master secret is named "isol8-${env}-paperclip-db-credentials"
          // (see database-stack.ts), generated under the AWS-managed prefix.
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:isol8-${env}-paperclip-db-credentials-*`,
        ],
      }),
    );

    // ─────────────────────────────────────────────────────────────────
    // IAM: task role (the container itself; Paperclip doesn't call AWS
    // APIs in normal operation, so this stays minimal — log writes only)
    // ─────────────────────────────────────────────────────────────────
    const taskRole = new iam.Role(this, "PaperclipTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Isol8 ${env} Paperclip Fargate task role`,
    });
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "PaperclipCloudWatchLogs",
        actions: [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ],
        resources: [logGroup.logGroupArn],
      }),
    );

    // ─────────────────────────────────────────────────────────────────
    // Task definition: 0.5 vCPU / 1 GB Fargate, upstream image
    // ─────────────────────────────────────────────────────────────────
    const taskDefinition = new ecs.FargateTaskDefinition(this, "PaperclipTaskDef", {
      family: `isol8-${env}-paperclip-server`,
      cpu: 512,
      memoryLimitMiB: 1024,
      executionRole,
      taskRole,
    });

    // Aurora cluster's CDK-managed master secret. Required for PGPASSWORD.
    const dbCredsSecret = props.paperclipDbCluster.secret;
    if (!dbCredsSecret) {
      throw new Error(
        "PaperclipStack: paperclipDbCluster.secret is undefined; " +
          "DatabaseStack must use rds.Credentials.fromGeneratedSecret(...) " +
          "(see database-stack.ts: paperclip Aurora wiring).",
      );
    }

    // Import BetterAuth secret by name to avoid cross-stack KMS auto-grant.
    const betterAuthSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      "PaperclipBetterAuthSecretRef",
      props.paperclipBetterAuthSecretName,
    );

    // Public URL for Paperclip's own deployment-mode banner / OAuth callback
    // shape. Maps to T6's host rule on the public ALB.
    const paperclipPublicUrl =
      env === "prod"
        ? "https://company.isol8.co"
        : `https://company-${env}.isol8.co`;

    taskDefinition.addContainer("paperclip", {
      image: ecs.ContainerImage.fromRegistry("paperclipai/paperclip:latest"),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "paperclip",
        logGroup,
      }),
      environment: {
        PORT: "3100",
        PAPERCLIP_DEPLOYMENT_MODE: "authenticated",
        PAPERCLIP_DEPLOYMENT_EXPOSURE: "public",
        PAPERCLIP_PUBLIC_URL: paperclipPublicUrl,
        // Critical: blocks public sign-up on company.isol8.co. Provisioning
        // happens server-side via Board API keys (see paperclip-rebuild
        // spec §4 — admin Board API key flow).
        PAPERCLIP_AUTH_DISABLE_SIGN_UP: "true",
        PAPERCLIP_BIND: "lan",
        // Postgres connection split: host/port/user/db at synth time;
        // password injected from Secrets Manager at runtime. The entrypoint
        // shim assembles DATABASE_URL from these so we never have to hold
        // a constructed URL in plaintext at synth time.
        PGHOST: props.paperclipDbCluster.clusterEndpoint.hostname,
        PGPORT: "5432",
        PGUSER: "paperclip_admin",
        PGDATABASE: "paperclip",
      },
      secrets: {
        // Aurora's generated secret has top-level fields {username, password,
        // host, port, dbname, dbClusterIdentifier, engine}. Pull just the
        // password — we already baked the rest into env above.
        PGPASSWORD: ecs.Secret.fromSecretsManager(dbCredsSecret, "password"),
        BETTER_AUTH_SECRET: ecs.Secret.fromSecretsManager(betterAuthSecret),
      },
      // Paperclip's image entrypoint expects DATABASE_URL. The shim below
      // assembles it from PG* env at container start, then exec's the same
      // boot command upstream `docker-entrypoint.sh` runs. Verified against
      // upstream Dockerfile + spec §8 discovery note.
      //
      // PGPASSWORD is URL-encoded via Node's `encodeURIComponent` before
      // interpolation: RDS-generated passwords routinely contain
      // url-special characters (`/`, `+`, `=`, `@`, `:`) that break
      // Postgres URL parsing. Node is already in the image — the
      // entrypoint runs `node server/dist/index.js` — so this adds no
      // new dependency.
      command: [
        "/bin/sh",
        "-c",
        "PGPASSWORD_ENC=$(node -e 'process.stdout.write(encodeURIComponent(process.env.PGPASSWORD))') && export DATABASE_URL=\"postgres://${PGUSER}:${PGPASSWORD_ENC}@${PGHOST}:${PGPORT}/${PGDATABASE}\" && exec docker-entrypoint.sh node --import ./server/node_modules/tsx/dist/loader.mjs server/dist/index.js",
      ],
      healthCheck: {
        command: [
          "CMD-SHELL",
          "curl -fsS http://localhost:3100/api/health || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
      portMappings: [
        // `name` is required when using ECS Service Connect / Cloud Map
        // discovery — Cloud Map publishes A records that resolve to the
        // task ENI; the named port mapping is what the SDK ties the
        // discovery entry to.
        { containerPort: 3100, protocol: ecs.Protocol.TCP, name: "http" },
      ],
    });

    // ─────────────────────────────────────────────────────────────────
    // Fargate service
    //
    // Cloud Map registration: we use `cloudMapOptions` on the FargateService
    // (matching the OpenClaw fleet pattern). This is the single canonical
    // registration of `paperclip` inside the private namespace owned by
    // ContainerStack — declaring a standalone `servicediscovery.Service`
    // on the side would collide on the namespace Name and fail at first
    // deploy.
    // ─────────────────────────────────────────────────────────────────
    this.service = new ecs.FargateService(this, "PaperclipService", {
      cluster: props.cluster,
      taskDefinition,
      serviceName: `isol8-${env}-paperclip-server`,
      desiredCount: 1,
      securityGroups: [this.taskSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      assignPublicIp: false,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      enableExecuteCommand: true,
      cloudMapOptions: {
        cloudMapNamespace: props.cloudMapNamespace,
        name: "paperclip",
        dnsRecordType: servicediscovery.DnsRecordType.A,
        dnsTtl: cdk.Duration.seconds(10),
      },
    });

    // Autoscale on CPU 70%, 1–4 tasks. Per spec §3.3.
    const scaling = this.service.autoScaleTaskCount({
      minCapacity: 1,
      maxCapacity: 4,
    });
    scaling.scaleOnCpuUtilization("PaperclipCpuScaling", {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.minutes(5),
      scaleOutCooldown: cdk.Duration.minutes(2),
    });

    // ─────────────────────────────────────────────────────────────────
    // Internal URL: FastAPI uses this to reach Paperclip (T14).
    //
    // The FargateService.cloudMapOptions block above publishes
    // `paperclip.<namespace>` A records pointing at task ENI IPs.
    // Service Connect / Cloud Map A records always resolve to the
    // container port directly — no separate target group needed.
    // ─────────────────────────────────────────────────────────────────
    this.internalUrl = `http://paperclip.${props.cloudMapNamespace.namespaceName}:3100`;

    new cdk.CfnOutput(this, "PaperclipInternalUrl", {
      value: this.internalUrl,
      description:
        "Internal URL FastAPI uses to reach Paperclip via Cloud Map",
      exportName: `isol8-${env}-paperclip-internal-url`,
    });

    new cdk.CfnOutput(this, "PaperclipTaskSecurityGroupId", {
      value: this.taskSecurityGroup.securityGroupId,
      description:
        "Paperclip task SG — granted ingress by T6 (ALB) and FastAPI peer",
      exportName: `isol8-${env}-paperclip-task-sg`,
    });

    // Tags
    cdk.Tags.of(this).add("Project", "isol8");
    cdk.Tags.of(this).add("Environment", env);
    cdk.Tags.of(this).add("Component", "paperclip");
  }
}
