import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as kms from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

export interface DatabaseStackProps extends cdk.StackProps {
  environment: string;
  kmsKey: kms.IKey;
}

const ENV_CONFIG: Record<string, { removalPolicy: cdk.RemovalPolicy }> = {
  dev: { removalPolicy: cdk.RemovalPolicy.DESTROY },
  prod: { removalPolicy: cdk.RemovalPolicy.RETAIN },
};

export class DatabaseStack extends cdk.Stack {
  public readonly usersTable: dynamodb.Table;
  public readonly containersTable: dynamodb.Table;
  public readonly billingTable: dynamodb.Table;
  public readonly apiKeysTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;
    const env = props.environment;

    this.usersTable = new dynamodb.Table(this, "UsersTable", {
      tableName: `isol8-${env}-users`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    this.containersTable = new dynamodb.Table(this, "ContainersTable", {
      tableName: `isol8-${env}-containers`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "gateway-token-index",
      partitionKey: { name: "gateway_token", type: dynamodb.AttributeType.STRING },
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "status-index",
      partitionKey: { name: "status", type: dynamodb.AttributeType.STRING },
    });

    this.billingTable = new dynamodb.Table(this, "BillingTable", {
      tableName: `isol8-${env}-billing-accounts`,
      partitionKey: { name: "clerk_user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
    this.billingTable.addGlobalSecondaryIndex({
      indexName: "stripe-customer-index",
      partitionKey: { name: "stripe_customer_id", type: dynamodb.AttributeType.STRING },
    });

    this.apiKeysTable = new dynamodb.Table(this, "ApiKeysTable", {
      tableName: `isol8-${env}-api-keys`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "tool_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    new cdk.CfnOutput(this, "DynamoTablePrefix", {
      value: `isol8-${env}-`,
      exportName: `${this.stackName}-table-prefix`,
    });
  }
}
