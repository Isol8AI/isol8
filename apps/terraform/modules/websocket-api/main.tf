# =============================================================================
# WebSocket API Gateway Module
# =============================================================================
# Creates a WebSocket API Gateway with Clerk JWT Lambda authorizer for
# real-time bidirectional communication with the backend.
#
# Architecture:
#   Client (wss://) -> API Gateway WebSocket -> VPC Link -> ALB -> EC2
#
# Authentication:
#   $connect route uses Lambda authorizer that validates Clerk JWT from
#   query parameter (?token=...) and passes user context to backend via headers.
# =============================================================================

# -----------------------------------------------------------------------------
# WebSocket API
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "websocket" {
  name                       = "${var.project}-${var.environment}-websocket"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = {
    Name        = "${var.project}-${var.environment}-websocket"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Lambda Authorizer
# -----------------------------------------------------------------------------
# Dependencies are installed by CI/CD pipeline (GitHub Actions) before
# terraform plan runs. This ensures the archive_file includes all packages.
# See .github/workflows/terraform.yml "Install Lambda dependencies" step.
# -----------------------------------------------------------------------------

# Package Lambda code (dependencies installed by CI)
data "archive_file" "authorizer" {
  type        = "zip"
  source_dir  = "${path.module}/../../lambda/websocket-authorizer"
  output_path = "${path.module}/../../lambda/websocket-authorizer.zip"
  excludes    = ["__pycache__", "*.pyc", "*.dist-info", "requirements.txt"]
}

# Lambda execution role
resource "aws_iam_role" "authorizer" {
  name = "${var.project}-${var.environment}-ws-authorizer-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-ws-authorizer-role"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "authorizer_basic" {
  role       = aws_iam_role.authorizer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda function
resource "aws_lambda_function" "authorizer" {
  filename         = data.archive_file.authorizer.output_path
  function_name    = "${var.project}-${var.environment}-ws-authorizer"
  role             = aws_iam_role.authorizer.arn
  handler          = "index.handler"
  source_code_hash = data.archive_file.authorizer.output_base64sha256
  runtime          = "python3.11"
  timeout          = 10

  environment {
    variables = {
      CLERK_JWKS_URL    = var.clerk_jwks_url
      CLERK_ISSUER      = var.clerk_issuer
    }
  }

  # Lambda layer for dependencies (PyJWT, cryptography)
  layers = var.jwt_layer_arn != "" ? [var.jwt_layer_arn] : []

  tags = {
    Name        = "${var.project}-${var.environment}-ws-authorizer"
    Project     = var.project
    Environment = var.environment
  }
}

# Permission for API Gateway to invoke Lambda
resource "aws_lambda_permission" "authorizer" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*"
}

# API Gateway authorizer
# Note: WebSocket APIs don't support authorizer_payload_format_version or enable_simple_responses
resource "aws_apigatewayv2_authorizer" "clerk_jwt" {
  api_id           = aws_apigatewayv2_api.websocket.id
  authorizer_type  = "REQUEST"
  authorizer_uri   = aws_lambda_function.authorizer.invoke_arn
  identity_sources = ["route.request.querystring.token"]
  name             = "clerk-jwt-authorizer"
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group for Lambda
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "authorizer" {
  name              = "/aws/lambda/${aws_lambda_function.authorizer.function_name}"
  retention_in_days = 30

  tags = {
    Name        = "${var.project}-${var.environment}-ws-authorizer-logs"
    Project     = var.project
    Environment = var.environment
  }
}

# =============================================================================
# VPC Link V1 (Required for WebSocket APIs)
# =============================================================================
# VPC Link V2 (aws_apigatewayv2_vpc_link) does NOT support WebSocket APIs.
# Must use VPC Link V1 (aws_api_gateway_vpc_link) which targets NLB.
# =============================================================================

resource "aws_api_gateway_vpc_link" "websocket" {
  name        = "${var.project}-${var.environment}-ws-vpc-link-v1"
  target_arns = [var.nlb_arn]

  tags = {
    Name        = "${var.project}-${var.environment}-ws-vpc-link-v1"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# VPC Link Integrations (one per route for HTTP type)
# -----------------------------------------------------------------------------

# $connect integration
resource "aws_apigatewayv2_integration" "connect" {
  api_id             = aws_apigatewayv2_api.websocket.id
  integration_type   = "HTTP"
  integration_uri    = "http://${var.nlb_dns_name}/api/v1/ws/connect"
  integration_method = "POST"
  connection_type    = "VPC_LINK"
  connection_id      = aws_api_gateway_vpc_link.websocket.id

  request_parameters = {
    "integration.request.header.x-connection-id" = "context.connectionId"
    "integration.request.header.x-user-id"       = "context.authorizer.userId"
    "integration.request.header.x-org-id"        = "context.authorizer.orgId"
    "integration.request.header.Content-Type"    = "'application/json'"
  }

  timeout_milliseconds = 5000
}

# $connect integration response - required for non-proxy HTTP integrations
# Maps backend HTTP response to WebSocket response
# Backend returns empty body, so no template transformation needed
# See: https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api-integration-responses.html
resource "aws_apigatewayv2_integration_response" "connect" {
  api_id                   = aws_apigatewayv2_api.websocket.id
  integration_id           = aws_apigatewayv2_integration.connect.id
  integration_response_key = "$default"
}

# $disconnect integration
resource "aws_apigatewayv2_integration" "disconnect" {
  api_id             = aws_apigatewayv2_api.websocket.id
  integration_type   = "HTTP"
  integration_uri    = "http://${var.nlb_dns_name}/api/v1/ws/disconnect"
  integration_method = "POST"
  connection_type    = "VPC_LINK"
  connection_id      = aws_api_gateway_vpc_link.websocket.id

  request_parameters = {
    "integration.request.header.x-connection-id" = "context.connectionId"
    "integration.request.header.Content-Type"    = "'application/json'"
  }

  timeout_milliseconds = 5000
}

# $disconnect integration response - backend returns empty body
resource "aws_apigatewayv2_integration_response" "disconnect" {
  api_id                   = aws_apigatewayv2_api.websocket.id
  integration_id           = aws_apigatewayv2_integration.disconnect.id
  integration_response_key = "$default"
}

# $default integration (messages)
resource "aws_apigatewayv2_integration" "message" {
  api_id             = aws_apigatewayv2_api.websocket.id
  integration_type   = "HTTP"
  integration_uri    = "http://${var.nlb_dns_name}/api/v1/ws/message"
  integration_method = "POST"
  connection_type    = "VPC_LINK"
  connection_id      = aws_api_gateway_vpc_link.websocket.id

  request_parameters = {
    "integration.request.header.x-connection-id" = "context.connectionId"
    "integration.request.header.Content-Type"    = "'application/json'"
  }

  timeout_milliseconds = 10000
}

# $default integration response - backend returns empty body
# Actual responses come via Management API, not HTTP response
resource "aws_apigatewayv2_integration_response" "message" {
  api_id                   = aws_apigatewayv2_api.websocket.id
  integration_id           = aws_apigatewayv2_integration.message.id
  integration_response_key = "$default"
}

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
# Route responses are required for HTTP integrations via VPC Link.
# Integration responses use empty templates to prevent HTTP body from being
# forwarded to WebSocket client. Actual responses come via Management API.
# See: https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api-integration-responses.html

# $connect route (with authorizer)
resource "aws_apigatewayv2_route" "connect" {
  api_id                              = aws_apigatewayv2_api.websocket.id
  route_key                           = "$connect"
  authorization_type                  = "CUSTOM"
  authorizer_id                       = aws_apigatewayv2_authorizer.clerk_jwt.id
  target                              = "integrations/${aws_apigatewayv2_integration.connect.id}"
  route_response_selection_expression = "$default"
}

# $connect route response
resource "aws_apigatewayv2_route_response" "connect" {
  api_id             = aws_apigatewayv2_api.websocket.id
  route_id           = aws_apigatewayv2_route.connect.id
  route_response_key = "$default"
}

# $disconnect route
resource "aws_apigatewayv2_route" "disconnect" {
  api_id                              = aws_apigatewayv2_api.websocket.id
  route_key                           = "$disconnect"
  target                              = "integrations/${aws_apigatewayv2_integration.disconnect.id}"
  route_response_selection_expression = "$default"
}

# $disconnect route response
resource "aws_apigatewayv2_route_response" "disconnect" {
  api_id             = aws_apigatewayv2_api.websocket.id
  route_id           = aws_apigatewayv2_route.disconnect.id
  route_response_key = "$default"
}

# $default route (for all messages)
resource "aws_apigatewayv2_route" "default" {
  api_id                              = aws_apigatewayv2_api.websocket.id
  route_key                           = "$default"
  target                              = "integrations/${aws_apigatewayv2_integration.message.id}"
  route_response_selection_expression = "$default"
}

# $default route response
resource "aws_apigatewayv2_route_response" "default" {
  api_id             = aws_apigatewayv2_api.websocket.id
  route_id           = aws_apigatewayv2_route.default.id
  route_response_key = "$default"
}

# -----------------------------------------------------------------------------
# Stage
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.websocket.id
  name        = var.environment
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.websocket_api.arn
    format = jsonencode({
      requestId    = "$context.requestId"
      ip           = "$context.identity.sourceIp"
      requestTime  = "$context.requestTime"
      routeKey     = "$context.routeKey"
      status       = "$context.status"
      connectionId = "$context.connectionId"
      eventType    = "$context.eventType"
      authorizer   = "$context.authorizer.error"
      error        = "$context.integrationErrorMessage"
    })
  }

  tags = {
    Name        = "${var.project}-${var.environment}-websocket-stage"
    Project     = var.project
    Environment = var.environment
  }

  # Ensure CloudWatch logging role is fully propagated before creating stage
  depends_on = [aws_api_gateway_account.main]
}

# CloudWatch Log Group for API Gateway
resource "aws_cloudwatch_log_group" "websocket_api" {
  name              = "/aws/api-gateway/${var.project}-${var.environment}-websocket"
  retention_in_days = 30

  tags = {
    Name        = "${var.project}-${var.environment}-websocket-api-logs"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# API Gateway Account-Level CloudWatch Logging Role
# -----------------------------------------------------------------------------
# This is an account-level setting required for API Gateway access logging.
# Only created if enable_api_gateway_logging_role is true (default for dev).
# Should only be created once per AWS account.
# -----------------------------------------------------------------------------

resource "aws_iam_role" "api_gateway_cloudwatch" {
  count = var.enable_api_gateway_logging_role ? 1 : 0
  name  = "api-gateway-cloudwatch-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "apigateway.amazonaws.com"
      }
    }]
  })

  tags = {
    Name    = "api-gateway-cloudwatch-role"
    Project = var.project
  }
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  count      = var.enable_api_gateway_logging_role ? 1 : 0
  role       = aws_iam_role.api_gateway_cloudwatch[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  count               = var.enable_api_gateway_logging_role ? 1 : 0
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch[0].arn
}

# -----------------------------------------------------------------------------
# Custom Domain (optional)
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_domain_name" "websocket" {
  count       = var.domain_name != "" ? 1 : 0
  domain_name = var.domain_name

  domain_name_configuration {
    certificate_arn = var.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Name        = "${var.project}-${var.environment}-websocket-domain"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_apigatewayv2_api_mapping" "websocket" {
  count       = var.domain_name != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.websocket.id
  domain_name = aws_apigatewayv2_domain_name.websocket[0].id
  stage       = aws_apigatewayv2_stage.main.id
}

# -----------------------------------------------------------------------------
# DynamoDB Table for Connection State
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "connections" {
  name         = "${var.project}-${var.environment}-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project}-${var.environment}-ws-connections"
    Project     = var.project
    Environment = var.environment
  }
}
