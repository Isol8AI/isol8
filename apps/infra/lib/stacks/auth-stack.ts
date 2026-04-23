import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

export interface AuthSecrets {
  clerkIssuer: secretsmanager.ISecret;
  clerkSecretKey: secretsmanager.ISecret;
  stripeSecretKey: secretsmanager.ISecret;
  stripeWebhookSecret: secretsmanager.ISecret;
  encryptionKey: secretsmanager.ISecret;
  posthogProjectApiKey: secretsmanager.ISecret;
}

export interface AuthStackProps extends cdk.StackProps {
  environment: string;
  /** Optional initial secret values (for local dev — production sets these manually). */
  secretValues?: Record<string, string>;
}

export class AuthStack extends cdk.Stack {
  public readonly secrets: AuthSecrets;
  public readonly kmsKey: kms.Key;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);

    const env = props.environment;

    // KMS key for general encryption (EBS, EFS, DynamoDB)
    this.kmsKey = new kms.Key(this, "GeneralEncryptionKey", {
      enableKeyRotation: true,
      description: `Isol8 ${env} general encryption key (EBS, EFS, DynamoDB)`,
      alias: `isol8-${env}-general`,
    });

    // Helper to create a CDK-managed secret.
    // If secretValues is provided (local dev), use that value instead of random generation.
    const secretVals = props.secretValues ?? {};
    const createSecret = (logicalId: string, secretName: string): secretsmanager.Secret => {
      const initialValue = secretVals[secretName];
      return new secretsmanager.Secret(this, logicalId, {
        secretName: `isol8/${env}/${secretName}`,
        description: `Isol8 ${env} ${secretName}`,
        encryptionKey: this.kmsKey,
        ...(initialValue
          ? { secretStringValue: cdk.SecretValue.unsafePlainText(initialValue) }
          : {}),
      });
    };

    // PostHog personal API key for the admin Activity tab. Distinct from
    // NEXT_PUBLIC_POSTHOG_KEY (which is the frontend ingest key). Defaults
    // to empty string rather than a random value — an empty key makes
    // posthog_admin.py short-circuit to {stubbed: true} so the backend
    // starts cleanly before the operator populates the real key via
    // `aws secretsmanager update-secret`.
    const posthogProjectApiKey = new secretsmanager.Secret(
      this,
      "PosthogProjectApiKey",
      {
        secretName: `isol8/${env}/posthog_project_api_key`,
        description: `Isol8 ${env} posthog_project_api_key`,
        encryptionKey: this.kmsKey,
        secretStringValue: cdk.SecretValue.unsafePlainText(
          secretVals["posthog_project_api_key"] ?? "",
        ),
      },
    );

    this.secrets = {
      clerkIssuer: createSecret("ClerkIssuer", "clerk_issuer"),
      clerkSecretKey: createSecret("ClerkSecretKey", "clerk_secret_key"),
      stripeSecretKey: createSecret("StripeSecretKey", "stripe_secret_key"),
      stripeWebhookSecret: createSecret("StripeWebhookSecret", "stripe_webhook_secret"),
      encryptionKey: createSecret("EncryptionKey", "encryption_key"),
      posthogProjectApiKey,
    };
  }
}
