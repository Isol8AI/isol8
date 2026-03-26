# =============================================================================
# Isol8 Infrastructure - Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod"
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones to use"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

# -----------------------------------------------------------------------------
# EC2 Configuration
# -----------------------------------------------------------------------------

variable "ec2_instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.xlarge"

  validation {
    condition = contains([
      "m5.xlarge", "m5.2xlarge", "m5.4xlarge",
      "c5.xlarge", "c5.2xlarge", "c5.4xlarge",
      "r5.xlarge", "r5.2xlarge", "r5.4xlarge",
      "m5a.xlarge", "m5a.2xlarge", "m5a.4xlarge",
      "t3.xlarge", "t3.2xlarge",
    ], var.ec2_instance_type)
    error_message = "Instance type must be a supported type"
  }
}

variable "ec2_desired_count" {
  description = "Desired number of EC2 instances"
  type        = number
  default     = 1
}

variable "ec2_min_count" {
  description = "Minimum number of EC2 instances"
  type        = number
  default     = 1
}

variable "ec2_max_count" {
  description = "Maximum number of EC2 instances"
  type        = number
  default     = 3
}

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

variable "domain_name" {
  description = "Domain name for the API (e.g., api-dev.isol8.co)"
  type        = string
}

variable "root_domain" {
  description = "Root domain for Route53 (e.g., isol8.co)"
  type        = string
  default     = "isol8.co"
}

variable "frontend_url" {
  description = "Frontend URL for CORS (e.g., https://isol8.co)"
  type        = string
}

# -----------------------------------------------------------------------------
# Secrets (passed via environment variables, not in tfvars)
# -----------------------------------------------------------------------------

variable "supabase_connection_string" {
  description = "Supabase PostgreSQL connection string"
  type        = string
  sensitive   = true
}

variable "huggingface_token" {
  description = "HuggingFace API token"
  type        = string
  sensitive   = true
}

variable "clerk_issuer" {
  description = "Clerk issuer URL"
  type        = string
}

variable "clerk_jwks_url" {
  description = "Clerk JWKS URL for JWT validation (e.g., https://<clerk-domain>/.well-known/jwks.json)"
  type        = string
}

variable "clerk_secret_key" {
  description = "Clerk secret key for server-side API calls"
  type        = string
  sensitive   = true
}

variable "clerk_webhook_secret" {
  description = "Clerk webhook signing secret (optional, only needed if using Clerk webhooks)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_secret_key" {
  description = "Stripe API secret key (sk_test_... or sk_live_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret (whsec_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "perplexity_api_key" {
  description = "Perplexity API key (proxied web search for user containers)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "encryption_key" {
  description = "Fernet encryption key for BYOK API key encryption at rest"
  type        = string
  sensitive   = true
  default     = ""
}

# Stripe billing configuration (non-secret price IDs)
variable "stripe_metered_price_id" {
  description = "Stripe Price ID for metered LLM usage billing"
  type        = string
  default     = ""
}

variable "stripe_meter_id" {
  description = "Stripe Billing Meter ID for LLM token usage"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# GitHub Actions OIDC (for CI/CD)
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# GitHub Actions OIDC (for CI/CD)
# -----------------------------------------------------------------------------

variable "github_org" {
  description = "GitHub organization name"
  type        = string
  default     = ""
}

variable "github_repos" {
  description = "List of GitHub repository names to trust for CI/CD"
  type        = list(string)
  default     = []
}
