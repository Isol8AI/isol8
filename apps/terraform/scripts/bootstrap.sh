#!/bin/bash
# =============================================================================
# AWS Bootstrap Script
# =============================================================================
# Creates the foundational AWS resources needed before Terraform can run:
# - S3 bucket for Terraform state
# - DynamoDB table for Terraform locks
# - ECR repository for Docker images
# - GitHub OIDC provider for CI/CD
#
# Usage: ./scripts/bootstrap.sh
# =============================================================================

set -euo pipefail

# Configuration
AWS_PROFILE="isol8-admin"
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="877352799272"
PROJECT="isol8"

# Resource names (S3 bucket includes account ID for global uniqueness)
S3_BUCKET="${PROJECT}-terraform-state-${AWS_ACCOUNT_ID}"
DYNAMODB_TABLE="${PROJECT}-terraform-locks"
ECR_REPO="${PROJECT}-backend"

echo "============================================="
echo "Isol8 AWS Bootstrap"
echo "============================================="
echo "Profile: $AWS_PROFILE"
echo "Region: $AWS_REGION"
echo "Account: $AWS_ACCOUNT_ID"
echo "============================================="

# Check if logged in
echo ""
echo "Checking AWS credentials..."
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" &>/dev/null; then
    echo "Not logged in. Running: aws sso login --profile $AWS_PROFILE"
    aws sso login --profile "$AWS_PROFILE"
fi

CALLER_IDENTITY=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --output json)
echo "Logged in as: $(echo $CALLER_IDENTITY | jq -r '.Arn')"

# -----------------------------------------------------------------------------
# 1. Create S3 Bucket for Terraform State
# -----------------------------------------------------------------------------
echo ""
echo "[1/4] Creating S3 bucket for Terraform state..."

if aws s3api head-bucket --bucket "$S3_BUCKET" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  ✓ Bucket '$S3_BUCKET' already exists"
else
    aws s3api create-bucket \
        --bucket "$S3_BUCKET" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Created bucket '$S3_BUCKET'"
fi

# Enable versioning (for state file history)
aws s3api put-bucket-versioning \
    --bucket "$S3_BUCKET" \
    --versioning-configuration Status=Enabled \
    --profile "$AWS_PROFILE"
echo "  ✓ Enabled versioning"

# Enable encryption
aws s3api put-bucket-encryption \
    --bucket "$S3_BUCKET" \
    --server-side-encryption-configuration '{
        "Rules": [{
            "ApplyServerSideEncryptionByDefault": {
                "SSEAlgorithm": "AES256"
            },
            "BucketKeyEnabled": true
        }]
    }' \
    --profile "$AWS_PROFILE"
echo "  ✓ Enabled encryption"

# Block public access
aws s3api put-public-access-block \
    --bucket "$S3_BUCKET" \
    --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }' \
    --profile "$AWS_PROFILE"
echo "  ✓ Blocked public access"

# -----------------------------------------------------------------------------
# 2. Create DynamoDB Table for Terraform Locks
# -----------------------------------------------------------------------------
echo ""
echo "[2/4] Creating DynamoDB table for Terraform locks..."

if aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" --region "$AWS_REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  ✓ Table '$DYNAMODB_TABLE' already exists"
else
    aws dynamodb create-table \
        --table-name "$DYNAMODB_TABLE" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Created table '$DYNAMODB_TABLE'"

    echo "  Waiting for table to become active..."
    aws dynamodb wait table-exists \
        --table-name "$DYNAMODB_TABLE" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Table is active"
fi

# -----------------------------------------------------------------------------
# 3. Create ECR Repository
# -----------------------------------------------------------------------------
echo ""
echo "[3/4] Creating ECR repository..."

if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  ✓ Repository '$ECR_REPO' already exists"
else
    aws ecr create-repository \
        --repository-name "$ECR_REPO" \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256 \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Created repository '$ECR_REPO'"
fi

# Set lifecycle policy (keep last 10 images)
aws ecr put-lifecycle-policy \
    --repository-name "$ECR_REPO" \
    --lifecycle-policy-text '{
        "rules": [{
            "rulePriority": 1,
            "description": "Keep last 10 images",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": 10
            },
            "action": {
                "type": "expire"
            }
        }]
    }' \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" >/dev/null
echo "  ✓ Set lifecycle policy (keep last 10 images)"

# -----------------------------------------------------------------------------
# 4. Create GitHub OIDC Provider
# -----------------------------------------------------------------------------
echo ""
echo "[4/4] Creating GitHub OIDC provider..."

GITHUB_OIDC_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$GITHUB_OIDC_ARN" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  ✓ GitHub OIDC provider already exists"
else
    # Get GitHub's OIDC thumbprint
    THUMBPRINT="6938fd4d98bab03faadb97b34396831e3780aea1"

    aws iam create-open-id-connect-provider \
        --url "https://token.actions.githubusercontent.com" \
        --client-id-list "sts.amazonaws.com" \
        --thumbprint-list "$THUMBPRINT" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Created GitHub OIDC provider"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo "Bootstrap Complete!"
echo "============================================="
echo ""
echo "Resources created:"
echo "  • S3 Bucket: $S3_BUCKET"
echo "  • DynamoDB Table: $DYNAMODB_TABLE"
echo "  • ECR Repository: $ECR_REPO"
echo "  • GitHub OIDC Provider: token.actions.githubusercontent.com"
echo ""
echo "Next steps:"
echo "  1. cd terraform"
echo "  2. terraform init -backend-config=environments/dev/backend.hcl"
echo "  3. terraform plan -var-file=environments/dev/terraform.tfvars"
echo ""
echo "Note: You'll need to set these environment variables for secrets:"
echo "  export TF_VAR_supabase_connection_string='postgresql://...'"
echo "  export TF_VAR_huggingface_token='hf_...'"
echo "  export TF_VAR_clerk_webhook_secret='whsec_...'"
echo "============================================="
