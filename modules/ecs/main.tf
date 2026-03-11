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
      user             = "0:0"
      workingDirectory = "/home/node"
      command = [
        "sh", "-c",
        "apt-get update -qq && apt-get install -y -qq socat python3-pip > /dev/null 2>&1; pip install --break-system-packages websockets > /dev/null 2>&1; export NPM_CONFIG_PREFIX=/home/node/.npm-global && export PATH=$NPM_CONFIG_PREFIX/bin:$PATH && npm i -g --ignore-scripts mcporter clawhub openai 2>/dev/null; GH_VER=2.65.0 && wget -qO- https://github.com/cli/cli/releases/download/v$${GH_VER}/gh_$${GH_VER}_linux_amd64.tar.gz | tar xz -C /tmp && cp /tmp/gh_$${GH_VER}_linux_amd64/bin/gh $NPM_CONFIG_PREFIX/bin/gh 2>/dev/null; wget -qO- https://astral.sh/uv/install.sh | HOME=/home/node sh 2>/dev/null && export PATH=/home/node/.local/bin:$PATH; clawhub install markdown-converter --no-input 2>/dev/null; exec node /app/openclaw.mjs gateway --port 18789 --bind lan"
      ]

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
          name  = "HOME"
          value = "/home/node"
        },
        {
          name  = "NPM_CONFIG_PREFIX"
          value = "/home/node/.npm-global"
        },
        {
          name  = "PATH"
          value = "/home/node/.local/bin:/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        },
        {
          name  = "AWS_REGION"
          value = "us-east-1"
        },
        {
          name  = "AWS_DEFAULT_REGION"
          value = "us-east-1"
        },
        {
          name  = "NODE_PATH"
          value = "/home/node/.npm-global/lib/node_modules"
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

      healthCheck = {
        command     = ["CMD-SHELL", "node /app/openclaw.mjs gateway status --json | node -e \"process.stdin.on('data',d=>{try{const s=JSON.parse(d);process.exit(s.port&&s.port.status==='busy'?0:1)}catch{process.exit(1)}})\""]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
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
