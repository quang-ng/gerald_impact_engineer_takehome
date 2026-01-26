"""
Prometheus Metrics for Gerald BNPL Decision Service.

This module defines all metrics exposed at the /metrics endpoint.
Metrics are categorized into:

1. Business Impact Metrics - For Product/Finance teams
   - Decision outcomes, approval rates, credit limits

2. Technical Metrics - For Engineering/SRE teams
   - Latencies, error rates, queue depths
"""
from prometheus_client import Counter, Gauge, Histogram, Info

# =============================================================================
# SERVICE INFO
# =============================================================================

SERVICE_INFO = Info(
    "gerald_service",
    "Service information"
)
SERVICE_INFO.info({
    "version": "0.1.0",
    "service": "gerald-gateway",
})

# =============================================================================
# BUSINESS IMPACT METRICS
# =============================================================================

# Counter: Total decisions made by outcome
DECISION_TOTAL = Counter(
    "gerald_decision_total",
    "Total BNPL decisions made",
    ["outcome"]  # approved, declined
)

# Counter: Credit limits granted by bucket
CREDIT_LIMIT_BUCKET = Counter(
    "gerald_credit_limit_bucket",
    "Credit limits granted by dollar bucket",
    ["bucket", "outcome"]  # bucket: "0", "100", "200", etc. outcome: approved/declined
)

# Gauge: Current 1-hour approval rate (updated on each decision)
APPROVAL_RATE_1H = Gauge(
    "gerald_approval_rate_1h",
    "Rolling 1-hour approval rate (0.0 to 1.0)"
)

# Gauge: Average credit limit granted (rolling)
AVG_CREDIT_LIMIT = Gauge(
    "gerald_avg_credit_limit_dollars",
    "Average credit limit granted in dollars"
)

# Counter: Total amount granted in cents
TOTAL_AMOUNT_GRANTED = Counter(
    "gerald_total_amount_granted_cents",
    "Total amount granted across all approved decisions"
)

# Histogram: Requested amounts distribution
REQUESTED_AMOUNT = Histogram(
    "gerald_requested_amount_cents",
    "Distribution of requested amounts",
    buckets=[10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000]
)

# Counter: Decisions by score band
DECISION_BY_SCORE_BAND = Counter(
    "gerald_decision_by_score_band",
    "Decisions grouped by risk score band",
    ["score_band", "outcome"]  # score_band: denied, entry, basic, etc.
)

# =============================================================================
# TECHNICAL METRICS
# =============================================================================

# Histogram: Decision latency (end-to-end)
DECISION_LATENCY = Histogram(
    "decision_latency_seconds",
    "Time to make a BNPL decision (end-to-end)",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Histogram: Risk scoring latency
SCORING_LATENCY = Histogram(
    "gerald_scoring_latency_seconds",
    "Time to calculate risk score",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25]
)

