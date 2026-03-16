#!/bin/bash
# =============================================================================
# AWS Cleanup Script - Delete Old "freebird" Resources
# =============================================================================
# Removes the old freebird-* resources before running bootstrap.sh with isol8-*
#
# Usage: ./scripts/cleanup-old-infra.sh
# =============================================================================

set -euo pipefail

# Configuration
AWS_PROFILE="isol8-admin"
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="877352799272"

# Old resource names to delete
OLD_S3_BUCKET="freebird-terraform-state-${AWS_ACCOUNT_ID}"
OLD_DYNAMODB_TABLE="freebird-terraform-locks"
OLD_ECR_REPO="freebird-backend"

echo "============================================="
echo "Cleanup Old Freebird AWS Resources"
echo "============================================="
echo "Profile: $AWS_PROFILE"
echo "Region: $AWS_REGION"
echo ""
echo "Resources to delete:"
echo "  - S3 Bucket: $OLD_S3_BUCKET"
echo "  - DynamoDB Table: $OLD_DYNAMODB_TABLE"
echo "  - ECR Repository: $OLD_ECR_REPO"
echo "============================================="
echo ""
echo "WARNING: This will permanently delete all Terraform state!"
read -p "Are you sure you want to continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 1
fi

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
# 1. Delete S3 Bucket (must empty first, including versions)
# -----------------------------------------------------------------------------
echo ""
echo "[1/3] Deleting S3 bucket: $OLD_S3_BUCKET"

if aws s3api head-bucket --bucket "$OLD_S3_BUCKET" --profile "$AWS_PROFILE" 2>/dev/null; then
    echo "  Deleting all object versions..."

    # Delete all object versions
    aws s3api list-object-versions --bucket "$OLD_S3_BUCKET" --profile "$AWS_PROFILE" \
        --query 'Versions[].{Key:Key,VersionId:VersionId}' --output json 2>/dev/null | \
    jq -c '.[]' | while read -r obj; do
        key=$(echo "$obj" | jq -r '.Key')
        version=$(echo "$obj" | jq -r '.VersionId')
        if [[ "$key" != "null" && "$version" != "null" ]]; then
            aws s3api delete-object --bucket "$OLD_S3_BUCKET" --key "$key" --version-id "$version" --profile "$AWS_PROFILE" >/dev/null
            echo "    Deleted version: $key ($version)"
        fi
    done

    # Delete all delete markers
    aws s3api list-object-versions --bucket "$OLD_S3_BUCKET" --profile "$AWS_PROFILE" \
        --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' --output json 2>/dev/null | \
    jq -c '.[]' | while read -r obj; do
        key=$(echo "$obj" | jq -r '.Key')
        version=$(echo "$obj" | jq -r '.VersionId')
        if [[ "$key" != "null" && "$version" != "null" ]]; then
            aws s3api delete-object --bucket "$OLD_S3_BUCKET" --key "$key" --version-id "$version" --profile "$AWS_PROFILE" >/dev/null
            echo "    Deleted marker: $key ($version)"
        fi
    done

    # Delete the bucket
    aws s3api delete-bucket --bucket "$OLD_S3_BUCKET" --profile "$AWS_PROFILE"
    echo "  ✓ Deleted bucket '$OLD_S3_BUCKET'"
else
    echo "  ✓ Bucket '$OLD_S3_BUCKET' does not exist (already deleted)"
fi

# -----------------------------------------------------------------------------
# 2. Delete DynamoDB Table
# -----------------------------------------------------------------------------
echo ""
echo "[2/3] Deleting DynamoDB table: $OLD_DYNAMODB_TABLE"

if aws dynamodb describe-table --table-name "$OLD_DYNAMODB_TABLE" --region "$AWS_REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
    aws dynamodb delete-table \
        --table-name "$OLD_DYNAMODB_TABLE" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE" >/dev/null
    echo "  Waiting for table deletion..."
    aws dynamodb wait table-not-exists \
        --table-name "$OLD_DYNAMODB_TABLE" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE"
    echo "  ✓ Deleted table '$OLD_DYNAMODB_TABLE'"
else
    echo "  ✓ Table '$OLD_DYNAMODB_TABLE' does not exist (already deleted)"
fi

# -----------------------------------------------------------------------------
# 3. Delete ECR Repository (optional - may have images)
# -----------------------------------------------------------------------------
echo ""
echo "[3/3] Deleting ECR repository: $OLD_ECR_REPO"

if aws ecr describe-repositories --repository-names "$OLD_ECR_REPO" --region "$AWS_REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
    aws ecr delete-repository \
        --repository-name "$OLD_ECR_REPO" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE" \
        --force >/dev/null
    echo "  ✓ Deleted repository '$OLD_ECR_REPO'"
else
    echo "  ✓ Repository '$OLD_ECR_REPO' does not exist (already deleted)"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo "Cleanup Complete!"
echo "============================================="
echo ""
echo "Deleted resources:"
echo "  - S3 Bucket: $OLD_S3_BUCKET"
echo "  - DynamoDB Table: $OLD_DYNAMODB_TABLE"
echo "  - ECR Repository: $OLD_ECR_REPO"
echo ""
echo "Next steps:"
echo "  1. Run: ./scripts/bootstrap.sh"
echo "     (This will create new isol8-* resources)"
echo ""
echo "============================================="
