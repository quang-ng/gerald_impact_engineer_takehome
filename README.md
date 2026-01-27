# Gerald BNPL Decision Service

A Buy Now, Pay Later credit decision engine built for Gerald's $0-fee model. This service evaluates user creditworthiness based on bank transaction data, assigns credit limits, and creates repayment plans.

---

## Business Context

### Problem

Gerald needs to make real-time credit decisions for BNPL advances ($100-$600). Unlike traditional BNPL providers that rely on late fees and penalties to recover from defaults, Gerald operates a **$0-fee model** — every default directly impacts the bottom line. This means risk assessment must be more accurate and conservative than fee-based competitors.

### Approach

The service balances two competing goals:

1. **Approve users who will repay** — maximize user value and revenue from merchant fees
2. **Deny users likely to default** — protect Gerald since there's no fee revenue to offset losses

We use a **score-based system (0-100)** built from four financial signals extracted from bank transaction history. The score maps to tiered credit limits ($0-$600), ensuring higher-risk users get lower limits rather than blanket denials.

### Trade-offs

| Decision | Rationale |
|----------|-----------|
| **Conservative thresholds** | No fee revenue means defaults are pure loss. We'd rather under-approve than over-approve. |
| **Tiered limits over binary approve/deny** | A user scoring 45 gets $200 instead of $0. This captures marginal revenue while limiting exposure. |
| **Thin file penalty over denial** | New users aren't outright denied — they receive reduced limits. This allows user acquisition while managing uncertainty. |
| **Income regularity weighted lower** | Gig workers have irregular timing but stable totals. Penalizing timing would exclude a growing segment unfairly. |
| **90-day analysis window** | Balances recency (recent behavior matters most) with stability (need enough data to see patterns). |

---

## Risk Logic

### Scoring Components (0-100 points)

| Component | Max Points | What It Measures |
|-----------|-----------|------------------|
| Average Daily Balance | 30 | Financial buffer for repayment |
| Income vs Spending Ratio | 30 | Cash flow sustainability |
| NSF/Overdraft Count | 25 | Payment failure risk (strongest predictor) |
| Income Regularity | 15 | Predictability of cash inflows |
| Thin File Penalty | -30 | Uncertainty from limited history |

### Factor Details

**1. Average Daily Balance (0-30 points)**

Measures the user's financial cushion. Uses carry-forward logic — on days with no transactions, the previous day's balance carries over.

| Threshold | Points | Why |
|-----------|--------|-----|
| >= $1,000 | 30 | Can absorb a full BNPL advance ($600 max) |
| >= $500 | 25 | Can absorb smaller advances |
| >= $100 | 15 | Minimal cushion |
| >= $0 | 10 | At least not overdrawn |
| < $0 | 0 | Chronically negative — high risk |

**2. Income vs Spending Ratio (0-30 points)**

Total credits divided by total debits. A ratio > 1.0 means the user earns more than they spend.

| Threshold | Points | Why |
|-----------|--------|-----|
| >= 1.3 | 30 | 30% income surplus — strong repayment capacity |
| >= 1.1 | 25 | 10% surplus — healthy |
| >= 1.0 | 15 | Breakeven — risky but possible |
| >= 0.8 | 5 | 20% deficit — marginal |
| < 0.8 | 0 | Significant cash burn |

**3. NSF/Overdraft Count (0-25 points)**

Counts two types of events: explicit NSF flags from the bank, and debit transactions that cause the balance to cross from positive to negative. This is the **strongest predictor of future defaults**.

| Threshold | Points | Why |
|-----------|--------|-----|
| 0 events | 25 | Clean history |
| 1-2 events | 15 | May be one-time circumstance |
| 3-4 events | 5 | Pattern emerging |
| 5+ events | 0 | Chronic overdrafts |

**4. Income Regularity (0-15 points)**

Measures consistency of income timing using coefficient of variation of gaps between income deposits. Intentionally **weighted lower** to avoid penalizing gig workers.

| Threshold | Points | Why |
|-----------|--------|-----|
| >= 0.8 regularity | 15 | Very predictable (e.g., bi-weekly payroll) |
| >= 0.5 regularity | 10 | Somewhat predictable (steady gig work) |
| >= 0.3 regularity | 5 | Irregular but present |
| < 0.3 regularity | 0 | Highly unpredictable |

**5. Thin File Penalty (0 to -30 points)**

Applied when transaction history is limited. A penalty rather than outright denial — strong signals from other factors can overcome it.

| Transactions | Penalty | Why |
|-------------|---------|-----|
| >= 30 | 0 | Sufficient history |
| 20-29 | -10 | Moderate uncertainty |
| 10-19 | -20 | Limited history |
| < 10 | -30 | Very thin — could be gaming or new account |

### Score to Credit Limit Mapping

