#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { ShellStep } from "aws-cdk-lib/pipelines";
import {
  AwsCredentials,
  GitHubWorkflow,
  GitHubActionStep,
  StackCapabilities,
} from "cdk-pipelines-github";
import { Isol8Stage } from "./isol8-stage";

const app = new cdk.App();
const awsEnv = { account: "877352799272", region: "us-east-1" };

// Vercel env vars used in all Vercel deploy steps
const vercelEnv = {
  VERCEL_TOKEN: "${{ secrets.VERCEL_TOKEN }}",
  VERCEL_ORG_ID: "${{ secrets.VERCEL_ORG_ID }}",
  VERCEL_PROJECT_ID: "${{ secrets.VERCEL_PROJECT_ID }}",
};

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
        { name: "Checkout", uses: "actions/checkout@v4" },
        { name: "Setup pnpm", uses: "pnpm/action-setup@v4" },
        { name: "Setup Node.js", uses: "actions/setup-node@v4", with: { "node-version": "20", cache: "pnpm" } },
        { name: "Install Vercel CLI", run: "npm install -g vercel" },
        { name: "Pull Vercel Settings", run: "vercel pull --yes --token=$VERCEL_TOKEN", env: vercelEnv },
        {
          name: "Build Frontend",
          run: "vercel build --token=$VERCEL_TOKEN",
          env: {
            ...vercelEnv,
            NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV }}",
            NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_DEV }}",
          },
        },
        {
          name: "Deploy to Vercel (Preview)",
          id: "vercel-deploy-dev",
          run: 'DEPLOY_URL=$(vercel deploy --prebuilt --token=$VERCEL_TOKEN) && echo "DEPLOY_URL=$DEPLOY_URL" >> $GITHUB_OUTPUT',
          env: vercelEnv,
        },
        {
          name: "Alias to dev.isol8.co",
          run: "vercel alias ${{ steps.vercel-deploy-dev.outputs.DEPLOY_URL }} dev.isol8.co --token=$VERCEL_TOKEN",
          env: vercelEnv,
        },
      ],
    }),
  ],
});

// ---------------------------------------------------------------------------
// Automated e2e gate between dev and prod
// ---------------------------------------------------------------------------
const e2eGate = new GitHubActionStep("E2EGate", {
  jobSteps: [
    { name: "Checkout", uses: "actions/checkout@v4" },
    { name: "Setup pnpm", uses: "pnpm/action-setup@v4" },
    {
      name: "Setup Node.js",
      uses: "actions/setup-node@v4",
      with: { "node-version": "20", cache: "pnpm" },
    },
    {
      name: "Install dependencies",
      run: "pnpm install --frozen-lockfile",
    },
    {
      name: "Install Playwright browsers",
      run: "cd apps/frontend && npx playwright install chromium --with-deps",
    },
    {
      name: "Run E2E gate tests",
      run: "cd apps/frontend && timeout 1200 npx playwright test --project=chromium || (echo 'E2E tests failed or timed out after 20 min' && exit 1)",
      env: {
        BASE_URL: "https://dev.isol8.co",
        NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_DEV }}",
        NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_DEV }}",
        CLERK_SECRET_KEY: "${{ secrets.CLERK_SECRET_KEY_DEV }}",
        STRIPE_SECRET_KEY: "${{ secrets.STRIPE_SECRET_KEY }}",
        VERCEL_AUTOMATION_BYPASS_SECRET: "${{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}",
      },
    },
    {
      name: "Upload Playwright report",
      uses: "actions/upload-artifact@v4",
      if: "always()",
      with: {
        name: "playwright-report",
        path: "apps/frontend/playwright-report/",
        "retention-days": 7,
      },
    },
  ],
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
  pre: [e2eGate],
  post: [
    // Deploy frontend to Vercel (production) and alias to app.isol8.co
    new GitHubActionStep("DeployVercelProd", {
      jobSteps: [
        { name: "Checkout", uses: "actions/checkout@v4" },
        { name: "Setup pnpm", uses: "pnpm/action-setup@v4" },
        { name: "Setup Node.js", uses: "actions/setup-node@v4", with: { "node-version": "20", cache: "pnpm" } },
        { name: "Install Vercel CLI", run: "npm install -g vercel" },
        { name: "Pull Vercel Settings", run: "vercel pull --yes --environment=production --token=$VERCEL_TOKEN", env: vercelEnv },
        {
          name: "Build Frontend (Production)",
          run: "vercel build --prod --token=$VERCEL_TOKEN",
          env: {
            ...vercelEnv,
            NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "${{ secrets.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY_PROD }}",
            NEXT_PUBLIC_API_URL: "${{ secrets.NEXT_PUBLIC_API_URL_PROD }}",
          },
        },
        {
          name: "Deploy to Vercel (Production)",
          id: "vercel-deploy-prod",
          run: 'DEPLOY_URL=$(vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN) && echo "DEPLOY_URL=$DEPLOY_URL" >> $GITHUB_OUTPUT',
          env: vercelEnv,
        },
        {
          name: "Alias to app.isol8.co",
          run: "vercel alias ${{ steps.vercel-deploy-prod.outputs.DEPLOY_URL }} app.isol8.co --token=$VERCEL_TOKEN",
          env: vercelEnv,
        },
      ],
    }),
  ],
});

app.synth();
