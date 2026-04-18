terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_kms_key" "trust_ledger" {
  description             = "Myntist Sovereign Beacon signing key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })

  tags = {
    Project     = "myntist-beacon"
    Module      = "kms_signing"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-signing"
  }
}

variable "environment" {
  description = "Deployment environment (e.g. production, staging)"
  type        = string
  default     = "production"
}

resource "aws_kms_alias" "trust_ledger" {
  name          = "alias/trust-ledger-kms-key-01"
  target_key_id = aws_kms_key.trust_ledger.key_id
}

data "aws_caller_identity" "current" {}

output "key_id" { value = aws_kms_key.trust_ledger.key_id }
output "key_alias" { value = aws_kms_alias.trust_ledger.name }
