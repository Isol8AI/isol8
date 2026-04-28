import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as kms from "aws-cdk-lib/aws-kms";
import * as rds from "aws-cdk-lib/aws-rds";
import * as servicediscovery from "aws-cdk-lib/aws-servicediscovery";
import { Match, Template } from "aws-cdk-lib/assertions";
import { PaperclipStack } from "../lib/stacks/paperclip-stack";

/**
 * Builds a PaperclipStack against a synthetic Aurora cluster + Cloud Map
 * namespace in a sibling support stack. PaperclipStack uses
 * CfnSecurityGroupIngress (not addIngressRule) for the cross-stack DB SG
 * grant, which keeps the synth dependency graph one-directional and
 * avoids cycles.
 */
function buildStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };

  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const vpc = new ec2.Vpc(supportStack, "Vpc", { maxAzs: 2 });
  const kmsKey = new kms.Key(supportStack, "KmsKey");
  const cluster = new ecs.Cluster(supportStack, "Cluster", { vpc });

  const namespace = new servicediscovery.PrivateDnsNamespace(
    supportStack,
    "Namespace",
    { name: `isol8-${environment}.local`, vpc },
  );

  const dbSg = new ec2.SecurityGroup(supportStack, "PaperclipDbSg", {
    vpc,
    allowAllOutbound: false,
  });

  const dbCluster = new rds.DatabaseCluster(supportStack, "PaperclipDb", {
    engine: rds.DatabaseClusterEngine.auroraPostgres({
      version: rds.AuroraPostgresEngineVersion.VER_16_4,
    }),
    serverlessV2MinCapacity: 0,
    serverlessV2MaxCapacity: 4,
    writer: rds.ClusterInstance.serverlessV2("writer"),
    vpc,
    securityGroups: [dbSg],
    defaultDatabaseName: "paperclip",
    credentials: rds.Credentials.fromGeneratedSecret("paperclip_admin", {
      secretName: `isol8-${environment}-paperclip-db-credentials`,
    }),
    storageEncrypted: true,
    storageEncryptionKey: kmsKey,
  });

  const stack = new PaperclipStack(app, `Paperclip-${environment}`, {
    env,
    environment,
    vpc,
    cluster,
    cloudMapNamespace: namespace,
    paperclipDbCluster: dbCluster,
    paperclipDbSecurityGroup: dbSg,
    paperclipBetterAuthSecretName: `isol8/${environment}/paperclip_better_auth_secret`,
  });

  return Template.fromStack(stack);
}

