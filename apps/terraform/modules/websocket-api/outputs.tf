# =============================================================================
# WebSocket API Module - Outputs
# =============================================================================

output "api_id" {
  description = "WebSocket API Gateway ID"
  value       = aws_apigatewayv2_api.websocket.id
}

output "api_endpoint" {
  description = "WebSocket API Gateway endpoint URL (default stage)"
  value       = aws_apigatewayv2_api.websocket.api_endpoint
}

output "stage_name" {
  description = "Deployed stage name"
  value       = aws_apigatewayv2_stage.main.name
}

output "stage_id" {
  description = "Deployed stage ID"
  value       = aws_apigatewayv2_stage.main.id
}

output "execution_arn" {
  description = "Execution ARN for API Gateway (used for Lambda permissions)"
  value       = aws_apigatewayv2_api.websocket.execution_arn
}

# Custom domain outputs (only available if domain_name is provided)
output "custom_domain" {
  description = "Custom domain for WebSocket API"
  value       = var.domain_name != "" ? aws_apigatewayv2_domain_name.websocket[0].domain_name : null
}

output "custom_domain_target" {
  description = "Custom domain target domain name (for Route53 alias)"
  value       = var.domain_name != "" ? aws_apigatewayv2_domain_name.websocket[0].domain_name_configuration[0].target_domain_name : null
}

output "custom_domain_zone_id" {
  description = "Custom domain hosted zone ID (for Route53 alias)"
  value       = var.domain_name != "" ? aws_apigatewayv2_domain_name.websocket[0].domain_name_configuration[0].hosted_zone_id : null
}

output "websocket_url" {
  description = "Full WebSocket URL for client connections"
  value       = var.domain_name != "" ? "wss://${aws_apigatewayv2_domain_name.websocket[0].domain_name}" : "${aws_apigatewayv2_api.websocket.api_endpoint}/${aws_apigatewayv2_stage.main.name}"
}

# Lambda authorizer outputs
output "authorizer_function_name" {
  description = "Lambda authorizer function name"
  value       = aws_lambda_function.authorizer.function_name
}

output "authorizer_function_arn" {
  description = "Lambda authorizer function ARN"
  value       = aws_lambda_function.authorizer.arn
}

# DynamoDB connection state outputs
output "connections_table_name" {
  description = "DynamoDB table name for connection state"
  value       = aws_dynamodb_table.connections.name
}

output "connections_table_arn" {
  description = "DynamoDB table ARN for IAM policies"
  value       = aws_dynamodb_table.connections.arn
}

output "management_api_url" {
  description = "Management API URL for pushing messages to clients (HTTPS, not WSS)"
  # API Gateway Management API requires https:// not wss://
  # api_endpoint returns wss://, so we convert to https://
  value = replace("${aws_apigatewayv2_api.websocket.api_endpoint}/${aws_apigatewayv2_stage.main.name}", "wss://", "https://")
}

# VPC Link V1 output
output "vpc_link_v1_id" {
  description = "VPC Link V1 ID for WebSocket API"
  value       = aws_api_gateway_vpc_link.websocket.id
}
