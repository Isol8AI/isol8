import * as fs from "fs";
import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as autoscaling from "aws-cdk-lib/aws-autoscaling";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { DockerImageAsset, Platform } from "aws-cdk-lib/aws-ecr-assets";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Construct } from "constructs";
import { AuthSecrets } from "./auth-stack";

export interface ComputeStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  database: {
    dbInstance: rds.IDatabaseInstance;
    dbSecurityGroup: ec2.ISecurityGroup;
    dbSecret: secretsmanager.ISecret;
  };
  secrets: AuthSecrets;
  kmsKey: kms.IKey;
  certificate: acm.ICertificate;
  container: {
    cluster: ecs.ICluster;
    cloudMapNamespace: servicediscovery.IPrivateDnsNamespace;
    cloudMapService: servicediscovery.IService;
    efsFileSystem: efs.IFileSystem;
    efsSecurityGroup: ec2.ISecurityGroup;
    containerSecurityGroup: ec2.ISecurityGroup;
    taskExecutionRole: iam.IRole;
  };
}

const ENV_CONFIG: Record<
  string,
  {
    instanceType: ec2.InstanceType;
    minCapacity: number;
    desiredCapacity: number;
    maxCapacity: number;
  }
> = {
  dev: {
    instanceType: ec2.InstanceType.of(
      ec2.InstanceClass.T3,
      ec2.InstanceSize.LARGE,
    ),
    minCapacity: 1,
    desiredCapacity: 1,
    maxCapacity: 2,
  },
  prod: {
    instanceType: ec2.InstanceType.of(
      ec2.InstanceClass.T3,
      ec2.InstanceSize.LARGE,
    ),
    minCapacity: 1,
    desiredCapacity: 1,
    maxCapacity: 3,
  },
};

export class ComputeStack extends cdk.Stack {
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly albSecurityGroup: ec2.SecurityGroup;
  public readonly albHttpListenerArn: string;
  public readonly albHttpsListenerArn: string;
  public readonly nlb: elbv2.NetworkLoadBalancer;
  public readonly nlbDnsName: string;
  public readonly asg: autoscaling.AutoScalingGroup;
  public readonly repository: ecr.Repository;
  public readonly ec2SecurityGroup: ec2.SecurityGroup;
  public readonly ec2Role: iam.Role;

  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;
    const env = props.environment;

    // -------------------------------------------------------------------------
    // ECR Repository
    // -------------------------------------------------------------------------
    this.repository = new ecr.Repository(this, "BackendRepo", {
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
    // EC2 Security Group
    // -------------------------------------------------------------------------
    this.ec2SecurityGroup = new ec2.SecurityGroup(this, "Ec2SecurityGroup", {
      vpc: props.vpc,
      description: `Isol8 ${env} EC2 instances security group`,
      allowAllOutbound: true,
    });

    // -------------------------------------------------------------------------
    // ALB
    // -------------------------------------------------------------------------
    this.albSecurityGroup = new ec2.SecurityGroup(this, "AlbSecurityGroup", {
      vpc: props.vpc,
      description: `Isol8 ${env} internal ALB security group`,
      allowAllOutbound: true,
    });

    // ALB accepts traffic from within VPC (API Gateway VPC Link)
    this.albSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "HTTPS from VPC (API Gateway)",
    );
    this.albSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(80),
      "HTTP from VPC (API Gateway)",
    );