describe("PaperclipStack — Fargate service shape", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("dev");
  });

  test("creates the Paperclip task definition with upstream image and 0.5 vCPU / 1 GB", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", {
      Family: "isol8-dev-paperclip-server",
      Cpu: "512",
      Memory: "1024",
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Image: "paperclipai/paperclip:latest",
        }),
      ]),
    });
  });

  test("container env disables public sign-up and sets non-prod public URL", () => {
    // Pull the single TaskDef out of the template and assert directly
    // against its Environment array. arrayWith()-on-arrayWith() can't
    // express "all of these are present in any order" — it requires
    // monotonic ordering — so we extract once and use plain expect().
    const tasks = template.findResources("AWS::ECS::TaskDefinition", {
      Properties: { Family: "isol8-dev-paperclip-server" },
    });
    expect(Object.keys(tasks)).toHaveLength(1);
    const td = Object.values(tasks)[0] as { Properties: any };
    const env = td.Properties.ContainerDefinitions[0].Environment as Array<{
      Name: string;
      Value: string;
    }>;
    const envMap = Object.fromEntries(env.map((e) => [e.Name, e.Value]));
    expect(envMap.PAPERCLIP_AUTH_DISABLE_SIGN_UP).toBe("true");
    expect(envMap.PAPERCLIP_DEPLOYMENT_MODE).toBe("authenticated");
    expect(envMap.PAPERCLIP_DEPLOYMENT_EXPOSURE).toBe("public");
    expect(envMap.PORT).toBe("3100");
    expect(envMap.PGUSER).toBe("paperclip_admin");
    expect(envMap.PGDATABASE).toBe("paperclip");
    expect(envMap.PGPORT).toBe("5432");
    expect(envMap.PAPERCLIP_BIND).toBe("lan");
    expect(envMap.PAPERCLIP_PUBLIC_URL).toBe("https://company-dev.isol8.co");
  });

  test("container has DATABASE_URL-building entrypoint shim with URL-encoded password", () => {
    // RDS-generated passwords routinely contain `/`, `+`, `=`, `@`, `:` —
    // the shim must URL-encode PGPASSWORD via Node's encodeURIComponent
    // before interpolating into DATABASE_URL, then exec the upstream
    // entrypoint.
    template.hasResourceProperties("AWS::ECS::TaskDefinition", {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Command: [
            "/bin/sh",
            "-c",
            Match.stringLikeRegexp(
              'PGPASSWORD_ENC=\\$\\(node -e .*encodeURIComponent\\(process\\.env\\.PGPASSWORD\\).*\\) && export DATABASE_URL="postgres://\\$\\{PGUSER\\}:\\$\\{PGPASSWORD_ENC\\}@\\$\\{PGHOST\\}:\\$\\{PGPORT\\}/\\$\\{PGDATABASE\\}".*exec docker-entrypoint.sh',
            ),
          ],
        }),
      ]),
    });
  });

  test("container health check hits /api/health", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          HealthCheck: Match.objectLike({
            Command: [
              "CMD-SHELL",
              "curl -fsS http://localhost:3100/api/health || exit 1",
            ],
          }),
        }),
      ]),
    });
  });

  test("Fargate service runs in private subnets with no public IP", () => {
    template.hasResourceProperties("AWS::ECS::Service", {
      ServiceName: "isol8-dev-paperclip-server",
      LaunchType: "FARGATE",
      DesiredCount: 1,
      DeploymentConfiguration: Match.objectLike({
        DeploymentCircuitBreaker: Match.objectLike({ Enable: true, Rollback: true }),
      }),
      NetworkConfiguration: Match.objectLike({
        AwsvpcConfiguration: Match.objectLike({
          AssignPublicIp: "DISABLED",
        }),
      }),
    });
  });

  test("autoscaling target is 1–4 and tracks CPU at 70%", () => {
    template.hasResourceProperties("AWS::ApplicationAutoScaling::ScalableTarget", {
      MinCapacity: 1,
      MaxCapacity: 4,
      ServiceNamespace: "ecs",
    });
    template.hasResourceProperties(
      "AWS::ApplicationAutoScaling::ScalingPolicy",
      {
        PolicyType: "TargetTrackingScaling",
        TargetTrackingScalingPolicyConfiguration: Match.objectLike({
          TargetValue: 70,
          PredefinedMetricSpecification: Match.objectLike({
            PredefinedMetricType: "ECSServiceAverageCPUUtilization",
          }),
        }),
      },
    );
  });

  test("registers `paperclip` in Cloud Map exactly once with A records (10s TTL)", () => {
    // The FargateService.cloudMapOptions block is the SINGLE canonical
    // registration of `paperclip` in the namespace. A standalone
    // servicediscovery.Service alongside it would collide on the
    // namespace Name and fail at first deploy — so we assert exactly one
    // such service exists.
    const services = template.findResources(
      "AWS::ServiceDiscovery::Service",
      {
        Properties: {
          Name: "paperclip",
        },
      },
    );
    expect(Object.keys(services)).toHaveLength(1);
    const svc = Object.values(services)[0] as { Properties: any };
    const records = svc.Properties.DnsConfig?.DnsRecords ?? [];
    expect(records).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ Type: "A", TTL: 10 }),
      ]),
    );
  });

  test("Aurora SG gets ingress from Paperclip task SG on 5432", () => {
    // sg-on-sg ingress rule, the contract that lets Paperclip reach Postgres.
    template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
      FromPort: 5432,
      ToPort: 5432,
      IpProtocol: "tcp",
      Description: "Paperclip task → Aurora",
    });
  });

  test("exposes internal URL output for FastAPI proxy router (T14)", () => {
    template.hasOutput("PaperclipInternalUrl", {
      Value: "http://paperclip.isol8-dev.local:3100",
      Export: { Name: "isol8-dev-paperclip-internal-url" },
    });
  });

  test("log group lives at /isol8/{env}/paperclip with 14d retention", () => {
    template.hasResourceProperties("AWS::Logs::LogGroup", {
      LogGroupName: "/isol8/dev/paperclip",
      RetentionInDays: 14,
    });
  });
});

describe("PaperclipStack — prod public URL", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("prod");
  });

  test("prod container env points at https://company.isol8.co (no env suffix)", () => {
    const tasks = template.findResources("AWS::ECS::TaskDefinition", {
      Properties: { Family: "isol8-prod-paperclip-server" },
    });
    expect(Object.keys(tasks)).toHaveLength(1);
    const td = Object.values(tasks)[0] as { Properties: any };
    const envArr = td.Properties.ContainerDefinitions[0].Environment as Array<{
      Name: string;
      Value: string;
    }>;
    const envMap = Object.fromEntries(envArr.map((e) => [e.Name, e.Value]));
    expect(envMap.PAPERCLIP_PUBLIC_URL).toBe("https://company.isol8.co");
  });

  test("prod log group uses RETAIN removal policy", () => {
    const logGroups = template.findResources("AWS::Logs::LogGroup", {
      Properties: { LogGroupName: "/isol8/prod/paperclip" },
    });
    const ids = Object.keys(logGroups);
    expect(ids).toHaveLength(1);
    expect(logGroups[ids[0]].DeletionPolicy).toBe("Retain");
  });
});
