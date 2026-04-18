terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "bucket_name" {
  description = "S3 bucket name for beacon feeds"
  type        = string
  default     = "myntist-beacon-feeds"
}

variable "cloudfront_domain" {
  description = "Custom domain for CloudFront distribution"
  type        = string
  default     = "myntist.com"
}

variable "environment" {
  description = "Deployment environment (e.g. production, staging)"
  type        = string
  default     = "production"
}

resource "aws_s3_bucket" "beacon_feeds" {
  bucket = var.bucket_name
  tags = {
    Project     = "myntist-beacon"
    Module      = "s3_cloudfront_beacon"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-feeds"
  }
}

resource "aws_s3_bucket_public_access_block" "beacon_feeds" {
  bucket                  = aws_s3_bucket.beacon_feeds.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_distribution" "beacon" {
  origin {
    domain_name              = aws_s3_bucket.beacon_feeds.bucket_regional_domain_name
    origin_id                = "S3-beacon-feeds"
    origin_access_control_id = aws_cloudfront_origin_access_control.beacon.id
  }

  enabled             = true
  default_root_object = "api/field/v1/status.json"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-beacon-feeds"
    viewer_protocol_policy = "redirect-to-https"
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 900
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate { cloudfront_default_certificate = true }

  tags = {
    Project     = "myntist-beacon"
    Module      = "s3_cloudfront_beacon"
    Environment = var.environment
    Phase       = "phase2"
    CostCenter  = "beacon-cdn"
  }
}

resource "aws_cloudfront_origin_access_control" "beacon" {
  name                              = "beacon-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

output "bucket_name" { value = aws_s3_bucket.beacon_feeds.bucket }
output "cloudfront_domain" { value = aws_cloudfront_distribution.beacon.domain_name }
