# =============================================================================
# ACM Module - SSL/TLS Certificate
# =============================================================================
# Creates an ACM certificate with DNS validation via Route53.
# Supports wildcard certificates for all subdomains.
# =============================================================================

# -----------------------------------------------------------------------------
# ACM Certificate
# -----------------------------------------------------------------------------
resource "aws_acm_certificate" "main" {
  domain_name               = var.domain_name
  subject_alternative_names = var.subject_alternative_names
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "${var.project}-${var.environment}-cert"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Route53 DNS Validation Records
# -----------------------------------------------------------------------------
data "aws_route53_zone" "main" {
  name         = var.root_domain
  private_zone = false
}

resource "aws_route53_record" "validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main.zone_id
}

# -----------------------------------------------------------------------------
# Certificate Validation
# -----------------------------------------------------------------------------
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
