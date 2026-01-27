# =============================================================================
# Gerald BNPL Decision Service - Datadog Monitors
# =============================================================================
#
# This configuration defines alerts for the Gerald BNPL decision service.
# Alerts are categorized into:
#   - Business Alerts: Product/revenue impact metrics
#   - Technical Alerts: System health and reliability metrics
#
# Usage:
#   terraform init
#   terraform plan -var="datadog_api_key=YOUR_KEY" -var="datadog_app_key=YOUR_KEY"
#   terraform apply -var="datadog_api_key=YOUR_KEY" -var="datadog_app_key=YOUR_KEY"
#
# =============================================================================

terraform {
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 3.40"
    }
  }
}

provider "datadog" {
  api_key  = var.datadog_api_key
  app_key  = var.datadog_app_key
  api_url  = "https://api.us5.datadoghq.com"
}

# =============================================================================
# BUSINESS ALERTS
# =============================================================================

# -----------------------------------------------------------------------------
# Approval Rate Drop Alert
# -----------------------------------------------------------------------------
# Triggers when approval rate drops >20% compared to 24-hour baseline.
# This signals broken risk logic or upstream data issues that need immediate
# investigation to prevent revenue loss and user experience degradation.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "approval_rate_drop" {
  name    = "${var.service_name} - Approval rate drop >20% vs 24h baseline"
  type    = "query alert"
  message = <<-EOT
    ## 🚨 Approval Rate Alert

    **Approval rate has dropped more than 20% compared to 24-hour baseline.**

    ### Impact
    - Users may be incorrectly denied advances
    - Revenue impact from reduced approvals
    - Potential broken risk logic or upstream data issues

    ### Investigation Steps
    1. Check recent deployments for scoring logic changes
    2. Verify Bank API is returning valid transaction data
    3. Review risk score distribution in dashboard
    4. Check for data quality issues in transaction history

    ### Runbook
    See: https://wiki.gerald.com/runbooks/approval-rate-drop

    ${var.oncall_notification}
    ${var.product_notification}
  EOT

  query = <<-EOQ
    pct_change(avg(last_5m),last_1d):avg:gerald_approval_rate_1h{service:${var.service_name}} < -20
  EOQ

  monitor_thresholds {
    critical = -20
    warning  = -10
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:high", "alert-type:business"]
  notify_no_data      = false
  require_full_window = true
  evaluation_delay    = 60

  # Notify on recovery
  notify_audit      = false
  include_tags      = true
  renotify_interval = 30
}

# -----------------------------------------------------------------------------
# Average Credit Limit Drop Alert
# -----------------------------------------------------------------------------
# Triggers when average credit limit drops >30% compared to 7-day baseline.
# Over-conservative scoring hurts revenue. This alert helps Product team
# identify when risk model changes are negatively impacting business.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "credit_limit_drop" {
  name    = "${var.service_name} - Average credit limit drop >30% vs 7d baseline"
  type    = "query alert"
  message = <<-EOT
    ## ⚠️ Credit Limit Alert

    **Average credit limit has dropped more than 30% compared to 7-day baseline.**

    ### Impact
    - Users receiving lower limits than expected
    - Revenue reduction from smaller advance amounts
    - Potentially over-conservative risk scoring

    ### Investigation Steps
    1. Review recent changes to scoring logic or thresholds
    2. Check distribution of risk scores by band
    3. Analyze user cohorts affected by the change
    4. Compare income/balance patterns vs historical

    ### Runbook
    See: https://wiki.gerald.com/runbooks/credit-limit-drop

    ${var.product_notification}
  EOT

  query = <<-EOQ
    pct_change(avg(last_1h),last_1w):avg:gerald_avg_credit_limit_dollars{service:${var.service_name}} < -30
  EOQ

  monitor_thresholds {
    critical = -30
    warning  = -15
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:medium", "alert-type:business"]
  notify_no_data      = false
  require_full_window = true
  evaluation_delay    = 300

  include_tags      = true
  renotify_interval = 60
}

# =============================================================================
# TECHNICAL ALERTS
# =============================================================================

# -----------------------------------------------------------------------------
# Error Rate Alert
# -----------------------------------------------------------------------------
# Triggers when error rate exceeds 2% over 5 minutes.
# High error rates indicate system instability requiring immediate attention.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "error_rate" {
  name    = "${var.service_name} - Error rate >2% (5m)"
  type    = "query alert"
  message = <<-EOT
    ## 🚨 High Error Rate Alert

    **Error rate has exceeded 2% over the last 5 minutes.**

    ### Impact
    - Users unable to request advances
    - Decision requests failing
    - Potential data loss or corruption

    ### Investigation Steps
    1. Check application logs for error patterns
    2. Verify database connectivity
    3. Check Bank API health
    4. Review recent deployments

    ### Runbook
    See: https://wiki.gerald.com/runbooks/high-error-rate

    ${var.oncall_notification}
  EOT

  query = <<-EOQ
    sum(last_5m):sum:http_requests_total{service:${var.service_name},status:5*}.as_count() / sum:http_requests_total{service:${var.service_name}}.as_count() * 100 > 2
  EOQ

  monitor_thresholds {
    critical          = 2
    warning           = 1
    critical_recovery = 0.5
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:critical", "alert-type:technical"]
  notify_no_data      = false
  require_full_window = true
  evaluation_delay    = 60

  include_tags      = true
  renotify_interval = 15
}

