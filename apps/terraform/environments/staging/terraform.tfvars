# =============================================================================
# Staging Environment Configuration (Isol8)
# =============================================================================

environment = "staging"
aws_region  = "us-east-1"

# VPC
vpc_cidr           = "10.1.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b"]

# EC2 (DISABLED - instances stopped to save costs during development)
ec2_instance_type = "m5.xlarge"
ec2_desired_count = 0
ec2_min_count     = 0
ec2_max_count     = 0

# Domain
domain_name       = "api-staging.isol8.co"
root_domain       = "isol8.co"
frontend_url      = "https://staging.isol8.co"
town_frontend_url = "https://staging.town.isol8.co"

# Clerk (production Clerk with custom domain)
clerk_issuer = "https://clerk.isol8.co"

# GitHub (for CI/CD OIDC)
github_org   = "Isol8AI"
github_repos = ["backend", "terraform"]
