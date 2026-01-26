terraform {
  required_providers { datadog = { source = "DataDog/datadog", version = "~> 3.40" } }
}
provider "datadog" { api_key = var.datadog_api_key app_key = var.datadog_app_key }
resource "datadog_monitor" "error_rate" {
  name = "${var.service_name} - Error rate >2% (5m)"
  type = "query alert"
  query = "sum(last_5m):sum:service.${var.service_name}.errors / sum:service.${var.service_name}.requests * 100 > 2"
  message = "High error rate detected for ${var.service_name}."
  tags = ["service:${var.service_name}", "team:bnpl"]
  notify_no_data = false
  require_full_window = true
}
resource "datadog_monitor" "approval_rate_drop" {
  name = "${var.service_name} - Approval rate drop >20% vs 24h"
  type = "query alert"
  query = "sum(last_5m):sum:gerald.approved{*} / (sum(last_5m):sum:gerald.approved{*} + sum(last_5m):sum:gerald.declined{*}) < (avg(last_24h):sum:gerald.approved{*} / (avg(last_24h):(sum:gerald.approved{*} + sum:gerald.declined{*})))*0.8"
  message = "Approval rate dropped >20% vs 24h baseline."
  tags = ["service:${var.service_name}", "team:bnpl"]
  notify_no_data = false
  require_full_window = true
}
