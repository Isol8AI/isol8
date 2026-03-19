# =============================================================================
# IAM Module - Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key ARN for encryption at rest"
  type        = string
}

variable "secrets_arn_prefix" {
  description = "ARN prefix for Secrets Manager secrets"
  type        = string
}

variable "github_org" {
  description = "GitHub organization name"
  type        = string
  default     = ""
}

variable "github_repos" {
  description = "List of GitHub repository names to trust"
  type        = list(string)
  default     = []
}

variable "websocket_api_arn" {
  description = "WebSocket API execution ARN for Management API permissions"
  type        = string
  default     = ""
}

variable "ws_connections_table_arn" {
  description = "DynamoDB table ARN for WebSocket connections"
  type        = string
  default     = ""
}

variable "ecs_cluster_arn" {
  type    = string
  default = ""
}

variable "ecs_task_definition_arn" {
  type    = string
  default = ""
}

variable "efs_file_system_arn" {
  type    = string
  default = ""
}

variable "openclaw_config_bucket_arn" {
  description = "S3 bucket ARN for openclaw config storage"
  type        = string
  default     = ""
}

variable "cloud_map_namespace_arn" {
  type    = string
  default = ""
}

variable "cloud_map_service_arn" {
  type    = string
  default = ""
}
