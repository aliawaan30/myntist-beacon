terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "environment" {
  description = "Deployment environment (e.g. production, staging)"
  type        = string
  default     = "production"
}

variable "secrets" {
  description = "Map of secret names to descriptions"
  type        = map(string)
  default = {
    "myntist/beacon/godaddy_api_key"    = "GoDaddy API key"
    "myntist/beacon/godaddy_api_secret" = "GoDaddy API secret"
    "myntist/beacon/hmac_secret"        = "HMAC webhook secret"
    "myntist/beacon/substrate_api_key"  = "Substrate API key"
  }
}

resource "aws_secretsmanager_secret" "beacon_secrets" {
  for_each    = var.secrets
  name        = each.key
  description = each.value
  tags = {
    Project     = "myntist-beacon"
    Module      = "secrets_publishers"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-secrets"
  }
}

output "secret_arns" {
  value = { for k, v in aws_secretsmanager_secret.beacon_secrets : k => v.arn }
}
