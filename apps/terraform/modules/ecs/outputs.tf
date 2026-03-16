# =============================================================================
# ECS Module - Outputs
# =============================================================================

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "task_definition_arn" {
  description = "ECS task definition ARN"
  value       = aws_ecs_task_definition.openclaw.arn
}

output "task_definition_family" {
  description = "ECS task definition family name"
  value       = aws_ecs_task_definition.openclaw.family
}

output "fargate_security_group_id" {
  description = "Security group ID for Fargate tasks"
  value       = aws_security_group.fargate_task.id
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name for OpenClaw tasks"
  value       = aws_cloudwatch_log_group.openclaw.name
}

output "cloud_map_namespace_id" {
  description = "Cloud Map private DNS namespace ID"
  value       = aws_service_discovery_private_dns_namespace.main.id
}

output "cloud_map_service_id" {
  description = "Cloud Map service ID for OpenClaw"
  value       = aws_service_discovery_service.openclaw.id
}

output "cloud_map_service_arn" {
  description = "Cloud Map service ARN for OpenClaw"
  value       = aws_service_discovery_service.openclaw.arn
}
