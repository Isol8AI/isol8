# =============================================================================
# IAM Module - Outputs
# =============================================================================

output "ec2_role_arn" {
  description = "EC2 IAM role ARN"
  value       = aws_iam_role.ec2.arn
}

output "ec2_role_name" {
  description = "EC2 IAM role name"
  value       = aws_iam_role.ec2.name
}

output "ec2_instance_profile_name" {
  description = "EC2 instance profile name"
  value       = aws_iam_instance_profile.ec2.name
}

output "ec2_instance_profile_arn" {
  description = "EC2 instance profile ARN"
  value       = aws_iam_instance_profile.ec2.arn
}

output "github_actions_role_arn" {
  description = "GitHub Actions IAM role ARN"
  value       = length(aws_iam_role.github_actions) > 0 ? aws_iam_role.github_actions[0].arn : ""
}

output "container_execution_role_arn" {
  description = "IAM role ARN for container Bedrock access (assumed via STS)"
  value       = aws_iam_role.container_execution.arn
}

output "ecs_task_execution_role_arn" {
  description = "ECS task execution role ARN (Fargate image pull + CloudWatch logs)"
  value       = aws_iam_role.ecs_task_execution.arn
}

output "ecs_task_role_arn" {
  description = "ECS task role ARN (OpenClaw container runtime permissions)"
  value       = aws_iam_role.ecs_task.arn
}
