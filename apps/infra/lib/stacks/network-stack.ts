import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";

export interface NetworkStackProps extends cdk.StackProps {
  environment: string;
}

const ENV_CONFIG: Record<string, { maxAzs: number; cidr: string }> = {
  dev: { maxAzs: 2, cidr: "10.0.0.0/16" },
  prod: { maxAzs: 3, cidr: "10.2.0.0/16" },
};

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;

    this.vpc = new ec2.Vpc(this, "Vpc", {
      ipAddresses: ec2.IpAddresses.cidr(config.cidr),
      maxAzs: config.maxAzs,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
      restrictDefaultSecurityGroup: true,
    });
  }
}
