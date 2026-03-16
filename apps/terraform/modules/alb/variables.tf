# =============================================================================
# ALB Module - Variables
# =============================================================================

variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block for security group rules"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for ALB"
  type        = list(string)
}

variable "idle_timeout" {
  description = "Idle timeout in seconds (300 for SSE streaming)"
  type        = number
  default     = 300
}

variable "health_check_path" {
  description = "Health check path"
  type        = string
  default     = "/health"
}

variable "health_check_interval" {
  description = "Health check interval in seconds"
  type        = number
  default     = 30
}

variable "health_check_timeout" {
  description = "Health check timeout in seconds"
  type        = number
  default     = 10
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS (required)"
  type        = string
}

variable "enable_https" {
  description = "Enable HTTPS listener"
  type        = bool
  default     = true
}
