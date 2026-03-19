#!/bin/bash
# =============================================================================
# EC2 User Data Script - Isol8 Backend
# =============================================================================
# Variables are injected by CDK via CloudFormation Fn::Sub.
# All ${VarName} placeholders are substituted at deploy time.
# =============================================================================
set -euo pipefail

# Variables from CDK (Fn::Sub)
PROJECT="${Project}"
ENVIRONMENT="${Environment}"
SECRETS_ARN_PREFIX="${SecretsArnPrefix}"
REGION="${Region}"
FRONTEND_URL="${FrontendUrl}"
WS_CONNECTIONS_TABLE="${WsConnectionsTable}"
WS_MANAGEMENT_API_URL="${WsManagementApiUrl}"

# Logging
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting Isol8 backend setup..."

# -----------------------------------------------------------------------------
# Install dependencies
# -----------------------------------------------------------------------------
dnf update -y
dnf install -y docker aws-cli jq amazon-efs-utils

# Start Docker
systemctl start docker
systemctl enable docker

# Start SSM agent (pre-installed on Amazon Linux 2023)
systemctl start amazon-ssm-agent
systemctl enable amazon-ssm-agent

# Add ec2-user to docker group
usermod -aG docker ec2-user

# -----------------------------------------------------------------------------
# Fetch secrets from Secrets Manager
# -----------------------------------------------------------------------------
echo "Fetching secrets from region: $REGION"

DATABASE_URL=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}database_url" \
    --query 'SecretString' --output text)

CLERK_ISSUER=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}clerk_issuer" \
    --query 'SecretString' --output text)

CLERK_WEBHOOK_SECRET=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}clerk_webhook_secret" \
    --query 'SecretString' --output text)

STRIPE_SECRET_KEY=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}stripe_secret_key" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

STRIPE_WEBHOOK_SECRET=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}stripe_webhook_secret" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

PERPLEXITY_API_KEY=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}perplexity_api_key" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

ENCRYPTION_KEY=$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "${!SECRETS_ARN_PREFIX}encryption_key" \
    --query 'SecretString' --output text 2>/dev/null || echo "")

# -----------------------------------------------------------------------------
# Create environment file
# -----------------------------------------------------------------------------
cat > /home/ec2-user/.env << ENVEOF
DATABASE_URL=$DATABASE_URL
CLERK_ISSUER=$CLERK_ISSUER
CLERK_WEBHOOK_SECRET=$CLERK_WEBHOOK_SECRET
CORS_ORIGINS=$FRONTEND_URL
ENVIRONMENT=$ENVIRONMENT
DEBUG=false
WS_CONNECTIONS_TABLE=$WS_CONNECTIONS_TABLE
WS_MANAGEMENT_API_URL=$WS_MANAGEMENT_API_URL
AWS_REGION=$REGION
AWS_DEFAULT_REGION=$REGION
STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET
STRIPE_STARTER_FIXED_PRICE_ID=${StripeStarterFixedPriceId}
STRIPE_PRO_FIXED_PRICE_ID=${StripeProFixedPriceId}
STRIPE_METERED_PRICE_ID=${StripeMeteredPriceId}
STRIPE_METER_ID=${StripeMeterIdParam}
FRONTEND_URL=$FRONTEND_URL
PERPLEXITY_API_KEY=$PERPLEXITY_API_KEY
ENCRYPTION_KEY=$ENCRYPTION_KEY
PROXY_BASE_URL=https://${DomainName}/api/v1/proxy
CONTAINER_EXECUTION_ROLE_ARN=${ContainerExecutionRoleArn}
ECS_CLUSTER_ARN=${EcsClusterArn}
ECS_TASK_DEFINITION=${EcsTaskDefinition}
ECS_SUBNETS=${EcsSubnets}
ECS_SECURITY_GROUP_ID=${EcsSecurityGroupId}
EFS_MOUNT_PATH=/mnt/efs/users
EFS_FILE_SYSTEM_ID=${EfsFileSystemId}
CLOUD_MAP_NAMESPACE_ID=${CloudMapNamespaceId}
CLOUD_MAP_SERVICE_ID=${CloudMapServiceId}
CLOUD_MAP_SERVICE_ARN=${CloudMapServiceArn}
ENVEOF

chmod 600 /home/ec2-user/.env
chown ec2-user:ec2-user /home/ec2-user/.env

# -----------------------------------------------------------------------------
# Login to ECR and pull image (URI injected by CDK with content hash tag)
# -----------------------------------------------------------------------------
echo "Pulling container image..."
IMAGE_URI="${ImageUri}"

AWS_ACCOUNT_ID=$(echo "$IMAGE_URI" | cut -d'.' -f1)
ECR_DOMAIN="$AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_DOMAIN"

docker pull "$IMAGE_URI"

# -----------------------------------------------------------------------------
# Mount EFS for workspaces
# -----------------------------------------------------------------------------
echo "Mounting EFS..."
mkdir -p /mnt/efs
EFS_FS_ID="${EfsFileSystemId}"
for i in 1 2 3 4 5; do
  mount -t efs -o tls "$EFS_FS_ID":/ /mnt/efs && break
  echo "EFS mount attempt $i failed, retrying in 10s..."
  /bin/sleep 10
done
mountpoint -q /mnt/efs || { echo "FATAL: EFS mount failed after 5 attempts"; exit 1; }
chmod 1777 /mnt/efs
mkdir -p /mnt/efs/users
echo "$EFS_FS_ID:/ /mnt/efs efs _netdev,tls 0 0" >> /etc/fstab

# -----------------------------------------------------------------------------
# Start the application
# -----------------------------------------------------------------------------
echo "Starting application..."

# Create systemd service
cat > /etc/systemd/system/isol8.service << SVCEOF
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
    $IMAGE_URI

[Install]
WantedBy=multi-user.target
SVCEOF

# Reload and start service
systemctl daemon-reload
systemctl enable isol8
systemctl start isol8

echo "Isol8 backend setup complete!"
