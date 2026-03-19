import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface DatabaseStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  kmsKey: kms.IKey;
}

const ENV_CONFIG: Record<
  string,
  {
    instanceType: ec2.InstanceType;
    multiAz: boolean;
    backupRetention: number;
    removalPolicy: cdk.RemovalPolicy;
  }
> = {
  dev: {
    instanceType: ec2.InstanceType.of(
      ec2.InstanceClass.T3,
      ec2.InstanceSize.SMALL,
    ),
    multiAz: false,
    backupRetention: 7,
    removalPolicy: cdk.RemovalPolicy.DESTROY,
  },
  prod: {
    instanceType: ec2.InstanceType.of(
      ec2.InstanceClass.T3,
      ec2.InstanceSize.MEDIUM,
    ),
    multiAz: true,
    backupRetention: 30,
    removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
  },
};

export class DatabaseStack extends cdk.Stack {
  public readonly dbInstance: rds.DatabaseInstance;
  public readonly dbSecurityGroup: ec2.SecurityGroup;
  public readonly dbSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;

    this.dbSecurityGroup = new ec2.SecurityGroup(this, "DbSecurityGroup", {
      vpc: props.vpc,
      description: `Isol8 ${props.environment} RDS PostgreSQL security group`,
      allowAllOutbound: false,
    });

    this.dbInstance = new rds.DatabaseInstance(this, "PostgresInstance", {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15,
      }),
      instanceType: config.instanceType,
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.dbSecurityGroup],
      multiAz: config.multiAz,
      storageEncrypted: true,
      storageEncryptionKey: props.kmsKey,
      credentials: rds.Credentials.fromGeneratedSecret("isol8_admin", {
        secretName: `isol8/${props.environment}/rds-credentials`,
      }),
      databaseName: "isol8",
      port: 5432,
      backupRetention: cdk.Duration.days(config.backupRetention),
      removalPolicy: config.removalPolicy,
    });

    this.dbSecret = this.dbInstance.secret!;
  }
}
