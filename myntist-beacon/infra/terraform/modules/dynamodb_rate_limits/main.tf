terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_dynamodb_table" "rate_limits" {
  name         = "myntist-beacon-rate-limits"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Project     = "myntist-beacon"
    Module      = "dynamodb_rate_limits"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-rate-limits"
  }
}

variable "environment" {
  description = "Deployment environment (e.g. production, staging)"
  type        = string
  default     = "production"
}

output "table_name" { value = aws_dynamodb_table.rate_limits.name }
