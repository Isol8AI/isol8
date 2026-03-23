#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { LocalStage } from "./local-stage";

const app = new cdk.App();

new LocalStage(app, "local", {
  env: { account: "000000000000", region: "us-east-1" },
});

app.synth();