| Score | Band | Limit | Description |
|-------|------|-------|-------------|
| 0-19 | Denied | $0 | Too risky for $0-fee model |
| 20-39 | Entry | $100 | Limited trust, small advance |
| 40-54 | Basic | $200 | Moderate risk |
| 55-64 | Standard | $300 | Acceptable risk |
| 65-74 | Enhanced | $400 | Good financial health |
| 75-84 | Premium | $500 | Strong financial health |
| 85-100 | Maximum | $600 | Excellent — full limit |

### Edge Cases

**Thin Files (new users):** Receive a penalty of -10 to -30 points depending on transaction count. A user with only 3 transactions but excellent metrics (high balance, good ratio, no NSF) would score ~40-55 instead of ~70-85, landing in the entry/basic tier rather than premium.

**Gig Workers:** Income regularity is only 15% of the total score. A gig worker with irregular timing but strong income ratio (1.3+) and good balance still scores 60+, qualifying for $300-$400 limits.

**Chronic Overdrafts:** Users with 5+ NSF events get 0 points from the NSF component (25 points lost) and likely have low balance scores too. Combined, they typically score < 20 and are denied.

**Zero Transactions:** Returns a score of 0 (denied). We can't make a decision without data.

---

## Stakeholder Guide

### Product Team

**Key metrics to watch:**

| Metric | What It Tells You | Dashboard Location |
|--------|-------------------|-------------------|
| `gerald_approval_rate_1h` | Are we approving the right percentage of users? | Business View - Approval Rate Trend |
| `gerald_decision_by_score_band` | Distribution across risk tiers — are we too conservative? | Business View - Score Band Distribution |
| `gerald_avg_credit_limit_dollars` | Average limit granted — trending up = more user value | Business View - Credit Limit Trend |
| `gerald_credit_limit_bucket` | How many users land in each dollar tier | Business View - Limit Distribution |

**Alerts you'll receive:**
- Approval rate drops >20% vs 24h baseline (Slack: `#bnpl-product-alerts`)
- Average credit limit drops >30% vs 7d baseline (Slack: `#bnpl-product-alerts`)

**What to do:** Check if a recent deployment changed scoring thresholds, or if bank data quality has degraded.

### Finance Team

**Monitoring default risk exposure:**

| Metric | What It Tells You |
|--------|-------------------|
| `gerald_total_amount_granted_cents` | Total dollars at risk |
| `gerald_decision_by_score_band` (declined) | Volume of denials — too many = lost revenue, too few = risk |
| `gerald_credit_limit_bucket` by outcome | Dollar exposure by tier |

**Key ratios to track:**
- **Approval rate** should be 40-60%. Below 40% = too conservative (lost revenue). Above 60% = too permissive (default risk).
- **Average limit** should track with user quality. If average limit drops while volume stays flat, the risk model is tightening.

### Support Team

**How to explain declines to users:**

The decision response includes `decision_factors` with transparent risk signals:

```json
{
  "approved": false,
  "decision_factors": {
    "risk_score": 15,
    "avg_daily_balance_dollars": -50.00,
    "income_ratio": 0.6,
    "nsf_count": 7,
    "credit_band": "denied"
  }
}
```

**Common decline reasons and suggested responses:**

| Factor | User-Friendly Explanation |
|--------|--------------------------|
| High NSF count | "Your account shows several overdraft events. We recommend building a positive balance pattern and trying again in 30 days." |
| Low income ratio | "Your recent spending appears to exceed your income. We want to make sure an advance won't put you in a difficult position." |
| Thin file | "We don't have enough transaction history to make a decision yet. Please try again after 30 days of account activity." |
| Negative balance | "Your average account balance has been negative. We recommend maintaining a positive balance and reapplying." |

### Engineering Team

**Key technical metrics:**

| Metric | Healthy Range | Alert Threshold |
|--------|---------------|-----------------|
| `decision_latency_seconds` P95 | < 1s | > 5s |
| `http_requests_total` (5xx) | < 0.5% | > 2% |
| `bank_fetch_failures_total` | < 2% | > 10% |
| `webhook_queue_depth` | 0-10 | > 100 |
| `gerald_bank_fetch_latency_seconds` P95 | < 2s | > 10s |

**Debugging a failed decision:**

1. Find the request by `X-Request-ID` header (returned in every response)
2. Search structured logs for `request_id=<id>`:
   - `decision_requested` — start of flow
   - `bank_api_request_completed` — did bank API succeed? How long?
   - `risk_scored` — full score breakdown with all components
   - `decision_made` — final outcome
   - `webhook_send_completed` — did ledger notification succeed?
3. Check Prometheus metrics for patterns (was this one request or a systemic issue?)

**Runbooks:**
- High error rate: Check DB connectivity, then Bank API health
- Bank API failures: Check `bank_fetch_failures_total` by `error_type` label (timeout, connection_error, http_error, not_found)
- Webhook backlog: Check Ledger service health, review `webhook_latency_seconds`

---

## How to Run

