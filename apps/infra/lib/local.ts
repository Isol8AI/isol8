#!/usr/bin/env node
/**
 * CDK entry point for local development via cdklocal.
 *
 * Uses LocalStage (same pattern as production Isol8Stage) but skips
 * DnsStack and certificate/hostedZone for LocalStack compatibility.
 *
 * Deploy with: cdklocal deploy "local/*" --require-approval never
 * (Stage-wrapped stacks require the "stage/*" glob pattern)
 */
import * as cdk from "aws-cdk-lib";
import { LocalStage } from "./local-stage";

const app = new cdk.App();

new LocalStage(app, "local", {
  env: { account: "000000000000", region: "us-east-1" },
});

app.synth();
