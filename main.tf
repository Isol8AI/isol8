# =============================================================================
# Isol8 Infrastructure - Main Configuration
# =============================================================================
# This file wires together all modules for the Isol8 backend infrastructure.
#
# Architecture:
#   Vercel (Frontend) → API Gateway → ALB → EC2 (FastAPI + per-user containers)
# =============================================================================

# -----------------------------------------------------------------------------
# VPC Module
# -----------------------------------------------------------------------------
module "vpc" {
  source = "./modules/vpc"

  project            = "isol8"
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

# -----------------------------------------------------------------------------
# KMS Module (Encryption at Rest)
# -----------------------------------------------------------------------------
module "kms" {
  source = "./modules/kms"

  project      = "isol8"
  environment  = var.environment
  ec2_role_arn = module.iam.ec2_role_arn
}

# -----------------------------------------------------------------------------
# Secrets Manager Module
# -----------------------------------------------------------------------------
# Database URL with schema per environment
# Format: postgresql+asyncpg://...?options=-csearch_path%3D{env}
locals {
  # Append schema to connection string (URL-encoded: %3D is =)
  # If connection string already has ?, append with &, otherwise add ?
  db_has_query = length(regexall("\\?", var.supabase_connection_string)) > 0
  db_separator = local.db_has_query ? "&" : "?"
  database_url = "${var.supabase_connection_string}${local.db_separator}options=-csearch_path%3D${var.environment}"

  # OpenMemory uses standard psycopg format (without +asyncpg)
  # Convert asyncpg URL to standard PostgreSQL URL for OpenMemory
  openmemory_base = replace(var.supabase_connection_string, "postgresql+asyncpg://", "postgresql://")
  openmemory_url  = "${local.openmemory_base}${local.db_separator}options=-csearch_path%3D${var.environment}"
}

module "secrets" {
  source = "./modules/secrets"

  project     = "isol8"
  environment = var.environment
  kms_key_arn = module.kms.key_arn

