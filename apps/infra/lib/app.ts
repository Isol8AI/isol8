#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { AuthStack } from "./stacks/auth-stack";
import { ContainerStack } from "./stacks/container-stack";
import { DatabaseStack } from "./stacks/database-stack";
import { DnsStack } from "./stacks/dns-stack";
import { NetworkStack } from "./stacks/network-stack";

const app = new cdk.App();
const env = app.node.tryGetContext("env") || "dev";
const awsEnv = { account: "877352799272", region: "us-east-1" };

const auth = new AuthStack(app, `isol8-${env}-auth`, {
  env: awsEnv,
  environment: env,
});

const dns = new DnsStack(app, `isol8-${env}-dns`, {
  env: awsEnv,
  environment: env,
});

const network = new NetworkStack(app, `isol8-${env}-network`, {
  env: awsEnv,
  environment: env,
});

const database = new DatabaseStack(app, `isol8-${env}-database`, {
  env: awsEnv,
  environment: env,
  vpc: network.vpc,
  kmsKey: auth.kmsKey,
});

const container = new ContainerStack(app, `isol8-${env}-container`, {
  env: awsEnv,
  environment: env,
  vpc: network.vpc,
  kmsKey: auth.kmsKey,
});