# Histogram: Bank API fetch latency
BANK_FETCH_LATENCY = Histogram(
    "gerald_bank_fetch_latency_seconds",
    "Time to fetch transactions from bank API",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

# Counter: Bank API failures
BANK_FETCH_FAILURES = Counter(
    "bank_fetch_failures_total",
    "Total bank API fetch failures",
    ["error_type"]  # timeout, connection_error, http_error, not_found
)

# Counter: Bank API successes
BANK_FETCH_SUCCESS = Counter(
    "gerald_bank_fetch_success_total",
    "Total successful bank API fetches"
)

# Histogram: Webhook delivery latency
WEBHOOK_LATENCY = Histogram(
    "webhook_latency_seconds",
    "Time to deliver webhook",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Counter: Webhook delivery outcomes
WEBHOOK_DELIVERY = Counter(
    "gerald_webhook_delivery_total",
    "Webhook delivery attempts",
    ["status"]  # success, failed
)

# Counter: Webhook retries
WEBHOOK_RETRY = Counter(
    "webhook_retry_total",
    "Total webhook retry attempts"
)

# Gauge: Webhook queue depth (pending webhooks)
WEBHOOK_QUEUE_DEPTH = Gauge(
    "webhook_queue_depth",
    "Number of webhooks pending delivery"
)

# Gauge: Database connection pool stats
DB_POOL_CONNECTIONS = Gauge(
    "gerald_db_pool_connections",
    "Database connection pool statistics",
    ["state"]  # active, idle, overflow
)

# Histogram: Database query latency
DB_QUERY_LATENCY = Histogram(
    "gerald_db_query_latency_seconds",
    "Database query execution time",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# =============================================================================
# HTTP METRICS (Standard)
# =============================================================================

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

HTTP_REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Track rolling stats for approval rate calculation
_recent_decisions: list[bool] = []
_max_decisions_tracked = 1000  # Track last 1000 decisions for rolling rate


def record_decision(
    approved: bool,
    credit_limit_cents: int,
    amount_granted_cents: int,
    score_band: str,
    latency_seconds: float,
) -> None:
    """
    Record all metrics for a single BNPL decision.

    Args:
        approved: Whether the decision was approved
        credit_limit_cents: The credit limit assigned
        amount_granted_cents: The amount actually granted
        score_band: The risk score band (e.g., "premium", "denied")
        latency_seconds: Time taken to make the decision
    """
    outcome = "approved" if approved else "declined"

    # Decision counter
    DECISION_TOTAL.labels(outcome=outcome).inc()

    # Credit limit bucket
    bucket = _cents_to_bucket(credit_limit_cents)
    CREDIT_LIMIT_BUCKET.labels(bucket=bucket, outcome=outcome).inc()

    # Score band counter
    DECISION_BY_SCORE_BAND.labels(score_band=score_band, outcome=outcome).inc()

    # Decision latency
    DECISION_LATENCY.observe(latency_seconds)

    # Track for rolling approval rate
    _recent_decisions.append(approved)
    if len(_recent_decisions) > _max_decisions_tracked:
        _recent_decisions.pop(0)

    # Update rolling approval rate
    if _recent_decisions:
        rate = sum(_recent_decisions) / len(_recent_decisions)
        APPROVAL_RATE_1H.set(rate)

    # Track granted amounts
    if approved and amount_granted_cents > 0:
        TOTAL_AMOUNT_GRANTED.inc(amount_granted_cents)

        # Update average credit limit
        total_approved = sum(_recent_decisions)
        if total_approved > 0:
            # This is a simplified calculation; in production use a proper rolling average
            AVG_CREDIT_LIMIT.set(credit_limit_cents / 100)


def record_bank_fetch(success: bool, latency_seconds: float, error_type: str = None) -> None:
    """Record bank API fetch metrics."""
    BANK_FETCH_LATENCY.observe(latency_seconds)

    if success:
        BANK_FETCH_SUCCESS.inc()
    else:
        BANK_FETCH_FAILURES.labels(error_type=error_type or "unknown").inc()


def record_webhook_delivery(success: bool, latency_seconds: float, is_retry: bool = False) -> None:
    """Record webhook delivery metrics."""
    WEBHOOK_LATENCY.observe(latency_seconds)

    status = "success" if success else "failed"
    WEBHOOK_DELIVERY.labels(status=status).inc()

    if is_retry:
        WEBHOOK_RETRY.inc()


def set_webhook_queue_depth(depth: int) -> None:
    """Update the webhook queue depth gauge."""
    WEBHOOK_QUEUE_DEPTH.set(depth)


def record_scoring_latency(latency_seconds: float) -> None:
    """Record risk scoring latency."""
    SCORING_LATENCY.observe(latency_seconds)


def record_requested_amount(amount_cents: int) -> None:
    """Record the requested amount for distribution tracking."""
    REQUESTED_AMOUNT.observe(amount_cents)


def _cents_to_bucket(cents: int) -> str:
    """Convert cents to a bucket label."""
    dollars = cents // 100
    if dollars == 0:
        return "0"
    elif dollars <= 100:
        return "100"
    elif dollars <= 200:
        return "200"
    elif dollars <= 300:
        return "300"
    elif dollars <= 400:
        return "400"
    elif dollars <= 500:
        return "500"
    else:
        return "600+"
