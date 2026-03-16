# =============================================================================
# ACM Module - Outputs
# =============================================================================

output "certificate_arn" {
  description = "ARN of the ACM certificate"
  value       = aws_acm_certificate_validation.main.certificate_arn
}

output "certificate_domain" {
  description = "Primary domain of the certificate"
  value       = aws_acm_certificate.main.domain_name
}
