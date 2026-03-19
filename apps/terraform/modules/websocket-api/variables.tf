# =============================================================================
# WebSocket API Module - Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------

variable "domain_name" {
  description = "Custom domain name for WebSocket API (e.g., ws-dev.isol8.co). Leave empty to skip custom domain."
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "ACM certificate ARN for custom domain (required if domain_name is set)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# NLB Integration (VPC Link V1 - Required for WebSocket APIs)
# -----------------------------------------------------------------------------
# WebSocket APIs require VPC Link V1 (aws_api_gateway_vpc_link) which targets NLB.
# VPC Link V2 (aws_apigatewayv2_vpc_link) does NOT support WebSocket APIs.
# The ALB is still used for HTTP API; this NLB is specifically for WebSocket.
# -----------------------------------------------------------------------------

variable "nlb_arn" {
  description = "NLB ARN for VPC Link V1 target"
  type        = string
}

variable "nlb_dns_name" {
  description = "NLB DNS name for integration URI"
  type        = string
}

# -----------------------------------------------------------------------------
# Clerk Configuration
# -----------------------------------------------------------------------------

variable "clerk_jwks_url" {
  description = "Clerk JWKS URL for JWT validation (e.g., https://<clerk-domain>/.well-known/jwks.json)"
  type        = string
}

variable "clerk_issuer" {
  description = "Clerk issuer URL for JWT validation (e.g., https://<clerk-domain>)"
  type        = string
}

# -----------------------------------------------------------------------------
# Lambda Configuration
# -----------------------------------------------------------------------------

variable "jwt_layer_arn" {
  description = "Lambda layer ARN containing PyJWT and cryptography dependencies. Leave empty if dependencies are bundled."
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------

variable "throttling_burst_limit" {
  description = "Throttling burst limit (concurrent requests)"
  type        = number
  default     = 100
}

variable "throttling_rate_limit" {
  description = "Throttling rate limit (requests per second)"
  type        = number
  default     = 50
}

# -----------------------------------------------------------------------------
# CloudWatch Logging
# -----------------------------------------------------------------------------

variable "enable_api_gateway_logging_role" {
  description = "Create account-level IAM role for API Gateway CloudWatch logging. Only set to true for one environment per AWS account."
  type        = bool
  default     = true
}
