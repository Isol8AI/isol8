# =============================================================================
# ALB Module - Outputs
# =============================================================================

output "arn" {
  description = "ALB ARN"
  value       = aws_lb.main.arn
}

output "dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.main.dns_name
}

output "zone_id" {
  description = "ALB hosted zone ID"
  value       = aws_lb.main.zone_id
}

output "target_group_arn" {
  description = "Target group ARN"
  value       = aws_lb_target_group.main.arn
}

output "security_group_id" {
  description = "ALB security group ID"
  value       = aws_security_group.alb.id
}

output "https_listener_arn" {
  description = "HTTPS listener ARN (for API Gateway integration)"
  value       = var.enable_https ? aws_lb_listener.https[0].arn : null
}

output "http_listener_arn" {
  description = "HTTP listener ARN (for API Gateway VPC Link integration)"
  value       = aws_lb_listener.http.arn
}
