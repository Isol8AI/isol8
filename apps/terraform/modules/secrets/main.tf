# =============================================================================
# Secrets Manager Module
# =============================================================================
# Stores application secrets encrypted with the KMS key.
# =============================================================================

# -----------------------------------------------------------------------------
# Secrets
# -----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "main" {
  for_each = var.secrets

  name       = "${var.project}/${var.environment}/${each.key}"
  kms_key_id = var.kms_key_arn

  tags = {
    Name = "${var.project}-${var.environment}-${each.key}"
  }
}

resource "aws_secretsmanager_secret_version" "main" {
  for_each = var.secrets

  secret_id     = aws_secretsmanager_secret.main[each.key].id
  secret_string = each.value != "" ? each.value : "not-configured"
}

