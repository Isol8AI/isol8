# =============================================================================
# ECS Module - Variables
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
  description = "VPC ID where ECS resources are created"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for Fargate tasks"
  type        = list(string)
}

variable "control_plane_security_group_id" {
  description = "EC2 control plane security group ID allowed to reach Fargate on 18789"
  type        = string
}

variable "efs_file_system_id" {
  description = "EFS file system ID for OpenClaw workspace persistence"
  type        = string
}

variable "efs_access_point_id" {
  description = "EFS access point ID for OpenClaw workspaces"
  type        = string
}

variable "task_execution_role_arn" {
  description = "IAM role ARN for ECS task execution (ECR pull, CloudWatch logs)"
  type        = string
}

variable "task_role_arn" {
  description = "IAM role ARN for the running ECS task (Bedrock, EFS access)"
  type        = string
}

variable "openclaw_image" {
  description = "Docker image for the OpenClaw gateway container"
  type        = string
  default     = "ghcr.io/openclaw/openclaw:latest"
}

variable "task_cpu" {
  description = "CPU units for the Fargate task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory in MiB for the Fargate task (2048 = 2 GB)"
  type        = number
  default     = 2048
}
