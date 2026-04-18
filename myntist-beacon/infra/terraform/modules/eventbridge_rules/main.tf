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

resource "aws_cloudwatch_event_rule" "generate_status" {
  name                = "myntist-beacon-generate-status"
  description         = "Trigger generate_status Lambda every 5 minutes"
  schedule_expression = "rate(5 minutes)"
  tags = {
    Project     = "myntist-beacon"
    Module      = "eventbridge_rules"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-scheduler"
  }
}

resource "aws_cloudwatch_event_rule" "generate_matrix" {
  name                = "myntist-beacon-generate-matrix"
  description         = "Trigger generate_matrix Lambda every hour"
  schedule_expression = "rate(1 hour)"
  tags = {
    Project     = "myntist-beacon"
    Module      = "eventbridge_rules"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-scheduler"
  }
}

resource "aws_cloudwatch_event_rule" "generate_pulse" {
  name                = "myntist-beacon-generate-pulse"
  description         = "Trigger generate_pulse Lambda every minute"
  schedule_expression = "rate(1 minute)"
  tags = {
    Project     = "myntist-beacon"
    Module      = "eventbridge_rules"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-scheduler"
  }
}
