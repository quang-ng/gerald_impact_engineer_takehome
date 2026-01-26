# =============================================================================
# Gerald BNPL Decision Service - Terraform Variables
# =============================================================================

# -----------------------------------------------------------------------------
# Datadog Authentication
# -----------------------------------------------------------------------------
variable "datadog_api_key" {
  description = "Datadog API key for authentication"
  type        = string
  sensitive   = true
}

variable "datadog_app_key" {
  description = "Datadog Application key for authentication"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Service Configuration
# -----------------------------------------------------------------------------
variable "service_name" {
  description = "Name of the service (used in metric tags and monitor names)"
  type        = string
  default     = "gerald-gateway"
}

variable "environment" {
  description = "Deployment environment (production, staging, development)"
  type        = string
  default     = "production"
}

# -----------------------------------------------------------------------------
# Notification Channels
# -----------------------------------------------------------------------------
# These variables define who gets notified for different alert types.
# Use Datadog notification syntax:
#   - PagerDuty: @pagerduty-service-name
#   - Slack: @slack-channel-name
#   - Email: @email@example.com
#   - Teams: @teams-channel
# -----------------------------------------------------------------------------

variable "oncall_notification" {
  description = "Notification target for on-call (PagerDuty/OpsGenie)"
  type        = string
  default     = "@pagerduty-gerald-bnpl-oncall"
}

variable "product_notification" {
  description = "Notification target for Product team alerts"
  type        = string
  default     = "@slack-bnpl-product-alerts"
}

variable "engineering_notification" {
  description = "Notification target for Engineering team alerts"
  type        = string
  default     = "@slack-bnpl-engineering"
}

# -----------------------------------------------------------------------------
# Alert Thresholds (Optional Overrides)
# -----------------------------------------------------------------------------
# These allow customizing alert thresholds without modifying monitors.tf
# -----------------------------------------------------------------------------

variable "error_rate_critical_threshold" {
  description = "Error rate percentage threshold for critical alert"
  type        = number
  default     = 2
}

variable "bank_api_failure_threshold" {
  description = "Bank API failure rate percentage threshold"
  type        = number
  default     = 10
}

variable "webhook_queue_depth_threshold" {
  description = "Webhook queue depth threshold for alerting"
  type        = number
  default     = 100
}

variable "approval_rate_drop_threshold" {
  description = "Approval rate drop percentage (negative) vs baseline"
  type        = number
  default     = -20
}

variable "credit_limit_drop_threshold" {
  description = "Credit limit drop percentage (negative) vs baseline"
  type        = number
  default     = -30
}
