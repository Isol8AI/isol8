import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface AuthSecrets {
  clerkIssuer: secretsmanager.ISecret;
  clerkSecretKey: secretsmanager.ISecret;
  clerkWebhookSecret: secretsmanager.ISecret;
  stripeSecretKey: secretsmanager.ISecret;
  stripeWebhookSecret: secretsmanager.ISecret;
  perplexityApiKey: secretsmanager.ISecret;
  encryptionKey: secretsmanager.ISecret;
  databaseUrl: secretsmanager.ISecret;
}

export interface AuthStackProps extends cdk.StackProps {
  environment: string;
}

export class AuthStack extends cdk.Stack {
  public readonly secrets: AuthSecrets;
  public readonly kmsKey: kms.Key;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);

    const env = props.environment;

    // KMS key for general encryption (EBS, EFS, RDS)
    this.kmsKey = new kms.Key(this, "GeneralEncryptionKey", {
      enableKeyRotation: true,
      description: `Isol8 ${env} general encryption key (EBS, EFS, RDS)`,
      alias: `isol8-${env}-general`,
    });

    // Helper to create a CDK-managed secret
    const createSecret = (logicalId: string, secretName: string): secretsmanager.Secret =>
      new secretsmanager.Secret(this, logicalId, {
        secretName: `isol8/${env}/${secretName}`,
        description: `Isol8 ${env} ${secretName}`,
        encryptionKey: this.kmsKey,
      });

    this.secrets = {
      clerkIssuer: createSecret("ClerkIssuer", "clerk_issuer"),
      clerkSecretKey: createSecret("ClerkSecretKey", "clerk_secret_key"),
      clerkWebhookSecret: createSecret("ClerkWebhookSecret", "clerk_webhook_secret"),
      stripeSecretKey: createSecret("StripeSecretKey", "stripe_secret_key"),
      stripeWebhookSecret: createSecret("StripeWebhookSecret", "stripe_webhook_secret"),
      perplexityApiKey: createSecret("PerplexityApiKey", "perplexity_api_key"),
      encryptionKey: createSecret("EncryptionKey", "encryption_key"),
      databaseUrl: createSecret("DatabaseUrl", "database_url"),
    };
  }
}
