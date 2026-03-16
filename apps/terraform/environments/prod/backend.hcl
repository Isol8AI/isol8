# =============================================================================
# Terraform Backend Configuration - Prod Environment (Isol8)
# =============================================================================
# Initialize with: terraform init -backend-config=environments/prod/backend.hcl

bucket         = "isol8-terraform-state-877352799272"
key            = "prod/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "isol8-terraform-locks"
