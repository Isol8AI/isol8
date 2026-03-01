#!/bin/bash
# =============================================================================
# EC2 User Data Script - Isol8 Backend
# =============================================================================
set -euo pipefail

# Variables from Terraform
PROJECT="${project}"
ENVIRONMENT="${environment}"
SECRETS_ARN_PREFIX="${secrets_arn_prefix}"
REGION="${aws_region}"
FRONTEND_URL="${frontend_url}"
TOWN_FRONTEND_URL="${town_frontend_url}"
WS_CONNECTIONS_TABLE="${ws_connections_table}"
WS_MANAGEMENT_API_URL="${ws_management_api_url}"

# Logging
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting Isol8 backend setup..."

# -----------------------------------------------------------------------------
# Install dependencies
# -----------------------------------------------------------------------------
yum update -y
yum install -y docker aws-cli jq

# Start Docker
systemctl start docker
systemctl enable docker

# Start SSM agent (pre-installed on Amazon Linux 2, needed for GitHub Actions deployments)
systemctl start amazon-ssm-agent
systemctl enable amazon-ssm-agent

# Add ec2-user to docker group
usermod -aG docker ec2-user

# -----------------------------------------------------------------------------
# Fetch secrets from Secrets Manager
# -----------------------------------------------------------------------------
echo "Fetching secrets from region: $REGION"

# Fetch secrets
DATABASE_URL=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}database_url" \
    --query 'SecretString' --output text)

HUGGINGFACE_TOKEN=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}huggingface_token" \
    --query 'SecretString' --output text)

CLERK_ISSUER=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}clerk_issuer" \
    --query 'SecretString' --output text)

CLERK_WEBHOOK_SECRET=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}clerk_webhook_secret" \
    --query 'SecretString' --output text)

OM_PG_DSN=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}openmemory_url" \
    --query 'SecretString' --output text)

STRIPE_SECRET_KEY=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}stripe_secret_key" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

STRIPE_WEBHOOK_SECRET=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}stripe_webhook_secret" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

BRAVE_API_KEY=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$${SECRETS_ARN_PREFIX}brave_api_key" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

# -----------------------------------------------------------------------------
# Create environment file
# -----------------------------------------------------------------------------
cat > /home/ec2-user/.env << EOF
DATABASE_URL=$DATABASE_URL
OM_METADATA_BACKEND=postgres
OM_PG_DSN=$OM_PG_DSN
OM_PG_SCHEMA=$ENVIRONMENT
HUGGINGFACE_TOKEN=$HUGGINGFACE_TOKEN
CLERK_ISSUER=$CLERK_ISSUER
CLERK_WEBHOOK_SECRET=$CLERK_WEBHOOK_SECRET
CORS_ORIGINS=$FRONTEND_URL,$TOWN_FRONTEND_URL
ENVIRONMENT=$ENVIRONMENT
DEBUG=false
WS_CONNECTIONS_TABLE=$WS_CONNECTIONS_TABLE
WS_MANAGEMENT_API_URL=$WS_MANAGEMENT_API_URL
AWS_REGION=$REGION
AWS_DEFAULT_REGION=$REGION
STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET
STRIPE_STARTER_FIXED_PRICE_ID=${stripe_starter_fixed_price_id}
STRIPE_PRO_FIXED_PRICE_ID=${stripe_pro_fixed_price_id}
STRIPE_METERED_PRICE_ID=${stripe_metered_price_id}
STRIPE_METER_ID=${stripe_meter_id}
FRONTEND_URL=$FRONTEND_URL
BRAVE_API_KEY=$BRAVE_API_KEY
CONTAINER_EXECUTION_ROLE_ARN=${container_execution_role_arn}
ECS_CLUSTER_ARN=${ecs_cluster_arn}
ECS_TASK_DEFINITION=${ecs_task_definition}
ECS_SUBNETS=${ecs_subnets}
ECS_SECURITY_GROUP_ID=${ecs_security_group_id}
EFS_MOUNT_PATH=/mnt/efs
S3_CONFIG_BUCKET=${s3_config_bucket}
CLOUD_MAP_NAMESPACE_ID=${cloud_map_namespace_id}
CLOUD_MAP_SERVICE_ID=${cloud_map_service_id}
CLOUD_MAP_SERVICE_ARN=${cloud_map_service_arn}
EOF

chmod 600 /home/ec2-user/.env
chown ec2-user:ec2-user /home/ec2-user/.env

# -----------------------------------------------------------------------------
# Login to ECR and pull images
# -----------------------------------------------------------------------------
echo "Pulling container images..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="$AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$PROJECT-backend"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker pull "$ECR_REPO:latest" || docker pull "$ECR_REPO:$ENVIRONMENT" || true

# -----------------------------------------------------------------------------
# Mount EFS for OpenClaw workspaces
# -----------------------------------------------------------------------------
echo "Mounting EFS..."
yum install -y amazon-efs-utils
mkdir -p /mnt/efs
for i in 1 2 3 4 5; do
  mount -t efs -o tls ${efs_file_system_id}:/ /mnt/efs && break
  echo "EFS mount attempt $i failed, retrying in 10s..."
  /bin/sleep 10
done
mountpoint -q /mnt/efs || { echo "FATAL: EFS mount failed after 5 attempts"; exit 1; }
chmod 1777 /mnt/efs
echo "${efs_file_system_id}:/ /mnt/efs efs _netdev,tls 0 0" >> /etc/fstab

# -----------------------------------------------------------------------------
# Start the application
# -----------------------------------------------------------------------------
echo "Starting application..."

# Create systemd service
cat > /etc/systemd/system/isol8.service << EOF
[Unit]
Description=Isol8 Backend
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=5
ExecStart=/usr/bin/docker run --rm \
    --name isol8 \
    --env-file /home/ec2-user/.env \
    -v /mnt/efs:/mnt/efs \
    --network=host \
    $ECR_REPO:latest

[Install]
WantedBy=multi-user.target
EOF

# Reload and start service
systemctl daemon-reload
systemctl enable isol8
systemctl start isol8

echo "Isol8 backend setup complete!"
