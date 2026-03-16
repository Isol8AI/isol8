# =============================================================================
# API Gateway Module - HTTP API
# =============================================================================
# Creates an HTTP API (API Gateway v2) that routes requests to the ALB.
# This adds rate limiting, throttling, and a clean API endpoint.
#
# Architecture:
#   Vercel → API Gateway → ALB → EC2 (FastAPI + per-user containers)
# =============================================================================

# -----------------------------------------------------------------------------
# HTTP API
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project}-${var.environment}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins     = var.cors_allow_origins
    allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers     = ["Content-Type", "Authorization", "X-Requested-With"]
    expose_headers    = ["Content-Type"]
    allow_credentials = true
    max_age           = 86400
  }

  tags = {
    Name = "${var.project}-${var.environment}-api"
  }
}

# -----------------------------------------------------------------------------
# VPC Link (for private ALB integration)
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_vpc_link" "main" {
  name               = "${var.project}-${var.environment}-vpc-link"
  security_group_ids = [var.alb_security_group_id]
  subnet_ids         = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-vpc-link"
  }
}

# -----------------------------------------------------------------------------
# Integration with ALB
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "alb" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "HTTP_PROXY"
  integration_uri    = var.alb_listener_arn
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.main.id

  # 30s max timeout for HTTP API (ALB handles long SSE connections)
  timeout_milliseconds = 30000
}

# -----------------------------------------------------------------------------
# Route - Catch all requests
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.alb.id}"
}

# -----------------------------------------------------------------------------
# Stage
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  tags = {
    Name = "${var.project}-${var.environment}-api-stage"
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group for API Gateway
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/api-gateway/${var.project}-${var.environment}"
  retention_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-api-gateway-logs"
  }
}

# -----------------------------------------------------------------------------
# Custom Domain (optional)
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_domain_name" "main" {
  count       = var.domain_name != "" ? 1 : 0
  domain_name = var.domain_name

  domain_name_configuration {
    certificate_arn = var.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Name = "${var.project}-${var.environment}-api-domain"
  }
}

resource "aws_apigatewayv2_api_mapping" "main" {
  count       = var.domain_name != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.main.id
  domain_name = aws_apigatewayv2_domain_name.main[0].id
  stage       = aws_apigatewayv2_stage.main.id
}
