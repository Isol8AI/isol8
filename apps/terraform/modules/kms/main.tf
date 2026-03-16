# =============================================================================
# KMS Module - Encryption at Rest
# =============================================================================
# Creates a KMS key used for encrypting secrets and data at rest.
# The EC2 role is granted encrypt/decrypt permissions.
# =============================================================================

data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# KMS Key
# -----------------------------------------------------------------------------
resource "aws_kms_key" "main" {
  description             = "KMS key for Isol8 encryption at rest"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowRootFullAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowEC2Encrypt"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["kms:Encrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext"]
        Resource  = "*"
      },
      {
        Sid       = "AllowEC2Decrypt"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["kms:Decrypt"]
        Resource  = "*"
      }
    ]
  })

  tags = {
    Name = "${var.project}-${var.environment}-key"
  }
}

# -----------------------------------------------------------------------------
# KMS Alias
# -----------------------------------------------------------------------------
resource "aws_kms_alias" "main" {
  name          = "alias/${var.project}-${var.environment}"
  target_key_id = aws_kms_key.main.key_id
}
