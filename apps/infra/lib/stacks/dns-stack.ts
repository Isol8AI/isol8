import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as route53 from "aws-cdk-lib/aws-route53";
import { Construct } from "constructs";

export interface DnsStackProps extends cdk.StackProps {
  environment: string;
}

export class DnsStack extends cdk.Stack {
  public readonly certificate: acm.ICertificate;
  public readonly hostedZone: route53.IHostedZone;

  constructor(scope: Construct, id: string, props: DnsStackProps) {
    super(scope, id, props);

    this.hostedZone = route53.HostedZone.fromLookup(this, "HostedZone", {
      domainName: "isol8.co",
    });

    this.certificate = new acm.Certificate(this, "WildcardCert", {
      domainName: "*.isol8.co",
      subjectAlternativeNames: ["isol8.co"],
      validation: acm.CertificateValidation.fromDns(this.hostedZone),
    });
  }
}
