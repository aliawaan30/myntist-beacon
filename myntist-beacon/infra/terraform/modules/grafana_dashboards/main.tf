terraform {
  required_providers {
    grafana = {
      source  = "grafana/grafana"
      version = "~> 2.0"
    }
  }
}

variable "grafana_url" {
  description = "Grafana instance URL"
  type        = string
}

variable "grafana_auth" {
  description = "Grafana service account token"
  type        = string
  sensitive   = true
}

# Stub: Grafana dashboard for Myntist Beacon survivability metrics
# Configure with actual Grafana provider credentials when deploying

output "dashboard_url" {
  value = "${var.grafana_url}/d/myntist-beacon"
}
