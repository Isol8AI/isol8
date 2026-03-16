# =============================================================================
# NLB Module - Outputs
# =============================================================================

output "arn" {
  description = "NLB ARN (for VPC Link V1)"
  value       = aws_lb.websocket.arn
}

output "dns_name" {
  description = "NLB DNS name (for API Gateway integration URI)"
  value       = aws_lb.websocket.dns_name
}

output "target_group_arn" {
  description = "Target group ARN (for ASG attachment)"
  value       = aws_lb_target_group.websocket.arn
}

output "zone_id" {
  description = "NLB hosted zone ID"
  value       = aws_lb.websocket.zone_id
}
