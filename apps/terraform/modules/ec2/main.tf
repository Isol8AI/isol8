# =============================================================================
# EC2 Module - Application Instances
# =============================================================================
# Creates EC2 instances for FastAPI backend control plane.
# User containers run on ECS Fargate; EC2 mounts EFS for workspace access.
# Uses Auto Scaling Group for high availability and rolling deployments.
# =============================================================================

data "aws_ami" "amazon_linux_2" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------
resource "aws_security_group" "ec2" {
  name        = "${var.project}-${var.environment}-ec2-sg"
  description = "Security group for EC2 instances"
  vpc_id      = var.vpc_id

  # Allow inbound from ALB
  ingress {
    description     = "HTTP from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
  }

  # Allow inbound from NLB (WebSocket traffic)
  # NLB doesn't use security groups - traffic comes from NLB IPs within VPC
  dynamic "ingress" {
    for_each = var.vpc_cidr != "" ? [1] : []
    content {
      description = "WebSocket from NLB"
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = [var.vpc_cidr]
    }
  }

  # Allow all outbound (for HuggingFace API, etc.)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-ec2-sg"
  }
}

# -----------------------------------------------------------------------------
# Launch Template
# -----------------------------------------------------------------------------
resource "aws_launch_template" "main" {
  name_prefix   = "${var.project}-${var.environment}-"
  image_id      = data.aws_ami.amazon_linux_2.id
  instance_type = var.instance_type

  # IAM instance profile
  iam_instance_profile {
    name = var.instance_profile_name
  }

  # Network configuration
  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.ec2.id]
  }

  # Root volume
  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 100
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  # User data script
  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    project                       = var.project
    environment                   = var.environment
    secrets_arn_prefix            = var.secrets_arn_prefix
    aws_region                    = var.aws_region
    frontend_url                  = var.frontend_url
    ws_connections_table          = var.ws_connections_table
    ws_management_api_url         = var.ws_management_api_url
    stripe_metered_price_id       = var.stripe_metered_price_id
    stripe_meter_id               = var.stripe_meter_id
    container_execution_role_arn  = var.container_execution_role_arn
    ecs_cluster_arn               = var.ecs_cluster_arn
    ecs_task_definition           = var.ecs_task_definition
    ecs_subnets                   = var.ecs_subnets
    ecs_security_group_id         = var.ecs_security_group_id
    efs_file_system_id            = var.efs_file_system_id
    s3_config_bucket              = var.s3_config_bucket
    cloud_map_namespace_id        = var.cloud_map_namespace_id
    cloud_map_service_id          = var.cloud_map_service_id
    cloud_map_service_arn         = var.cloud_map_service_arn
    domain_name                   = var.domain_name
  }))

  # Metadata options (IMDSv2 required for security)
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2 # Allow Docker bridge containers to reach IMDS for credentials
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name    = "${var.project}-${var.environment}-instance"
      Project = var.project
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# Auto Scaling Group
# -----------------------------------------------------------------------------
resource "aws_autoscaling_group" "main" {
  name                = "${var.project}-${var.environment}-asg"
  vpc_zone_identifier = var.subnet_ids

  # Attach both ALB and NLB target groups
  # compact() removes empty strings, so if nlb_target_group_arn is not provided, it won't cause an error
  target_group_arns = compact([
    var.target_group_arn,     # ALB target group (HTTP API)
    var.nlb_target_group_arn, # NLB target group (WebSocket)
  ])

  min_size         = var.min_count
  max_size         = var.max_count
  desired_capacity = var.desired_count

  # Health check
  health_check_type         = "ELB"
  health_check_grace_period = 300

  # Launch template
  launch_template {
    id      = aws_launch_template.main.id
    version = "$Latest"
  }

  # Instance refresh for rolling deployments
  # Triggers on launch template changes (user_data, AMI, etc.)
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 60
    }
    triggers = ["launch_template"]
  }

  tag {
    key                 = "Name"
    value               = "${var.project}-${var.environment}-instance"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = var.project
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.environment
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}
