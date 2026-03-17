# =============================================================================
# Dev Environment Configuration
# =============================================================================

environment = "dev"
aws_region  = "us-east-1"

# VPC
vpc_cidr           = "10.0.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b"]

# EC2
ec2_instance_type = "r5.xlarge"
ec2_desired_count = 1
ec2_min_count     = 1
ec2_max_count     = 2

# Domain
domain_name       = "api-dev.isol8.co"
root_domain       = "isol8.co"
frontend_url      = "https://dev.isol8.co"
town_frontend_url = "https://dev.town.isol8.co"

# Clerk (using production Clerk with custom domain)
clerk_issuer   = "https://clerk.isol8.co"
clerk_jwks_url = "https://clerk.isol8.co/.well-known/jwks.json"

# GitHub (for CI/CD OIDC) - trust both backend and terraform repos
github_org   = "Isol8AI"
github_repos = ["backend", "terraform", "isol8"]

# Stripe billing (test mode)
stripe_starter_fixed_price_id = "price_1TBm0NI54BysGS3r57fcRXOJ"
stripe_pro_fixed_price_id     = "price_1TBm0PI54BysGS3rFjUOtmrR"
stripe_metered_price_id       = "price_1TBm0fI54BysGS3rrqTaZ5Zz"
stripe_meter_id               = "mtr_test_61UL9xth9m1qTEaXv41I54BysGS3rJCC"

# GooseTown sprite CDN (CloudFront + S3)
town_assets_cert_arn = "arn:aws:acm:us-east-1:877352799272:certificate/24b2c113-a8ec-4d72-84af-044807ff8d87"

# =============================================================================
# SENSITIVE VALUES - Set via environment variables, not in this file!
# =============================================================================
# export TF_VAR_supabase_connection_string="postgresql://..."
# export TF_VAR_huggingface_token="hf_..."
# export TF_VAR_clerk_webhook_secret="whsec_..."
# =============================================================================
