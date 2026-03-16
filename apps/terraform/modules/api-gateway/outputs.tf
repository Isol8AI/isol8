# =============================================================================
# API Gateway Module - Outputs
# =============================================================================

output "api_id" {
  description = "API Gateway ID"
  value       = aws_apigatewayv2_api.main.id
}

output "api_endpoint" {
  description = "API Gateway invoke URL"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "custom_domain_name" {
  description = "Custom domain regional domain name (for Route53)"
  value       = var.domain_name != "" ? aws_apigatewayv2_domain_name.main[0].domain_name_configuration[0].target_domain_name : null
}

output "custom_domain_zone_id" {
  description = "Custom domain hosted zone ID (for Route53)"
  value       = var.domain_name != "" ? aws_apigatewayv2_domain_name.main[0].domain_name_configuration[0].hosted_zone_id : null
}

output "stage_id" {
  description = "API Gateway stage ID"
  value       = aws_apigatewayv2_stage.main.id
}

output "vpc_link_id" {
  description = "VPC Link ID (for sharing with WebSocket API)"
  value       = aws_apigatewayv2_vpc_link.main.id
}
