#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { AuthStack } from "./stacks/auth-stack";
import { NetworkStack } from "./stacks/network-stack";

const app = new cdk.App();
const env = app.node.tryGetContext("env") || "dev";
const awsEnv = { account: "877352799272", region: "us-east-1" };

const auth = new AuthStack(app, `isol8-${env}-auth`, {
  env: awsEnv,
  environment: env,
});

const network = new NetworkStack(app, `isol8-${env}-network`, {
  env: awsEnv,
  environment: env,
});