  # Secrets to store (encrypted with KMS key)
  secrets = {
    database_url          = local.database_url
    openmemory_url        = local.openmemory_url
    huggingface_token     = var.huggingface_token
    clerk_issuer          = var.clerk_issuer
    clerk_secret_key      = var.clerk_secret_key
    clerk_webhook_secret  = var.clerk_webhook_secret
    stripe_secret_key     = var.stripe_secret_key
    stripe_webhook_secret = var.stripe_webhook_secret
    perplexity_api_key    = var.perplexity_api_key
    encryption_key        = var.encryption_key
    pixellab_api_key      = var.pixellab_api_key
  }
}

# --- S3 bucket for OpenClaw configuration ---

resource "aws_s3_bucket" "openclaw_configs" {
  bucket = "isol8-${var.environment}-openclaw-configs"

  tags = {
    Name        = "isol8-${var.environment}-openclaw-configs"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "openclaw_configs" {
  bucket = aws_s3_bucket.openclaw_configs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "openclaw_configs" {
  bucket = aws_s3_bucket.openclaw_configs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = module.kms.key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "openclaw_configs" {
  bucket                  = aws_s3_bucket.openclaw_configs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# S3 + CloudFront for GooseTown Sprite Assets
# -----------------------------------------------------------------------------
# Serves AI-generated agent sprites via CDN at assets.town.isol8.co
# S3 bucket is private; CloudFront OAI provides read access.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "town_sprites" {
  bucket = "isol8-${var.environment}-town-sprites"

  tags = {
    Name        = "isol8-${var.environment}-town-sprites"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_cors_configuration" "town_sprites" {
  bucket = aws_s3_bucket.town_sprites.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    max_age_seconds = 86400
  }
}

resource "aws_s3_bucket_public_access_block" "town_sprites" {
  bucket                  = aws_s3_bucket.town_sprites.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_identity" "town_sprites" {
  comment = "OAI for isol8-${var.environment}-town-sprites"
}

resource "aws_s3_bucket_policy" "town_sprites" {
  bucket = aws_s3_bucket.town_sprites.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontOAI"
        Effect    = "Allow"
        Principal = {
          AWS = aws_cloudfront_origin_access_identity.town_sprites.iam_arn
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.town_sprites.arn}/*"
      }
    ]
  })
}

resource "aws_cloudfront_response_headers_policy" "town_sprites_cors" {
  count = var.town_assets_cert_arn != "" ? 1 : 0
  name  = "isol8-${var.environment}-town-sprites-cors"

  cors_config {
    access_control_allow_origins {
      items = ["*"]
    }
    access_control_allow_methods {
      items = ["GET", "HEAD"]
    }
    access_control_allow_headers {
      items = ["*"]
    }
    access_control_allow_credentials = false
    access_control_max_age_sec       = 86400
    origin_override                  = true
  }
}

resource "aws_cloudfront_distribution" "town_sprites" {
  count = var.town_assets_cert_arn != "" ? 1 : 0

  enabled             = true
  is_ipv6_enabled     = true
  comment             = "GooseTown sprite assets (${var.environment})"
  default_root_object = ""

  aliases = ["assets.town.${var.root_domain}"]

  origin {
    domain_name = aws_s3_bucket.town_sprites.bucket_regional_domain_name
    origin_id   = "S3-town-sprites"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.town_sprites.cloudfront_access_identity_path
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-town-sprites"
    viewer_protocol_policy = "redirect-to-https"

    response_headers_policy_id = aws_cloudfront_response_headers_policy.town_sprites_cors[0].id

    forwarded_values {
      query_string = false
      headers      = ["Origin", "Access-Control-Request-Method", "Access-Control-Request-Headers"]
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 31536000
    compress    = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.town_assets_cert_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Name        = "isol8-${var.environment}-town-sprites-cdn"
    Environment = var.environment
  }
}

# Route53 A record: assets.town.isol8.co → CloudFront
resource "aws_route53_record" "town_sprites_cdn" {
  count   = var.town_assets_cert_arn != "" ? 1 : 0
  zone_id = var.town_zone_id != "" ? var.town_zone_id : data.aws_route53_zone.main.zone_id
  name    = "assets.town.${var.root_domain}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.town_sprites[0].domain_name
    zone_id                = aws_cloudfront_distribution.town_sprites[0].hosted_zone_id
    evaluate_target_health = false
  }
}

# -----------------------------------------------------------------------------
# EFS Module (Shared storage for OpenClaw workspaces)
# -----------------------------------------------------------------------------
module "efs" {
  source = "./modules/efs"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  kms_key_arn        = module.kms.key_arn

  allowed_security_group_ids = [
    module.ec2.security_group_id,
    module.ecs.fargate_security_group_id,
  ]
}

# -----------------------------------------------------------------------------
# ECS Module (Fargate cluster for per-user OpenClaw gateways)
# -----------------------------------------------------------------------------
module "ecs" {
  source = "./modules/ecs"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  control_plane_security_group_id = module.ec2.security_group_id
  efs_file_system_id              = module.efs.file_system_id
  efs_access_point_id             = module.efs.access_point_id
  task_execution_role_arn         = module.iam.ecs_task_execution_role_arn
  task_role_arn                   = module.iam.ecs_task_role_arn
}

# -----------------------------------------------------------------------------
# IAM Module
# -----------------------------------------------------------------------------
module "iam" {
  source = "./modules/iam"

  project            = "isol8"
  environment        = var.environment
  kms_key_arn        = module.kms.key_arn
  secrets_arn_prefix = module.secrets.secrets_arn_prefix

  # GitHub OIDC for CI/CD
  github_org   = var.github_org
  github_repos = var.github_repos

  # WebSocket permissions
  websocket_api_arn        = module.websocket_api.execution_arn
  ws_connections_table_arn = module.websocket_api.connections_table_arn

  # ECS/EFS/S3 permissions
  ecs_cluster_arn            = module.ecs.cluster_arn
  ecs_task_definition_arn    = module.ecs.task_definition_arn
  efs_file_system_arn        = module.efs.file_system_arn
  openclaw_config_bucket_arn = aws_s3_bucket.openclaw_configs.arn

  # GooseTown sprite assets
  sprite_s3_bucket_name = "isol8-${var.environment}-town-sprites"
}

# -----------------------------------------------------------------------------
# ACM Module (SSL Certificate)
# -----------------------------------------------------------------------------
module "acm" {
  source = "./modules/acm"

  project     = "isol8"
  environment = var.environment
  domain_name = var.domain_name
  root_domain = var.root_domain

  # Wildcard for all subdomains
  subject_alternative_names = ["*.${var.root_domain}"]
}

# -----------------------------------------------------------------------------
# ALB Module (Internal - only accessible via API Gateway)
# -----------------------------------------------------------------------------
module "alb" {
  source = "./modules/alb"

  project     = "isol8"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  vpc_cidr    = module.vpc.vpc_cidr
  subnet_ids  = module.vpc.private_subnet_ids # Internal ALB in private subnets

  # 300s timeout for long-running SSE streaming requests
  idle_timeout = 300

  # Health check configuration
  health_check_path     = "/health"
  health_check_interval = 30
  health_check_timeout  = 10

  # SSL certificate
  certificate_arn = module.acm.certificate_arn
  enable_https    = true
}

# -----------------------------------------------------------------------------
# NLB Module (for WebSocket VPC Link V1)
# -----------------------------------------------------------------------------
# VPC Link V1 (required for WebSocket APIs) only supports NLB targets.
# This NLB handles WebSocket traffic alongside the ALB for HTTP traffic.
# -----------------------------------------------------------------------------
module "nlb" {
  source = "./modules/nlb"

  project     = "isol8"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  subnet_ids  = module.vpc.private_subnet_ids
}

# -----------------------------------------------------------------------------
# API Gateway Module (Public entry point)
# -----------------------------------------------------------------------------
module "api_gateway" {
  source = "./modules/api-gateway"

  project     = "isol8"
  environment = var.environment
  subnet_ids  = module.vpc.private_subnet_ids

  # ALB integration (HTTP for internal VPC Link - API Gateway handles public TLS)
  alb_listener_arn      = module.alb.http_listener_arn
  alb_security_group_id = module.alb.security_group_id

  # CORS - allow frontend origins
  cors_allow_origins = compact([var.frontend_url, var.town_frontend_url])

  # Custom domain
  domain_name     = var.domain_name
  certificate_arn = module.acm.certificate_arn

  # Rate limiting
  throttling_burst_limit = 1000
  throttling_rate_limit  = 500
}

# -----------------------------------------------------------------------------
# WebSocket API Gateway (for streaming - avoids HTTP API buffering)
# -----------------------------------------------------------------------------
module "websocket_api" {
  source = "./modules/websocket-api"

  project     = "isol8"
  environment = var.environment

  # Custom domain (ws-{env}.isol8.co)
  domain_name     = "ws-${var.environment}.${var.root_domain}"
  certificate_arn = module.acm.certificate_arn

  # NLB for VPC Link V1 (required for WebSocket APIs)
  nlb_arn      = module.nlb.arn
  nlb_dns_name = module.nlb.dns_name

  # Clerk configuration for JWT validation
  clerk_jwks_url = var.clerk_jwks_url
  clerk_issuer   = var.clerk_issuer

  # Shared secret for HMAC-signed town agent tokens
  town_token_secret = var.town_token_secret
}

# -----------------------------------------------------------------------------
# Route53 DNS Records
# -----------------------------------------------------------------------------
data "aws_route53_zone" "main" {
  name         = var.root_domain
  private_zone = false
}

# HTTP API record (api-{env}.isol8.co)
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = module.api_gateway.custom_domain_name
    zone_id                = module.api_gateway.custom_domain_zone_id
    evaluate_target_health = false
  }
}

# WebSocket API record (ws-{env}.isol8.co)
resource "aws_route53_record" "websocket" {
  count   = module.websocket_api.custom_domain != null ? 1 : 0
  zone_id = data.aws_route53_zone.main.zone_id
  name    = module.websocket_api.custom_domain
  type    = "A"

  alias {
    name                   = module.websocket_api.custom_domain_target
    zone_id                = module.websocket_api.custom_domain_zone_id
    evaluate_target_health = false
  }
}

# -----------------------------------------------------------------------------
# EC2 Module
# -----------------------------------------------------------------------------
module "ec2" {
  source = "./modules/ec2"

  project       = "isol8"
  environment   = var.environment
  aws_region    = var.aws_region
  vpc_id        = module.vpc.vpc_id
  subnet_ids    = module.vpc.private_subnet_ids
  instance_type = var.ec2_instance_type

  # Auto Scaling
  desired_count = var.ec2_desired_count
  min_count     = var.ec2_min_count
  max_count     = var.ec2_max_count

  # IAM
  instance_profile_name = module.iam.ec2_instance_profile_name

  # ALB (for HTTP API)
  target_group_arn      = module.alb.target_group_arn
  alb_security_group_id = module.alb.security_group_id

  # NLB (for WebSocket)
  nlb_target_group_arn = module.nlb.target_group_arn
  vpc_cidr             = module.vpc.vpc_cidr

  # Secrets
  secrets_arn_prefix = module.secrets.secrets_arn_prefix

  # CORS
  frontend_url      = var.frontend_url
  town_frontend_url = var.town_frontend_url

  # WebSocket
  ws_connections_table  = module.websocket_api.connections_table_name
  ws_management_api_url = module.websocket_api.management_api_url

  # GooseTown
  town_token_secret = var.town_token_secret

  # Stripe billing
  stripe_starter_fixed_price_id = var.stripe_starter_fixed_price_id
  stripe_pro_fixed_price_id     = var.stripe_pro_fixed_price_id
  stripe_metered_price_id       = var.stripe_metered_price_id
  stripe_meter_id               = var.stripe_meter_id

  # Container credential vending
  container_execution_role_arn = module.iam.container_execution_role_arn

  # ECS Fargate integration
  ecs_cluster_arn        = module.ecs.cluster_arn
  ecs_task_definition    = module.ecs.task_definition_family
  ecs_subnets            = join(",", module.vpc.private_subnet_ids)
  ecs_security_group_id  = module.ecs.fargate_security_group_id
  efs_file_system_id     = module.efs.file_system_id
  s3_config_bucket       = aws_s3_bucket.openclaw_configs.id
  cloud_map_namespace_id = module.ecs.cloud_map_namespace_id
  cloud_map_service_id   = module.ecs.cloud_map_service_id
  cloud_map_service_arn  = module.ecs.cloud_map_service_arn
  domain_name            = var.domain_name

  # GooseTown sprite assets
  sprite_s3_bucket = aws_s3_bucket.town_sprites.id
  sprite_cdn_url   = var.town_assets_cert_arn != "" ? "https://assets.town.${var.root_domain}" : ""
}
