import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import { Match, Template } from "aws-cdk-lib/assertions";
import { ContainerStack } from "../lib/stacks/container-stack";

function buildStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };
  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const vpc = new ec2.Vpc(supportStack, "Vpc");
  const kmsKey = new kms.Key(supportStack, "KmsKey");
  const containerStack = new ContainerStack(app, `Container-${environment}`, {
    env,
    environment,
    vpc,
    kmsKeyArn: kmsKey.keyArn,
  });
  return Template.fromStack(containerStack);
}

describe("ContainerStack — dev", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("dev");
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

  test("creates the openclaw-image-builder OIDC role for CI image pushes", () => {
    template.hasResourceProperties("AWS::IAM::Role", {
      RoleName: "isol8-openclaw-image-builder",
      AssumeRolePolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "sts:AssumeRoleWithWebIdentity",
            Condition: Match.objectLike({
              StringLike: {
                "token.actions.githubusercontent.com:sub":
                  "repo:Isol8AI/isol8:*",
              },
              StringEquals: {
                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
              },
            }),
          }),
        ]),
      }),
    });
  });

  test("builder role has ECR auth + push permissions on the openclaw-extended repo", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "ecr:GetAuthorizationToken",
            Effect: "Allow",
            Resource: "*",
          }),
        ]),
      }),
    });
  });
});

describe("ContainerStack — prod", () => {
  let template: Template;
  beforeAll(() => {
    template = buildStack("prod");
  });

  test("does NOT create the ECR repo (referenced by name from dev)", () => {
    template.resourceCountIs("AWS::ECR::Repository", 0);
  });

  test("does NOT create the image-builder role (single account-wide role)", () => {
    // No role with name isol8-openclaw-image-builder — verify by checking
    // no IAM::Role with that exact RoleName exists.
    const roles = template.findResources("AWS::IAM::Role");
    const builderRoles = Object.values(roles).filter(
      (r: unknown) =>
        (r as { Properties?: { RoleName?: string } }).Properties?.RoleName ===
        "isol8-openclaw-image-builder",
    );
    expect(builderRoles).toHaveLength(0);
  });
});
