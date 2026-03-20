import * as path from "path";
import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as apigatewayv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as route53 from "aws-cdk-lib/aws-route53";
import { Construct } from "constructs";

// =============================================================================
// ApiStack — HTTP API Gateway + WebSocket API Gateway
// =============================================================================
// HTTP API:  Vercel → API Gateway v2 (HTTP) → VPC Link v2 → ALB → EC2
// WebSocket: Client → API Gateway v2 (WS) → VPC Link v1 → NLB → EC2:8000
// =============================================================================

export interface ApiStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  certificate: acm.ICertificate;
  hostedZone: route53.IHostedZone;
  ec2Role: iam.IRole;
  albListenerArn: string;
  albSecurityGroupId: string;
  nlbArn: string;
  nlbDnsName: string;
}

const THROTTLE_CONFIG: Record<
  string,
  { burstLimit: number; rateLimit: number }
> = {
  dev: { burstLimit: 100, rateLimit: 50 },
  prod: { burstLimit: 500, rateLimit: 200 },
};

export class ApiStack extends cdk.Stack {
  public readonly httpApiUrl: string;
  public readonly webSocketUrl: string;
  public readonly managementApiUrl: string;
  public readonly connectionsTableName: string;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const env = props.environment;
    const isProd = env === "prod";
    const throttle = THROTTLE_CONFIG[env] ?? THROTTLE_CONFIG.dev;

    // =========================================================================
    // HTTP API Gateway
    // =========================================================================

    const httpApiDomain = isProd ? "api.isol8.co" : `api-${env}.isol8.co`;
    const frontendUrl = isProd
      ? "https://isol8.co"
      : `https://${env}.isol8.co`;

    // --- HTTP API ---
    const httpApi = new apigatewayv2.CfnApi(this, "HttpApi", {
      name: `isol8-${env}-api`,
      protocolType: "HTTP",
      corsConfiguration: {
        allowOrigins: [frontendUrl],
        allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allowHeaders: [
          "Content-Type",
          "Authorization",
          "X-Requested-With",
        ],
        exposeHeaders: ["Content-Type"],
        allowCredentials: true,
        maxAge: 86400,
      },
    });

    // --- VPC Link v2 (for HTTP API → ALB) ---
    const vpcLinkV2 = new apigatewayv2.CfnVpcLink(this, "HttpVpcLink", {
      name: `isol8-${env}-vpc-link`,
      securityGroupIds: [props.albSecurityGroupId],
      subnetIds: props.vpc.selectSubnets({
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      }).subnetIds,
    });

    // --- HTTP Integration → ALB via VPC Link ---
    const httpIntegration = new apigatewayv2.CfnIntegration(
      this,
      "HttpAlbIntegration",
      {
        apiId: httpApi.ref,
        integrationType: "HTTP_PROXY",
        integrationUri: props.albListenerArn,
        integrationMethod: "ANY",
        connectionType: "VPC_LINK",
        connectionId: vpcLinkV2.ref,
        payloadFormatVersion: "1.0",
        timeoutInMillis: 30000,
      },
    );

    // --- Default route ---
    new apigatewayv2.CfnRoute(this, "HttpDefaultRoute", {
      apiId: httpApi.ref,
      routeKey: "$default",
      target: `integrations/${httpIntegration.ref}`,
    });

