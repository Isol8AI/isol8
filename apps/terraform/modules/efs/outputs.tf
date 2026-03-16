# =============================================================================
# EFS Module - Outputs
# =============================================================================

output "file_system_id" {
  description = "EFS file system ID"
  value       = aws_efs_file_system.main.id
}

output "file_system_arn" {
  description = "EFS file system ARN"
  value       = aws_efs_file_system.main.arn
}

output "access_point_id" {
  description = "EFS access point ID for OpenClaw workspaces"
  value       = aws_efs_access_point.openclaw.id
}

output "access_point_arn" {
  description = "EFS access point ARN for OpenClaw workspaces"
  value       = aws_efs_access_point.openclaw.arn
}

output "security_group_id" {
  description = "EFS security group ID"
  value       = aws_security_group.efs.id
}
