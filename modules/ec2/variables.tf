# =============================================================================
# EC2 Module - Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for EC2 instances"
  type        = list(string)
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "instance_profile_name" {
  description = "IAM instance profile name"
  type        = string
}

variable "target_group_arn" {
  description = "ALB target group ARN"
  type        = string
}

variable "nlb_target_group_arn" {
  description = "NLB target group ARN for WebSocket traffic"
  type        = string
  default     = ""
}

variable "alb_security_group_id" {
  description = "ALB security group ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block for NLB traffic ingress"
  type        = string
  default     = ""
}

variable "secrets_arn_prefix" {
  description = "Secrets Manager ARN prefix"
  type        = string
}

variable "frontend_url" {
  description = "Frontend URL for CORS configuration"
  type        = string
}

variable "town_frontend_url" {
  description = "GooseTown frontend URL for CORS configuration"
  type        = string
  default     = ""
}

# Auto Scaling
variable "desired_count" {
  description = "Desired number of instances"
  type        = number
  default     = 1
}

variable "min_count" {
  description = "Minimum number of instances"
  type        = number
  default     = 1
}

variable "max_count" {
  description = "Maximum number of instances"
  type        = number
  default     = 3
}

# WebSocket
variable "ws_connections_table" {
  description = "DynamoDB table name for WebSocket connections"
  type        = string
  default     = ""
}

variable "ws_management_api_url" {
  description = "Management API URL for pushing WebSocket messages"
  type        = string
  default     = ""
}

variable "town_token_secret" {
  description = "Shared HMAC secret for signing/verifying GooseTown agent tokens"
  type        = string
  sensitive   = true
  default     = ""
}

# Stripe billing
variable "stripe_starter_fixed_price_id" {
  description = "Stripe Price ID for Starter plan monthly fee"
  type        = string
  default     = ""
}

variable "stripe_pro_fixed_price_id" {
  description = "Stripe Price ID for Pro plan monthly fee"
  type        = string
  default     = ""
}

variable "stripe_metered_price_id" {
  description = "Stripe Price ID for metered LLM usage (shared across tiers)"
  type        = string
  default     = ""
}

variable "stripe_meter_id" {
  description = "Stripe Billing Meter ID for LLM token usage"
  type        = string
  default     = ""
}

variable "container_execution_role_arn" {
  description = "IAM role ARN for container Bedrock access (STS AssumeRole)"
  type        = string
  default     = ""
}

# ECS Fargate integration
variable "ecs_cluster_arn" {
  description = "ECS cluster ARN for Fargate service management"
  type        = string
  default     = ""
}

variable "ecs_task_definition" {
  description = "ECS task definition family name"
  type        = string
  default     = ""
}

variable "ecs_subnets" {
  description = "Comma-separated subnet IDs for ECS tasks"
  type        = string
  default     = ""
}

variable "ecs_security_group_id" {
  description = "Security group ID for ECS Fargate tasks"
  type        = string
  default     = ""
}

variable "efs_file_system_id" {
  description = "EFS file system ID for workspace storage"
  type        = string
  default     = ""
}

variable "s3_config_bucket" {
  description = "S3 bucket name for OpenClaw config storage"
  type        = string
  default     = ""
}

variable "cloud_map_namespace_id" {
  description = "Cloud Map namespace ID for service discovery"
  type        = string
  default     = ""
}

variable "cloud_map_service_id" {
  description = "Cloud Map service ID for OpenClaw"
  type        = string
  default     = ""
}

variable "cloud_map_service_arn" {
  description = "Cloud Map service ARN for OpenClaw"
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "API domain name (e.g., api-dev.isol8.co) for proxy URL"
  type        = string
}
