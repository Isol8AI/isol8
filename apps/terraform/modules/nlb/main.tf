# =============================================================================
# NLB Module - Network Load Balancer for WebSocket API
# =============================================================================
# Creates an internal NLB for WebSocket API Gateway VPC Link V1 integration.
# VPC Link V1 (required for WebSocket APIs) only supports NLB targets.
#
# Architecture:
#   WebSocket API Gateway → VPC Link V1 → NLB → EC2:8000
# =============================================================================

# -----------------------------------------------------------------------------
# Network Load Balancer
# -----------------------------------------------------------------------------
resource "aws_lb" "websocket" {
  name               = "${var.project}-${var.environment}-ws-nlb"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.subnet_ids

  # Enable cross-zone load balancing for better distribution
  enable_cross_zone_load_balancing = true

  tags = {
    Name        = "${var.project}-${var.environment}-ws-nlb"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Target Group
# -----------------------------------------------------------------------------
resource "aws_lb_target_group" "websocket" {
  name        = "${var.project}-${var.environment}-ws-tg"
  port        = 8000
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 30
  }

  tags = {
    Name        = "${var.project}-${var.environment}-ws-tg"
    Project     = var.project
    Environment = var.environment
  }
}

# -----------------------------------------------------------------------------
# Listener
# -----------------------------------------------------------------------------
resource "aws_lb_listener" "websocket" {
  load_balancer_arn = aws_lb.websocket.arn
  port              = 80
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.websocket.arn
  }
}
