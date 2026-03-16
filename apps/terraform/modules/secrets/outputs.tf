# =============================================================================
# Secrets Manager Module - Outputs
# =============================================================================

output "secrets_arn_prefix" {
  description = "ARN prefix for secrets"
  value       = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/${var.environment}/"
}

output "secret_arns" {
  description = "Map of secret names to ARNs"
  value       = { for k, v in aws_secretsmanager_secret.main : k => v.arn }
}

# Data sources for ARN construction
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
