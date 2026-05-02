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

    // Route Paperclip ("Teams") traffic to Vercel. The frontend project
    // has a host-conditional rewrite (apps/frontend/vercel.json) that
    // proxies these hostnames to the backend's paperclip_proxy router
    // via the standard api[-{env}].isol8.co API Gateway endpoint. We
    // route via Vercel (instead of giving the API Gateway a second
    // custom domain) so we get Vercel's edge TLS, observability, and
    // preview-deploy URLs the same way dev.isol8.co already does.
    //
    // 76.76.21.21 is Vercel's documented anycast IP for apex/subdomain
    // attachment to a Vercel project. Auto-provisions a Let's Encrypt
    // cert for the domain when the project also has it added (already
    // done via `vercel domains add`).
    const paperclipHost =
      props.environment === "prod" ? "company.isol8.co" : `${props.environment}.company.isol8.co`;
    new route53.ARecord(this, "PaperclipFrontendRecord", {
      zone: this.hostedZone,
      recordName: paperclipHost,
      target: route53.RecordTarget.fromIpAddresses("76.76.21.21"),
      ttl: cdk.Duration.minutes(5),
    });
  }
}
