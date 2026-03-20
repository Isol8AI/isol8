import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { ApiStack } from "./stacks/api-stack";
import { AuthStack } from "./stacks/auth-stack";
import { ComputeStack } from "./stacks/compute-stack";
import { ContainerStack } from "./stacks/container-stack";
import { DatabaseStack } from "./stacks/database-stack";
import { DnsStack } from "./stacks/dns-stack";
import { NetworkStack } from "./stacks/network-stack";

export interface Isol8StageProps extends cdk.StageProps {
  environment: string;
}

export class Isol8Stage extends cdk.Stage {
  constructor(scope: Construct, id: string, props: Isol8StageProps) {
    super(scope, id, props);

    const env = props.environment;

    const auth = new AuthStack(this, `isol8-${env}-auth`, {
      stackName: `isol8-${env}-auth`,
      environment: env,
    });

    const dns = new DnsStack(this, `isol8-${env}-dns`, {
      stackName: `isol8-${env}-dns`,
      environment: env,
    });

    const network = new NetworkStack(this, `isol8-${env}-network`, {
      stackName: `isol8-${env}-network`,
      environment: env,
    });

    const database = new DatabaseStack(this, `isol8-${env}-database`, {
      stackName: `isol8-${env}-database`,
      environment: env,
      vpc: network.vpc,
      kmsKey: auth.kmsKey,
    });

    const container = new ContainerStack(this, `isol8-${env}-container`, {
      stackName: `isol8-${env}-container`,
      environment: env,
      vpc: network.vpc,
      kmsKey: auth.kmsKey,
    });

    const compute = new ComputeStack(this, `isol8-${env}-compute`, {
      stackName: `isol8-${env}-compute`,
      environment: env,
      vpc: network.vpc,
      database: {
        dbInstance: database.dbInstance,
        dbSecurityGroup: database.dbSecurityGroup,
        dbSecret: database.dbSecret,
      },
      secrets: auth.secrets,
      kmsKey: auth.kmsKey,
      certificate: dns.certificate,
      container: {
        cluster: container.cluster,
        cloudMapNamespace: container.cloudMapNamespace,
        cloudMapService: container.cloudMapService,
        efsFileSystem: container.efsFileSystem,
        efsSecurityGroup: container.efsSecurityGroup,
        containerSecurityGroup: container.containerSecurityGroup,
        taskExecutionRole: container.taskExecutionRole,
        taskRole: container.taskRole,
      },
    });

    new ApiStack(this, `isol8-${env}-api`, {
      stackName: `isol8-${env}-api`,
      environment: env,
      vpc: network.vpc,
      certificate: dns.certificate,
      hostedZone: dns.hostedZone,
      ec2Role: compute.ec2Role,
      albListenerArn: compute.albHttpListenerArn,
      albSecurityGroupId: compute.albSecurityGroup.securityGroupId,
      nlbArn: compute.nlb.loadBalancerArn,
      nlbDnsName: compute.nlbDnsName,
    });

    // --- Tags ---
    cdk.Tags.of(this).add("Project", "isol8");
    cdk.Tags.of(this).add("Environment", env);
  }
}