# -----------------------------------------------------------------------------
# Bank API Failure Rate Alert
# -----------------------------------------------------------------------------
# Triggers when Bank API failure rate exceeds 10% over 10 minutes.
# Bank API is critical for fetching transaction data needed for decisions.
# High failure rates block all decision processing.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "bank_api_failures" {
  name    = "${var.service_name} - Bank API failure rate >10% (10m)"
  type    = "query alert"
  message = <<-EOT
    ## 🚨 Bank API Failure Alert

    **Bank API failure rate has exceeded 10% over the last 10 minutes.**

    ### Impact
    - Unable to fetch user transaction history
    - Decision requests will fail or timeout
    - Users cannot receive advances

    ### Investigation Steps
    1. Check Bank API status page
    2. Verify network connectivity to Bank API
    3. Review error types in bank_fetch_failures_total metric
    4. Check for rate limiting or authentication issues

    ### Runbook
    See: https://wiki.gerald.com/runbooks/bank-api-failures

    ${var.oncall_notification}
  EOT

  query = <<-EOQ
    sum(last_10m):sum:bank_fetch_failures_total{service:${var.service_name}}.as_count() / (sum:bank_fetch_failures_total{service:${var.service_name}}.as_count() + sum:gerald_bank_fetch_success_total{service:${var.service_name}}.as_count()) * 100 > 10
  EOQ

  monitor_thresholds {
    critical          = 10
    warning           = 5
    critical_recovery = 2
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:critical", "alert-type:technical", "dependency:bank-api"]
  notify_no_data      = false
  require_full_window = true
  evaluation_delay    = 60

  include_tags      = true
  renotify_interval = 15
}

# -----------------------------------------------------------------------------
# Webhook Queue Depth Alert
# -----------------------------------------------------------------------------
# Triggers when webhook retry queue exceeds 100 items.
# Growing queue indicates ledger service issues or webhook delivery problems.
# May cause delayed notifications and reconciliation issues.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "webhook_queue_depth" {
  name    = "${var.service_name} - Webhook queue depth >100 items"
  type    = "query alert"
  message = <<-EOT
    ## ⚠️ Webhook Queue Alert

    **Webhook retry queue has exceeded 100 pending items.**

    ### Impact
    - Ledger notifications delayed
    - Potential reconciliation issues
    - Webhook delivery backlog growing

    ### Investigation Steps
    1. Check Ledger service health
    2. Review webhook_latency_seconds for timeouts
    3. Check network connectivity to Ledger webhook endpoint
    4. Verify Ledger webhook endpoint is accepting requests

    ### Runbook
    See: https://wiki.gerald.com/runbooks/webhook-queue-backlog

    ${var.engineering_notification}
  EOT

  query = "avg(last_5m):avg:webhook_queue_depth{service:${var.service_name}} > 100"

  monitor_thresholds {
    critical          = 100
    warning           = 50
    critical_recovery = 25
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:medium", "alert-type:technical", "dependency:ledger"]
  notify_no_data      = false
  require_full_window = false
  evaluation_delay    = 60

  include_tags      = true
  renotify_interval = 30
}

# -----------------------------------------------------------------------------
# Decision Latency Alert (P95)
# -----------------------------------------------------------------------------
# Triggers when P95 decision latency exceeds 5 seconds.
# Slow decisions degrade user experience in the app.
# -----------------------------------------------------------------------------
resource "datadog_monitor" "decision_latency_p95" {
  name    = "${var.service_name} - Decision latency P95 >5s"
  type    = "query alert"
  message = <<-EOT
    ## ⚠️ High Latency Alert

    **Decision latency P95 has exceeded 5 seconds.**

    ### Impact
    - Poor user experience
    - App timeouts possible
    - Potential upstream slowness

    ### Investigation Steps
    1. Check Bank API latency (gerald_bank_fetch_latency_seconds)
    2. Review database query latency
    3. Check for resource contention
    4. Review recent code changes

    ${var.engineering_notification}
  EOT

  query = "avg(last_5m):p95:decision_latency_seconds{service:${var.service_name}} > 5"

  monitor_thresholds {
    critical = 5
    warning  = 2.5
  }

  tags                = ["service:${var.service_name}", "team:bnpl", "severity:medium", "alert-type:technical"]
  notify_no_data      = false
  require_full_window = true
  evaluation_delay    = 60

  include_tags      = true
  renotify_interval = 30
}
