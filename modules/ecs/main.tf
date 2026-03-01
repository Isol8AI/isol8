# =============================================================================
# ECS Module - Fargate Cluster for Per-User OpenClaw Gateways
# =============================================================================
# Creates the ECS Fargate cluster, task definition, Cloud Map namespace, and
# supporting resources for per-subscriber OpenClaw gateway tasks. Each user
# gets their own ECS Service (created by the backend at subscription time)
# pointing to this shared task definition. Cloud Map auto-registers task
# private IPs so the EC2 control plane can discover and route to them.
# =============================================================================

# -----------------------------------------------------------------------------
# Cloud Map - Service Discovery
# -----------------------------------------------------------------------------
resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project}-${var.environment}.local"
  description = "Private DNS namespace for ${var.project} ${var.environment} service discovery"
  vpc         = var.vpc_id

  tags = {
    Name        = "${var.project}-${var.environment}-cloudmap-ns"
    Environment = var.environment
  }
}

resource "aws_service_discovery_service" "openclaw" {
  name = "openclaw"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name        = "${var.project}-${var.environment}-cloudmap-openclaw"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# ECS Cluster
# -----------------------------------------------------------------------------
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.environment}-openclaw"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name        = "${var.project}-${var.environment}-openclaw"
    Environment = var.environment
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# -----------------------------------------------------------------------------
# Security Group - Fargate Tasks
# -----------------------------------------------------------------------------
resource "aws_security_group" "fargate_task" {
  name        = "${var.project}-${var.environment}-fargate-task-sg"
  description = "Security group for OpenClaw Fargate tasks"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound (Bedrock, ECR, CloudWatch)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project}-${var.environment}-fargate-task-sg"
    Environment = var.environment
  }
}

resource "aws_security_group_rule" "fargate_ingress_from_control_plane" {
  type                     = "ingress"
  description              = "OpenClaw gateway port from EC2 control plane"
  from_port                = 18789
  to_port                  = 18789
  protocol                 = "tcp"
  security_group_id        = aws_security_group.fargate_task.id
  source_security_group_id = var.control_plane_security_group_id
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "openclaw" {
  name              = "/isol8/${var.environment}/openclaw"
  retention_in_days = 30

  tags = {
    Name        = "${var.project}-${var.environment}-openclaw-logs"
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# ECS Task Definition
# -----------------------------------------------------------------------------
resource "aws_ecs_task_definition" "openclaw" {
  family                   = "${var.project}-${var.environment}-openclaw"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  volume {
    name = "openclaw-workspace"

    efs_volume_configuration {
      file_system_id     = var.efs_file_system_id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = var.efs_access_point_id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "openclaw"
      image     = var.openclaw_image
      essential = true

      # Config is written to EFS by the EC2 control plane and mounted
      # into the container at /home/node/.openclaw via per-user access
      # points. No inline config generation needed.
      command = ["node", "openclaw.mjs", "gateway", "--port", "18789", "--bind", "lan"]

      portMappings = [
        {
          containerPort = 18789
          protocol      = "tcp"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "openclaw-workspace"
          containerPath = "/home/node/.openclaw"
          readOnly      = false
        }
      ]

      # NOTE: GATEWAY_TOKEN is injected at service creation time via
      # container overrides in the backend EcsManager, not here.
      environment = [
        {
          name  = "AWS_REGION"
          value = "us-east-1"
        },
        {
          name  = "AWS_DEFAULT_REGION"
          value = "us-east-1"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.openclaw.name
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "openclaw"
        }
      }

      linuxParameters = {
        initProcessEnabled = true
      }
    }
  ])

  tags = {
    Name        = "${var.project}-${var.environment}-openclaw-task"
    Environment = var.environment
  }
}