    this.alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      vpc: props.vpc,
      internetFacing: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroup: this.albSecurityGroup,
      idleTimeout: cdk.Duration.seconds(300),
      deletionProtection: env === "prod",
    });

    // Target group
    const targetGroup = new elbv2.ApplicationTargetGroup(this, "TargetGroup", {
      vpc: props.vpc,
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.INSTANCE,
      healthCheck: {
        path: "/health",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
        timeout: cdk.Duration.seconds(10),
        healthyHttpCodes: "200",
      },
      stickinessCookieDuration: cdk.Duration.hours(1),
    });

    // HTTPS listener
    const httpsListener = this.alb.addListener("HttpsListener", {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [props.certificate],
      sslPolicy: elbv2.SslPolicy.TLS13_RES,
      defaultTargetGroups: [targetGroup],
    });

    // HTTP listener — forwards to target group
    // API Gateway VPC Link sends plain HTTP internally (API GW handles public TLS)
    const httpListener = this.alb.addListener("HttpListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    this.albHttpListenerArn = httpListener.listenerArn;
    this.albHttpsListenerArn = httpsListener.listenerArn;

    // -------------------------------------------------------------------------
    // EC2 Security Group ingress rules
    // -------------------------------------------------------------------------

    // Allow traffic from ALB on port 8000
    this.ec2SecurityGroup.addIngressRule(
      this.albSecurityGroup,
      ec2.Port.tcp(8000),
      "HTTP from ALB",
    );

    // Allow traffic from VPC CIDR on port 8000 (for NLB — NLB doesn't use SGs)
    this.ec2SecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(8000),
      "WebSocket from NLB (VPC CIDR)",
    );

    // Cross-stack security group ingress rules.
    // We use CfnSecurityGroupIngress to avoid circular dependencies between stacks.

    // Allow EC2 to mount EFS (port 2049)
    new ec2.CfnSecurityGroupIngress(this, "EfsFromEc2Ingress", {
      groupId: props.container.efsSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 2049,
      toPort: 2049,
      sourceSecurityGroupId: this.ec2SecurityGroup.securityGroupId,
      description: "Allow NFS from EC2 instances",
    });

    // Allow EC2 to manage Fargate containers (all TCP)
    new ec2.CfnSecurityGroupIngress(this, "ContainerFromEc2Ingress", {
      groupId: props.container.containerSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 0,
      toPort: 65535,
      sourceSecurityGroupId: this.ec2SecurityGroup.securityGroupId,
      description: "Allow all TCP from EC2 for container management",
    });

    // Allow EC2 to connect to database (port 5432)
    new ec2.CfnSecurityGroupIngress(this, "DbFromEc2Ingress", {
      groupId: props.database.dbSecurityGroup.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      sourceSecurityGroupId: this.ec2SecurityGroup.securityGroupId,
      description: "Allow PostgreSQL from EC2 instances",
    });

    // -------------------------------------------------------------------------
    // IAM Role for EC2 instances
    // -------------------------------------------------------------------------
    this.ec2Role = new iam.Role(this, "Ec2Role", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
      description: `Isol8 ${env} EC2 instance role`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "AmazonSSMManagedInstanceCore",
        ),
      ],
    });

    // ECR pull
    this.ec2Role.addToPolicy(
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
    this.ec2Role.addToPolicy(
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

    this.ec2Role.addToPolicy(
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

    // IAM PassRole for ECS task roles
    this.ec2Role.addToPolicy(
      new iam.PolicyStatement({
        sid: "IamPassRole",
        actions: ["iam:PassRole"],
        resources: [props.container.taskExecutionRole.roleArn],
      }),
    );

    // Secrets Manager
    this.ec2Role.addToPolicy(
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
    props.database.dbSecret.grantRead(this.ec2Role);

    // Bedrock
    this.ec2Role.addToPolicy(
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

    this.ec2Role.addToPolicy(
      new iam.PolicyStatement({
        sid: "BedrockList",
        actions: [
          "bedrock:ListFoundationModels",
          "bedrock:ListInferenceProfiles",
        ],
        resources: ["*"],
      }),
    );

    this.ec2Role.addToPolicy(
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
    this.ec2Role.addToPolicy(
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
    this.ec2Role.addToPolicy(
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
    this.ec2Role.addToPolicy(
      new iam.PolicyStatement({
        sid: "KmsAccess",
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: [props.kmsKey.keyArn],
      }),
    );

    // EC2 self-discovery
    this.ec2Role.addToPolicy(
      new iam.PolicyStatement({
        sid: "Ec2SelfDiscovery",
        actions: ["ec2:DescribeInstances", "ec2:DescribeTags"],
        resources: ["*"],
      }),
    );

    // STS
    this.ec2Role.addToPolicy(
      new iam.PolicyStatement({
        sid: "StsAccess",
        actions: ["sts:GetCallerIdentity", "sts:AssumeRole"],
        resources: ["*"],
      }),
    );

    // EFS access points management
    this.ec2Role.addToPolicy(
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

    this.ec2Role.addToPolicy(
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

    // S3 (OpenClaw config bucket — future needs)
    this.ec2Role.addToPolicy(
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

    // -------------------------------------------------------------------------
    // User Data
    // -------------------------------------------------------------------------
    const userDataScript = fs.readFileSync(
      path.join(__dirname, "..", "user-data.sh"),
      "utf8",
    );

    const privateSubnetIds = props.vpc
      .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
      .subnetIds.join(",");

    const userData = ec2.UserData.custom(
      cdk.Fn.sub(userDataScript, {
        Project: "isol8",
        Environment: env,
        SecretPrefix: `isol8/${env}`,
        SecretDatabaseUrl: `isol8/${env}/database_url`,
        SecretClerkIssuer: `isol8/${env}/clerk_issuer`,
        SecretClerkWebhookSecret: `isol8/${env}/clerk_webhook_secret`,
        SecretStripeSecretKey: `isol8/${env}/stripe_secret_key`,
        SecretStripeWebhookSecret: `isol8/${env}/stripe_webhook_secret`,
        SecretPerplexityApiKey: `isol8/${env}/perplexity_api_key`,
        SecretEncryptionKey: `isol8/${env}/encryption_key`,
        Region: this.region,
        FrontendUrl:
          env === "prod"
            ? "https://isol8.co"
            : `https://${env}.isol8.co`,
        WsConnectionsTable: `isol8-${env}-ws-connections`,
        WsManagementApiUrl: "", // Will be set by ApiStack
        StripeStarterFixedPriceId: "",
        StripeProFixedPriceId: "",
        StripeMeteredPriceId: "",
        StripeMeterIdParam: "",
        DomainName: `api-${env}.isol8.co`,
        ContainerExecutionRoleArn:
          props.container.taskExecutionRole.roleArn,
        EcsClusterArn: props.container.cluster.clusterArn,
        EcsTaskDefinition: `isol8-${env}-openclaw`,
        EcsSubnets: privateSubnetIds,
        EcsSecurityGroupId:
          props.container.containerSecurityGroup.securityGroupId,
        EfsFileSystemId: props.container.efsFileSystem.fileSystemId,
        CloudMapNamespaceId:
          props.container.cloudMapNamespace.namespaceId,
        CloudMapServiceId: props.container.cloudMapService.serviceId,
        CloudMapServiceArn: props.container.cloudMapService.serviceArn,
        ImageUri: backendImage.imageUri,
      }),
    );

    // -------------------------------------------------------------------------
    // Auto Scaling Group
    // -------------------------------------------------------------------------
    this.asg = new autoscaling.AutoScalingGroup(this, "Asg", {
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      instanceType: config.instanceType,
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      role: this.ec2Role,
      userData,
      securityGroup: this.ec2SecurityGroup,
      minCapacity: config.minCapacity,
      desiredCapacity: config.desiredCapacity,
      maxCapacity: config.maxCapacity,
      healthCheck: autoscaling.HealthCheck.elb({
        grace: cdk.Duration.seconds(300),
      }),
      blockDevices: [
        {
          deviceName: "/dev/xvda",
          volume: autoscaling.BlockDeviceVolume.ebs(30, {
            volumeType: autoscaling.EbsDeviceVolumeType.GP3,
            encrypted: true,
            deleteOnTermination: true,
          }),
        },
      ],
      updatePolicy: autoscaling.UpdatePolicy.rollingUpdate({
        minInstancesInService: 1,
        pauseTime: cdk.Duration.minutes(5),
      }),
      instanceMonitoring: autoscaling.Monitoring.DETAILED,
      requireImdsv2: true,
    });

    // Register ASG with ALB target group
    this.asg.attachToApplicationTargetGroup(targetGroup);

    // -------------------------------------------------------------------------
    // NLB (for WebSocket VPC Link v1 — targets EC2 instances on port 8000)
    // -------------------------------------------------------------------------
    // VPC Link V1 (required for WebSocket APIs) only supports NLB targets.
    // NLB is co-located with compute to avoid circular stack dependencies.
    this.nlb = new elbv2.NetworkLoadBalancer(this, "WebSocketNlb", {
      vpc: props.vpc,
      internetFacing: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      crossZoneEnabled: true,
    });

    const nlbTargetGroup = new elbv2.NetworkTargetGroup(
      this,
      "NlbTargetGroup",
      {
        vpc: props.vpc,
        port: 8000,
        protocol: elbv2.Protocol.TCP,
        targetType: elbv2.TargetType.INSTANCE,
        healthCheck: {
          enabled: true,
          protocol: elbv2.Protocol.HTTP,
          path: "/health",
          port: "traffic-port",
          healthyThresholdCount: 2,
          unhealthyThresholdCount: 2,
          interval: cdk.Duration.seconds(30),
        },
      },
    );

    this.nlb.addListener("NlbTcpListener", {
      port: 80,
      protocol: elbv2.Protocol.TCP,
      defaultTargetGroups: [nlbTargetGroup],
    });

    // Register ASG instances with NLB target group
    this.asg.attachToNetworkTargetGroup(nlbTargetGroup);

    this.nlbDnsName = this.nlb.loadBalancerDnsName;

    // -------------------------------------------------------------------------
    // Tags
    // -------------------------------------------------------------------------
    cdk.Tags.of(this.asg).add("Name", `isol8-${env}-instance`);
    cdk.Tags.of(this.asg).add("Project", "isol8");
    cdk.Tags.of(this.asg).add("Environment", env);
  }
}
