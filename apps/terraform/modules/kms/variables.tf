# =============================================================================
# KMS Module - Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "ec2_role_arn" {
  description = "ARN of the EC2 IAM role"
  type        = string
}
