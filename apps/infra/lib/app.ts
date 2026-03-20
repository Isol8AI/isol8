#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { ShellStep } from "aws-cdk-lib/pipelines";
import {
  AwsCredentials,
  GitHubWorkflow,
  GitHubActionStep,
  StackCapabilities,
  JobPermission,
} from "cdk-pipelines-github";
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
    primaryOutputDirectory: "apps/infra/cdk.out",
  }),
  awsCreds: AwsCredentials.fromOpenIdConnect({
    gitHubActionRoleArn: "arn:aws:iam::877352799272:role/isol8-dev-github-actions",
  }),
  workflowPath: "../../.github/workflows/deploy.yml",
});

// ---------------------------------------------------------------------------
// Dev stage — auto-deploy infra + frontend on merge to main
// ---------------------------------------------------------------------------
const devStage = new Isol8Stage(app, "dev", {
  env: awsEnv,
  environment: "dev",
});

pipeline.addStageWithGitHubOptions(devStage, {
  stackCapabilities: [
    StackCapabilities.NAMED_IAM,
    StackCapabilities.AUTO_EXPAND,
  ],
  post: [
    // Deploy frontend to Vercel (preview) and alias to dev.isol8.co
    new GitHubActionStep("DeployVercelDev", {
      jobSteps: [
        {
          name: "Checkout",
          uses: "actions/checkout@v4",
        },
        {
          name: "Install Vercel CLI",
          run: "npm install -g vercel",
        },
        {
          name: "Build Frontend",
          run: "cd apps/frontend && npx vercel build --token=$VERCEL_TOKEN",
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
        {
          name: "Deploy to Vercel (Preview)",
          id: "vercel-deploy-dev",
          run: [
            "cd apps/frontend",
            "DEPLOY_URL=$(npx vercel deploy --prebuilt --token=$VERCEL_TOKEN)",
            'echo "DEPLOY_URL=$DEPLOY_URL" >> $GITHUB_OUTPUT',
          ].join("\n"),
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
        {
          name: "Alias to dev.isol8.co",
          run: "npx vercel alias ${{ steps.vercel-deploy-dev.outputs.DEPLOY_URL }} dev.isol8.co --token=$VERCEL_TOKEN",
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
      ],
    }),
  ],
});

// ---------------------------------------------------------------------------
// Manual approval gate between dev and prod
// ---------------------------------------------------------------------------
const approvalStep = new GitHubActionStep("ApproveProduction", {
  jobSteps: [
    {
      name: "Approval Required",
      uses: "trstringer/manual-approval@v1",
      with: {
        secret: "${{ github.TOKEN }}",
        approvers: "prez2307",
        "issue-title": "Approve production deployment",
        "issue-body": "A new deployment is ready for production. Review the dev deployment at https://dev.isol8.co and approve or deny.",
        "minimum-approvals": "1",
      },
    },
  ],
  permissions: {
    issues: JobPermission.WRITE,
  },
});

// ---------------------------------------------------------------------------
// Prod stage — deploy after manual approval
// ---------------------------------------------------------------------------
const prodStage = new Isol8Stage(app, "prod", {
  env: awsEnv,
  environment: "prod",
});

pipeline.addStageWithGitHubOptions(prodStage, {
  stackCapabilities: [
    StackCapabilities.NAMED_IAM,
    StackCapabilities.AUTO_EXPAND,
  ],
  pre: [approvalStep],
  post: [
    // Deploy frontend to Vercel (production) and alias to app.isol8.co
    new GitHubActionStep("DeployVercelProd", {
      jobSteps: [
        {
          name: "Checkout",
          uses: "actions/checkout@v4",
        },
        {
          name: "Install Vercel CLI",
          run: "npm install -g vercel",
        },
        {
          name: "Build Frontend (Production)",
          run: "cd apps/frontend && npx vercel build --prod --token=$VERCEL_TOKEN",
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
        {
          name: "Deploy to Vercel (Production)",
          id: "vercel-deploy-prod",
          run: [
            "cd apps/frontend",
            "DEPLOY_URL=$(npx vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN)",
            'echo "DEPLOY_URL=$DEPLOY_URL" >> $GITHUB_OUTPUT',
          ].join("\n"),
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
        {
          name: "Alias to app.isol8.co",
          run: "npx vercel alias ${{ steps.vercel-deploy-prod.outputs.DEPLOY_URL }} app.isol8.co --token=$VERCEL_TOKEN",
          env: {
            VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
            VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
            VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
          },
        },
      ],
    }),
  ],
});

app.synth();
