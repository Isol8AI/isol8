#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { ShellStep } from "aws-cdk-lib/pipelines";
import { AwsCredentials, GitHubWorkflow, StackCapabilities } from "cdk-pipelines-github";
import { Isol8Stage } from "./isol8-stage";

const app = new cdk.App();
const awsEnv = { account: "877352799272", region: "us-east-1" };

// ---------------------------------------------------------------------------
// CDK Pipeline (generates .github/workflows/deploy.yml)
// ---------------------------------------------------------------------------
const pipeline = new GitHubWorkflow(app, "isol8-pipeline", {
  synth: new ShellStep("Synth", {
    commands: [
      "cd apps/infra",
      "npm ci",
      "npx cdk synth",
    ],
  }),
  awsCreds: AwsCredentials.fromOpenIdConnect({
    gitHubActionRoleArn: "arn:aws:iam::877352799272:role/isol8-dev-github-actions",
  }),
  workflowPath: "../../.github/workflows/deploy.yml",
});

// ---------------------------------------------------------------------------
// Dev stage — auto-deploy on merge to main
// ---------------------------------------------------------------------------
pipeline.addStageWithGitHubOptions(
  new Isol8Stage(app, "dev", {
    env: awsEnv,
    environment: "dev",
  }),
  {
    stackCapabilities: [
      StackCapabilities.NAMED_IAM,
      StackCapabilities.AUTO_EXPAND,
    ],
  },
);

// ---------------------------------------------------------------------------
// Prod stage — manual approval via GitHub environment protection rules
// ---------------------------------------------------------------------------
pipeline.addStageWithGitHubOptions(
  new Isol8Stage(app, "prod", {
    env: awsEnv,
    environment: "prod",
  }),
  {
    gitHubEnvironment: { name: "prod" },
    stackCapabilities: [
      StackCapabilities.NAMED_IAM,
      StackCapabilities.AUTO_EXPAND,
    ],
  },
);

app.synth();
