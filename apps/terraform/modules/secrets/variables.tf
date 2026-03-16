# =============================================================================
# Secrets Manager Module - Variables
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
  description = "KMS key ARN for encryption"
  type        = string
}

variable "secrets" {
  description = "Map of secret names to values"
  type        = map(string)
  default     = {}
  # Note: Values are sensitive but keys are not (they're just names like 'database_url')
  # The actual secret values are protected by Secrets Manager encryption
}