### Prerequisites

- Docker and Docker Compose
- Python 3.12+
- Poetry (for local development)

### Quick Start

```bash
# Start all services (DB, Bank mock, Ledger mock, Service)
docker compose up -d

# Verify service is running
curl http://localhost:8000/health
# → {"status": "ok", "service": "gerald-gateway"}
```

### Make a Decision

```bash
curl -X POST http://localhost:8000/v1/decision \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_good", "amount_cents_requested": 40000}'
```

Test users available: `user_good`, `user_gig`, `user_overdraft`, `user_highutil`, `user_thin`

### View Metrics

```bash
# Prometheus metrics endpoint
curl http://localhost:8000/metrics
```

### Running Tests

```bash
# Install dependencies
poetry install

# Unit tests (no external dependencies needed)
python -m pytest tests/test_risk_logic.py tests/test_scoring_sample.py -v

# Integration tests (requires running DB)
docker compose up -d db
python -m pytest tests/test_decision_integration.py -v

# All tests
python -m pytest tests/ -v
```

### Local Development

```bash
# Install dependencies
poetry install

# Start dependencies
docker compose up -d db bank ledger

# Run the service locally
uvicorn service.main:app --reload --host 0.0.0.0 --port 8000
```

### Terraform (Datadog Alerts)

```bash
cd terraform/
terraform init
terraform plan \
  -var="datadog_api_key=YOUR_KEY" \
  -var="datadog_app_key=YOUR_KEY"
terraform apply \
  -var="datadog_api_key=YOUR_KEY" \
  -var="datadog_app_key=YOUR_KEY"
```

---

## Architecture

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│  Client  │────>│  FastAPI      │────>│ Bank API │
│          │<────│  Service      │<────│ (mock)   │
└──────────┘     │              │     └──────────┘
                 │  ┌────────┐  │
                 │  │Scoring │  │     ┌──────────┐
                 │  │Engine  │  │────>│PostgreSQL│
                 │  └────────┘  │     └──────────┘
                 │              │
                 │  ┌────────┐  │     ┌──────────┐
                 │  │Webhook │  │────>│ Ledger   │
                 │  │Service │  │     │ (mock)   │
                 │  └────────┘  │     └──────────┘
                 └──────────────┘
                        │
                 ┌──────────────┐
                 │  /metrics    │───> Prometheus/Datadog
                 └──────────────┘
```

### Key Files

| Path | Purpose |
|------|---------|
| `service/main.py` | FastAPI app, middleware, metrics endpoint |
| `service/api/routes.py` | API route handlers |
| `service/scoring/calculator.py` | Risk scoring logic (documented thresholds) |
| `service/scoring/credit_limit.py` | Score-to-limit mapping |
| `service/services/decision.py` | Decision orchestration |
| `service/services/bank_client.py` | Bank API client |
| `service/services/webhook.py` | Webhook delivery with retries |
| `service/metrics.py` | Prometheus metric definitions |
| `service/logging.py` | Structured logging with request tracing |
| `terraform/monitors.tf` | Datadog alert definitions |
| `metrics/dashboard_datadog.json` | Datadog dashboard config |

---

## Future Improvements

### With More Time

- **Circuit breaker for Bank API** — Currently retries blindly. A circuit breaker would fail fast during Bank API outages, reducing latency and freeing resources.
- **Async webhook delivery** — Move webhook sending to a background task queue (e.g., Celery/Redis) instead of inline. This removes webhook latency from the decision response path.
- **Decision caching** — Cache recent decisions to handle duplicate requests without re-scoring. Useful for mobile app retries.
- **A/B testing framework** — Deploy multiple scoring models simultaneously to compare approval rates and default rates against each other.
- **Rate limiting** — Protect against abuse by limiting decision requests per user_id.

### Improving Approval Accuracy

- **ML-based scoring** — Replace threshold-based rules with a gradient-boosted model trained on actual default data. The current rules are a reasonable starting point but a trained model would capture nonlinear interactions between factors.
- **Time-weighted scoring** — Weight recent transactions more heavily than older ones. A user who had overdrafts 80 days ago but has been clean for 60 days should score better than the reverse.
- **Velocity checks** — Track how quickly a user's balance is declining. A rapidly draining account is riskier than a stable low balance.
- **Category-based spending analysis** — Distinguish essential spending (rent, groceries) from discretionary. Essential spending is more predictable for repayment planning.

### Additional Data That Would Help

| Data Source | Benefit |
|-------------|---------|
| **Previous BNPL repayment history** | Best predictor — did they repay before? |
| **Income verification (payroll API)** | Confirmed income vs inferred from deposits |
| **Rent/utility payment history** | Shows payment discipline outside banking |
| **Device/behavioral signals** | Fraud detection, not creditworthiness |
| **Multiple bank accounts** | Complete financial picture (current view is single-account) |
| **Employer data** | Employment stability correlates with repayment |