    // --- HTTP API Log Group ---
    const httpApiLogGroup = new logs.LogGroup(this, "HttpApiLogs", {
      logGroupName: `/aws/api-gateway/isol8-${env}-http`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // --- Stage ---
    new apigatewayv2.CfnStage(this, "HttpStage", {
      apiId: httpApi.ref,
      stageName: "$default",
      autoDeploy: true,
      defaultRouteSettings: {
        throttlingBurstLimit: throttle.burstLimit,
        throttlingRateLimit: throttle.rateLimit,
      },
      accessLogSettings: {
        destinationArn: httpApiLogGroup.logGroupArn,
        format: JSON.stringify({
          requestId: "$context.requestId",
          ip: "$context.identity.sourceIp",
          requestTime: "$context.requestTime",
          httpMethod: "$context.httpMethod",
          routeKey: "$context.routeKey",
          status: "$context.status",
          protocol: "$context.protocol",
          responseLength: "$context.responseLength",
          integrationError: "$context.integrationErrorMessage",
        }),
      },
    });

    // --- Custom domain for HTTP API ---
    const httpDomainName = new apigatewayv2.CfnDomainName(
      this,
      "HttpDomain",
      {
        domainName: httpApiDomain,
        domainNameConfigurations: [
          {
            certificateArn: props.certificate.certificateArn,
            endpointType: "REGIONAL",
            securityPolicy: "TLS_1_2",
          },
        ],
      },
    );

    new apigatewayv2.CfnApiMapping(this, "HttpApiMapping", {
      apiId: httpApi.ref,
      domainName: httpDomainName.ref,
      stage: "$default",
    });

    // --- Route53 A record for HTTP API ---
    new route53.ARecord(this, "HttpApiDnsRecord", {
      zone: props.hostedZone,
      recordName: httpApiDomain,
      target: route53.RecordTarget.fromAlias({
        bind: () => ({
          dnsName: cdk.Fn.getAtt(httpDomainName.logicalId, "RegionalDomainName").toString(),
          hostedZoneId: cdk.Fn.getAtt(httpDomainName.logicalId, "RegionalHostedZoneId").toString(),
        }),
      }),
    });

    this.httpApiUrl = `https://${httpApiDomain}`;

    // =========================================================================
    // DynamoDB Connections Table
    // =========================================================================

    const connectionsTable = new dynamodb.Table(this, "ConnectionsTable", {
      tableName: `isol8-${env}-ws-connections`,
      partitionKey: { name: "connectionId", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: "ttl",
    });

    this.connectionsTableName = connectionsTable.tableName;

    // =========================================================================
    // Lambda Authorizer (Clerk JWT validation for WebSocket $connect)
    // =========================================================================

    const authorizerFn = new lambda.Function(this, "WsAuthorizer", {
      functionName: `isol8-${env}-ws-authorizer`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "..", "..", "lambda", "websocket-authorizer"),
        {
          bundling: {
            image: lambda.Runtime.PYTHON_3_11.bundlingImage,
            command: [
              "bash",
              "-c",
              "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
            ],
          },
        },
      ),
      timeout: cdk.Duration.seconds(10),
      environment: {
        CLERK_ISSUER: `https://clerk.isol8.co`,
        CLERK_JWKS_URL: "https://clerk.isol8.co/.well-known/jwks.json",
      },
      logRetention: logs.RetentionDays.ONE_MONTH,
    });

    // =========================================================================
    // WebSocket API Gateway
    // =========================================================================

    const wsDomain = isProd ? "ws.isol8.co" : `ws-${env}.isol8.co`;

    // --- WebSocket API ---
    const wsApi = new apigatewayv2.CfnApi(this, "WebSocketApi", {
      name: `isol8-${env}-websocket`,
      protocolType: "WEBSOCKET",
      routeSelectionExpression: "$request.body.action",
    });

    // --- Permission for API Gateway to invoke the authorizer Lambda ---
    new lambda.CfnPermission(this, "WsAuthorizerInvokePermission", {
      action: "lambda:InvokeFunction",
      functionName: authorizerFn.functionName,
      principal: "apigateway.amazonaws.com",
      sourceArn: `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.ref}/*`,
    });

    // --- Authorizer ---
    const wsAuthorizer = new apigatewayv2.CfnAuthorizer(
      this,
      "WsClerkAuthorizer",
      {
        apiId: wsApi.ref,
        authorizerType: "REQUEST",
        authorizerUri: `arn:aws:apigateway:${this.region}:lambda:path/2015-03-31/functions/${authorizerFn.functionArn}/invocations`,
        identitySource: ["route.request.querystring.token"],
        name: "clerk-jwt-authorizer",
      },
    );

    // --- VPC Link v1 (REST API style — required for WebSocket APIs) ---
    // CDK L2 VpcLink is for REST API (apigateway, not apigatewayv2).
    // We use CfnResource for the REST API VPC Link which targets NLB.
    const vpcLinkV1 = new cdk.CfnResource(this, "WsVpcLinkV1", {
      type: "AWS::ApiGateway::VpcLink",
      properties: {
        Name: `isol8-${env}-ws-vpc-link-v1`,
        TargetArns: [props.nlbArn],
      },
    });

    // --- $connect integration ---
    const connectIntegration = new apigatewayv2.CfnIntegration(
      this,
      "WsConnectIntegration",
      {
        apiId: wsApi.ref,
        integrationType: "HTTP",
        integrationUri: `http://${props.nlbDnsName}/api/v1/ws/connect`,
        integrationMethod: "POST",
        connectionType: "VPC_LINK",
        connectionId: vpcLinkV1.ref,
        requestParameters: {
          "integration.request.header.x-connection-id": "context.connectionId",
          "integration.request.header.x-user-id": "context.authorizer.userId",
          "integration.request.header.x-org-id": "context.authorizer.orgId",
          "integration.request.header.Content-Type": "'application/json'",
        },
        timeoutInMillis: 5000,
      },
    );

    // $connect integration response
    new apigatewayv2.CfnIntegrationResponse(
      this,
      "WsConnectIntegrationResponse",
      {
        apiId: wsApi.ref,
        integrationId: connectIntegration.ref,
        integrationResponseKey: "$default",
      },
    );

    // --- $disconnect integration ---
    const disconnectIntegration = new apigatewayv2.CfnIntegration(
      this,
      "WsDisconnectIntegration",
      {
        apiId: wsApi.ref,
        integrationType: "HTTP",
        integrationUri: `http://${props.nlbDnsName}/api/v1/ws/disconnect`,
        integrationMethod: "POST",
        connectionType: "VPC_LINK",
        connectionId: vpcLinkV1.ref,
        requestParameters: {
          "integration.request.header.x-connection-id": "context.connectionId",
          "integration.request.header.Content-Type": "'application/json'",
        },
        timeoutInMillis: 5000,
      },
    );

    // $disconnect integration response
    new apigatewayv2.CfnIntegrationResponse(
      this,
      "WsDisconnectIntegrationResponse",
      {
        apiId: wsApi.ref,
        integrationId: disconnectIntegration.ref,
        integrationResponseKey: "$default",
      },
    );

    // --- $default (message) integration ---
    const messageIntegration = new apigatewayv2.CfnIntegration(
      this,
      "WsMessageIntegration",
      {
        apiId: wsApi.ref,
        integrationType: "HTTP",
        integrationUri: `http://${props.nlbDnsName}/api/v1/ws/message`,
        integrationMethod: "POST",
        connectionType: "VPC_LINK",
        connectionId: vpcLinkV1.ref,
        requestParameters: {
          "integration.request.header.x-connection-id": "context.connectionId",
          "integration.request.header.Content-Type": "'application/json'",
        },
        timeoutInMillis: 10000,
      },
    );

    // $default integration response
    new apigatewayv2.CfnIntegrationResponse(
      this,
      "WsMessageIntegrationResponse",
      {
        apiId: wsApi.ref,
        integrationId: messageIntegration.ref,
        integrationResponseKey: "$default",
      },
    );

    // =========================================================================
    // WebSocket Routes
    // =========================================================================

    // --- $connect route (with authorizer) ---
    const connectRoute = new apigatewayv2.CfnRoute(
      this,
      "WsConnectRoute",
      {
        apiId: wsApi.ref,
        routeKey: "$connect",
        authorizationType: "CUSTOM",
        authorizerId: wsAuthorizer.ref,
        target: `integrations/${connectIntegration.ref}`,
        routeResponseSelectionExpression: "$default",
      },
    );

    new apigatewayv2.CfnRouteResponse(this, "WsConnectRouteResponse", {
      apiId: wsApi.ref,
      routeId: connectRoute.ref,
      routeResponseKey: "$default",
    });

    // --- $disconnect route ---
    const disconnectRoute = new apigatewayv2.CfnRoute(
      this,
      "WsDisconnectRoute",
      {
        apiId: wsApi.ref,
        routeKey: "$disconnect",
        target: `integrations/${disconnectIntegration.ref}`,
        routeResponseSelectionExpression: "$default",
      },
    );

    new apigatewayv2.CfnRouteResponse(this, "WsDisconnectRouteResponse", {
      apiId: wsApi.ref,
      routeId: disconnectRoute.ref,
      routeResponseKey: "$default",
    });

    // --- $default route ---
    const defaultRoute = new apigatewayv2.CfnRoute(
      this,
      "WsDefaultRoute",
      {
        apiId: wsApi.ref,
        routeKey: "$default",
        target: `integrations/${messageIntegration.ref}`,
        routeResponseSelectionExpression: "$default",
      },
    );

    new apigatewayv2.CfnRouteResponse(this, "WsDefaultRouteResponse", {
      apiId: wsApi.ref,
      routeId: defaultRoute.ref,
      routeResponseKey: "$default",
    });

    // =========================================================================
    // WebSocket Stage
    // =========================================================================

    const wsApiLogGroup = new logs.LogGroup(this, "WsApiLogs", {
      logGroupName: `/aws/api-gateway/isol8-${env}-websocket`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const wsStage = new apigatewayv2.CfnStage(this, "WsStage", {
      apiId: wsApi.ref,
      stageName: env,
      autoDeploy: true,
      defaultRouteSettings: {
        throttlingBurstLimit: throttle.burstLimit,
        throttlingRateLimit: throttle.rateLimit,
      },
      accessLogSettings: {
        destinationArn: wsApiLogGroup.logGroupArn,
        format: JSON.stringify({
          requestId: "$context.requestId",
          ip: "$context.identity.sourceIp",
          requestTime: "$context.requestTime",
          routeKey: "$context.routeKey",
          status: "$context.status",
          connectionId: "$context.connectionId",
          eventType: "$context.eventType",
          authorizer: "$context.authorizer.error",
          error: "$context.integrationErrorMessage",
        }),
      },
    });

    // =========================================================================
    // WebSocket Custom Domain
    // =========================================================================

    const wsDomainName = new apigatewayv2.CfnDomainName(
      this,
      "WsDomain",
      {
        domainName: wsDomain,
        domainNameConfigurations: [
          {
            certificateArn: props.certificate.certificateArn,
            endpointType: "REGIONAL",
            securityPolicy: "TLS_1_2",
          },
        ],
      },
    );

    new apigatewayv2.CfnApiMapping(this, "WsApiMapping", {
      apiId: wsApi.ref,
      domainName: wsDomainName.ref,
      stage: wsStage.ref,
    });

    // --- Route53 A record for WebSocket API ---
    new route53.ARecord(this, "WsApiDnsRecord", {
      zone: props.hostedZone,
      recordName: wsDomain,
      target: route53.RecordTarget.fromAlias({
        bind: () => ({
          dnsName: cdk.Fn.getAtt(wsDomainName.logicalId, "RegionalDomainName").toString(),
          hostedZoneId: cdk.Fn.getAtt(wsDomainName.logicalId, "RegionalHostedZoneId").toString(),
        }),
      }),
    });

    this.webSocketUrl = `wss://${wsDomain}`;

    // =========================================================================
    // Management API URL
    // =========================================================================
    // The management API endpoint is:
    //   https://{api-id}.execute-api.{region}.amazonaws.com/{stage}
    this.managementApiUrl = `https://${wsApi.ref}.execute-api.${this.region}.amazonaws.com/${env}`;

    // =========================================================================
    // Grant EC2 role ManageConnections + DynamoDB permissions
    // =========================================================================
    // Use a standalone IAM policy in this stack to avoid circular dependency
    // between ApiStack and ComputeStack. The policy is attached to the EC2
    // role by name, keeping all references within this stack's template.
    new iam.CfnManagedPolicy(this, "Ec2WebSocketPolicy", {
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "WebSocketManageConnections",
            Effect: "Allow",
            Action: "execute-api:ManageConnections",
            Resource: [
              `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.ref}/${env}/POST/@connections/*`,
              `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.ref}/${env}/DELETE/@connections/*`,
              `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.ref}/${env}/GET/@connections/*`,
            ],
          },
          {
            Sid: "DynamoDbConnections",
            Effect: "Allow",
            Action: [
              "dynamodb:GetItem",
              "dynamodb:PutItem",
              "dynamodb:UpdateItem",
              "dynamodb:DeleteItem",
              "dynamodb:Query",
              "dynamodb:Scan",
              "dynamodb:BatchGetItem",
              "dynamodb:BatchWriteItem",
            ],
            Resource: connectionsTable.tableArn,
          },
        ],
      },
      roles: [props.ec2Role.roleName],
      managedPolicyName: `isol8-${env}-ec2-websocket-policy`,
    });

    // =========================================================================
    // CloudFormation Outputs
    // =========================================================================

    new cdk.CfnOutput(this, "HttpApiUrlOutput", {
      value: this.httpApiUrl,
      description: "HTTP API Gateway URL",
      exportName: `isol8-${env}-http-api-url`,
    });

    new cdk.CfnOutput(this, "WebSocketUrlOutput", {
      value: this.webSocketUrl,
      description: "WebSocket API Gateway URL",
      exportName: `isol8-${env}-websocket-url`,
    });

    new cdk.CfnOutput(this, "ManagementApiUrlOutput", {
      value: this.managementApiUrl,
      description: "WebSocket Management API URL (for pushing messages)",
      exportName: `isol8-${env}-management-api-url`,
    });

    new cdk.CfnOutput(this, "ConnectionsTableOutput", {
      value: connectionsTable.tableName,
      description: "DynamoDB connections table name",
      exportName: `isol8-${env}-connections-table`,
    });
  }
}
