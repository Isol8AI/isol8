#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { NetworkStack } from "./stacks/network-stack";

const app = new cdk.App();
const env = app.node.tryGetContext("env") || "dev";
const awsEnv = { account: "877352799272", region: "us-east-1" };

const network = new NetworkStack(app, `isol8-${env}-network`, {
  env: awsEnv,
  environment: env,
});
