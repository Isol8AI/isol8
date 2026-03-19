import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface AuthSecrets {
  clerkSecretKey: secretsmanager.ISecret;
  clerkWebhookSecret: secretsmanager.ISecret;
  stripeSecretKey: secretsmanager.ISecret;
  stripeWebhookSecret: secretsmanager.ISecret;
  perplexityApiKey: secretsmanager.ISecret;
  encryptionKey: secretsmanager.ISecret;
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

    // Import existing secrets (created by terraform, values already populated)
    const importSecret = (logicalId: string, secretName: string): secretsmanager.ISecret =>
      secretsmanager.Secret.fromSecretNameV2(this, logicalId, `isol8/${env}/${secretName}`);

    this.secrets = {
      clerkSecretKey: importSecret("ClerkSecretKey", "clerk_secret_key"),
      clerkWebhookSecret: importSecret("ClerkWebhookSecret", "clerk_webhook_secret"),
      stripeSecretKey: importSecret("StripeSecretKey", "stripe_secret_key"),
      stripeWebhookSecret: importSecret("StripeWebhookSecret", "stripe_webhook_secret"),
      perplexityApiKey: importSecret("PerplexityApiKey", "perplexity_api_key"),
      encryptionKey: importSecret("EncryptionKey", "encryption_key"),
    };
  }
}
