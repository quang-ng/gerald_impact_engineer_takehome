# =============================================================================
# Gerald BNPL Decision Service - Datadog Dashboard
# =============================================================================
#
# Deploys the dashboard from metrics/dashboard_datadog.json to Datadog.
# The dashboard has two views:
#   - Business View: Approval rates, credit limits, score distribution
#   - Engineering View: Latencies, error rates, upstream health
#
# =============================================================================

resource "datadog_dashboard_json" "gerald_bnpl" {
  dashboard = file("${path.module}/../metrics/dashboard_datadog.json")
}

output "dashboard_url" {
  description = "URL of the deployed Datadog dashboard"
  value       = datadog_dashboard_json.gerald_bnpl.url
}
