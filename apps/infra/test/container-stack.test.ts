import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import { Match, Template } from "aws-cdk-lib/assertions";
import { ContainerStack } from "../lib/stacks/container-stack";

describe("ContainerStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const env = { account: "877352799272", region: "us-east-1" };

    // Support stack hosts dependencies the ContainerStack needs by reference
    const supportStack = new cdk.Stack(app, "SupportStack", { env });
    const vpc = new ec2.Vpc(supportStack, "Vpc");
    const kmsKey = new kms.Key(supportStack, "KmsKey");

    const containerStack = new ContainerStack(app, "TestContainerStack", {
      env,
      environment: "dev",
      vpc,
      kmsKeyArn: kmsKey.keyArn,
    });

    template = Template.fromStack(containerStack);
  });

  test("creates the extended OpenClaw ECR repo with immutable tags + scan-on-push", () => {
    template.hasResourceProperties("AWS::ECR::Repository", {
      RepositoryName: "isol8/openclaw-extended",
      ImageScanningConfiguration: { ScanOnPush: true },
      ImageTagMutability: "IMMUTABLE",
    });
  });

  test("ECR repo has a 30-image lifecycle policy", () => {
    template.hasResourceProperties("AWS::ECR::Repository", {
      LifecyclePolicy: {
        LifecyclePolicyText: Match.stringLikeRegexp('"countNumber"\\s*:\\s*30'),
      },
    });
  });
});
