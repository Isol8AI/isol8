# =============================================================================
# EFS Module - Persistent Storage for OpenClaw Workspaces
# =============================================================================
# Creates an EFS file system for OpenClaw agent workspace persistence.
# Shared between the EC2 control plane (reads agent files directly) and
# Fargate tasks (OpenClaw workspace data). The access point UID/GID 1000
# matches ec2-user so the control plane can write config files to EFS.
# Containers run as root (user 0:0) but per-user access points remap
# UID to 1000 for EFS operations — root can still read UID 1000 files.
# =============================================================================

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------
resource "aws_security_group" "efs" {
  name        = "${var.project}-${var.environment}-efs-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project}-${var.environment}-efs-sg"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Security Group Rules - NFS ingress from each allowed SG
# -----------------------------------------------------------------------------
resource "aws_security_group_rule" "efs_ingress" {
  count = length(var.allowed_security_group_ids)

  type                     = "ingress"
  description              = "NFS from allowed security group ${count.index}"
  from_port                = 2049
  to_port                  = 2049
  protocol                 = "tcp"
  security_group_id        = aws_security_group.efs.id
  source_security_group_id = var.allowed_security_group_ids[count.index]
}

# -----------------------------------------------------------------------------
# EFS File System
# -----------------------------------------------------------------------------
resource "aws_efs_file_system" "main" {
  encrypted        = true
  kms_key_id       = var.kms_key_arn
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name        = "${var.project}-${var.environment}-efs"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# EFS Access Point - OpenClaw workspaces
# -----------------------------------------------------------------------------
resource "aws_efs_access_point" "openclaw" {
  file_system_id = aws_efs_file_system.main.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/users"

    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0755"
    }
  }

  tags = {
    Name        = "${var.project}-${var.environment}-efs-ap-openclaw"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# EFS Mount Targets - one per private subnet
# -----------------------------------------------------------------------------
resource "aws_efs_mount_target" "main" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}
