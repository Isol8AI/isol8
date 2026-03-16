# =============================================================================
# EFS Module - Variables
# =============================================================================

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "project" {
  description = "Project name"
  type        = string
  default     = "isol8"
}

variable "vpc_id" {
  description = "VPC ID where EFS resources are created"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for EFS mount targets"
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "List of security group IDs allowed to mount EFS (EC2 + Fargate SGs)"
  type        = list(string)
}

variable "kms_key_arn" {
  description = "KMS key ARN for EFS encryption at rest"
  type        = string
}
