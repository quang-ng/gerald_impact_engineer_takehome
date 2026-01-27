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

---

## Questions & Answers

### 1. Diagnosing an Approval Rate Drop (35% → lower)

If Product sees the `gerald_approval_rate_1h` metric drop, they need to distinguish between a code bug and a real shift in user quality. Here's the playbook:

**Check for code bugs first (fastest to rule out):**

- **Recent deployments** — Did a deploy go out in the last 24 hours? Compare the timing of the drop against the deploy log. If the drop correlates exactly with a release, it's likely a code change.
- **Score distribution shift** — Look at `gerald_decision_by_score_band` on the dashboard. If the entire distribution shifted left (everyone scoring lower), that points to a scoring logic bug or a broken input. If only one band changed, it's more targeted.
- **Bank API data quality** — Check `bank_fetch_failures_total`. If the Bank API is returning errors or empty transaction arrays, every user will score 0 (denied). This looks like an approval rate crash but is actually an upstream data issue.
- **Single component check** — Query the structured logs for `risk_scored` events and look at individual component scores. If one component (e.g., `avg_daily_balance`) is suddenly 0 for all users while others are normal, there's a bug in that specific calculation.

**If it's not a bug, investigate user quality:**

- **Cohort analysis** — Compare the score distributions of this week's applicants vs. last week's. If the new cohort genuinely has lower balances, higher NSF counts, or thinner files, the model is working correctly — the population shifted.
- **Acquisition channel** — If Gerald recently changed marketing or onboarding channels, the new user mix may skew riskier. Correlate approval rate drops with marketing campaign launches.
- **Seasonal patterns** — End-of-month or post-holiday periods naturally have more financially stressed users. Check if the drop aligns with known seasonal patterns.

**Decision framework:** If the drop is sudden (minutes/hours) → likely a bug. If gradual (days/weeks) → likely user quality. If correlated with a deploy → definitely investigate the code first.

### 2. Market Segmentation — Targeting Higher-Income Users

If Gerald pivots from paycheck-to-paycheck users to higher-income users, several model changes are needed:

**Scoring threshold adjustments:**

| Component | Current (paycheck-to-paycheck) | Higher-Income Target |
|-----------|-------------------------------|---------------------|
| Avg Daily Balance | $1,000 = max points | $5,000+ = max points |
| Income Ratio | 1.3 = excellent | 1.5+ = excellent (higher surplus expected) |
| NSF Tolerance | 1-2 events = moderate | 0 events expected (any NSF is a red flag for this segment) |
| Credit Limits | $100-$600 | $500-$2,500 (higher limits match higher spending) |

**Structural changes:**

- **Raise the floor, raise the ceiling** — The current $100-$600 limit range is designed for small advances. Higher-income users expect larger amounts. The scoring bands would shift to $500 / $1,000 / $1,500 / $2,000 / $2,500.
- **Income regularity matters more** — Higher-income users are more likely to have stable W-2 income. Increase the weight of income regularity from 15% to 25% of the score.
- **NSF becomes binary** — For higher-income users, any NSF event is a strong negative signal (it suggests spending beyond means despite high income). Change from a gradient (0/1-2/3-4/5+) to binary (0 = full points, any = significant penalty).
- **Thin file penalty less relevant** — Higher-income users typically have longer banking history. Could reduce the penalty or replace it with an account age requirement.

**Business model impact:**

- Higher limits mean higher default exposure per user. Gerald would need either higher merchant fee revenue per transaction or external credit data (bureau scores) to justify the risk.
- The $0-fee model becomes harder to sustain at higher limits — a single $2,500 default requires 50x more revenue to offset than a $50 default.

### 3. User Communication — Explaining a Decline

When a user is denied and frustrated, the goal is to be **specific enough to feel fair, actionable enough to feel hopeful, and honest without exposing internal scoring details**.

**Example response for a user with high NSF count and low balance:**

> "We reviewed your recent bank activity and weren't able to approve an advance right now. Here's what we looked at:
>
> - Your account has had several overdraft events recently, which tells us you might be in a tight spot financially. We don't want to add to that stress with an advance that could be hard to repay.
> - Your recent account balance has been lower than what we typically see for approvals.
>
> **What you can do:**
> - Focus on building a positive balance over the next 30 days
> - Avoid overdrafts if possible — even one fewer makes a difference
> - Reapply after 30 days — we'll look at your most recent 90 days of activity, so improvements show up quickly
>
> We're not saying no forever — we're saying not right now. Gerald doesn't charge fees, which means we need to be careful about when we extend advances. We'd rather wait until we're confident the advance helps you rather than puts you in a harder position."

**Principles behind this approach:**

1. **Name the factors, not the scores** — Users understand "overdraft events" and "low balance." They don't understand "NSF score: 0/25."
2. **Frame as protection, not rejection** — "We don't want to add to financial stress" positions Gerald as looking out for them.
3. **Give concrete next steps** — "30 days" and "avoid overdrafts" are actionable. Vague advice like "improve your finances" feels dismissive.
4. **Leave the door open** — "Not right now" is different from "no." The 90-day window means real improvements are reflected quickly.

### 4. Business Math — Break-Even Approval Rate

**Given:**
- Revenue per approved user: $50 (Cornerstore merchant fee)
- Default rate: 3%
- Average advance amount (assumed): $300 (midpoint of $100-$600 range)
- Gerald's fee model: $0 fees — defaults are pure loss

**Calculation:**

For every 100 approved users:
- Revenue: 100 × $50 = **$5,000**
- Defaults: 100 × 3% = 3 users default
- Loss per default: $300 (average advance amount, unrecovered)
- Total default loss: 3 × $300 = **$900**

**Net revenue per 100 approved users:** $5,000 - $900 = **$4,100**

**Break-even analysis — what approval rate makes the business viable?**

The question is really: at what approval rate does the revenue from approved users cover the cost of defaults?

Per approved user:
- Expected revenue: $50
- Expected loss: 3% × $300 = $9

**Profit per approved user: $50 - $9 = $41**

Since every approved user is net positive ($41 profit), the break-even approval rate is technically **any rate > 0%** — every approval is profitable at 3% default rate.

**The real question is: what default rate breaks even?**

Break-even when: Revenue = Default Loss
- $50 = default_rate × $300
- default_rate = $50 / $300 = **16.7%**

If the default rate stays below 16.7%, every approved user is profitable. At the current 3% default rate, Gerald has significant margin.

**What the approval rate actually affects:**

- **Too low (< 30%)**: Revenue left on the table. Users who would repay are being denied.
- **Too high (> 70%)**: Default rate likely rises as riskier users are approved. If defaults climb past 16.7%, the model loses money.
- **Sweet spot (40-60%)**: Balances revenue capture with risk management. The current model targets this range.

**Sensitivity analysis:**

| Default Rate | Loss per Approval | Profit per Approval | Viable? |
|-------------|-------------------|--------------------|---------|
| 3% | $9 | $41 | Yes — healthy margin |
| 5% | $15 | $35 | Yes |
| 10% | $30 | $20 | Yes — margin thinning |
| 16.7% | $50 | $0 | Break-even |
| 20% | $60 | -$10 | No — losing money |

### 5. Scalability — Model Changes with More Data

#### 6 Months of Transaction History (vs. 90 Days)

**What improves:**

- **Seasonal pattern detection** — 90 days misses quarterly cycles (tax refunds, insurance payments, seasonal employment). 6 months captures two full cycles, reducing false signals from temporary spikes or dips.
- **Trend analysis becomes possible** — With 180 days, you can compare the first 90 days vs. the last 90 days. A user whose balance is trending up is lower risk than one trending down, even if both have the same average.
- **Thin file problem shrinks** — More history means fewer users penalized for insufficient data. The thin file penalty threshold could move from 30 transactions to 60.

**What I'd change in the model:**

- **Add a time-weighted scoring component** — Split the window into 3 periods (0-60, 60-120, 120-180 days). Weight recent behavior at 50%, middle at 30%, oldest at 20%. This captures trajectory, not just snapshot.
- **Reduce thin file penalty weight** — With 6 months of data available, users with < 30 transactions are more concerning (they've had 6 months to generate activity). Increase the penalty for very thin files.
- **Add a stability score** — Measure the variance of monthly balances across 6 months. Low variance = stable finances = lower risk. This isn't meaningful with only 3 months.

#### Access to Credit Bureau Data

**What improves:**

- **Cross-lender visibility** — Bank transactions only show one account. Bureau data reveals total debt load, other BNPL usage, credit card utilization, and payment history across all creditors.
- **Validated identity and fraud reduction** — Bureau pulls confirm identity and flag known fraud patterns.
- **Proven predictive power** — FICO/VantageScore models are trained on millions of outcomes. Our 4-component model is a reasonable proxy, but bureau data is strictly superior for predicting default.

**What I'd change in the model:**

- **Add bureau score as a scoring component** — Weight it at 25-30 points (the largest single component). Reduce other components proportionally since bureau data already captures payment behavior.
- **Use bureau as a gate, not just a score** — Users with active collections, recent bankruptcy, or 90+ day delinquencies get auto-denied regardless of bank transaction health. These are signals our transaction data can't see.
- **Increase credit limits for bureau-verified users** — Users with FICO > 680 and clean bureau history could qualify for higher limits ($800-$1,000) since the risk is better quantified.
- **Keep bank transaction scoring for thin-bureau users** — Young users or recent immigrants may have thin bureau files but healthy bank activity. The current model becomes the fallback for this segment.

#### Rent/Utility Payment History

**What improves:**

- **Payment discipline signal** — Rent and utilities are recurring obligations with fixed due dates. Consistent on-time payment is a strong indicator of someone who prioritizes obligations — exactly the behavior that predicts BNPL repayment.
- **Coverage for credit-invisible users** — Many of Gerald's target users (paycheck-to-paycheck, younger demographics) may not have credit cards or loans, but they do pay rent and utilities. This data fills a gap.

**What I'd change in the model:**

- **Add a "payment discipline" component (0-20 points):**

  | Pattern | Points | Why |
  |---------|--------|-----|
  | 6+ months on-time rent + utilities | 20 | Strong payment discipline |
  | 3-6 months on-time | 15 | Good pattern forming |
  | Occasional late (1-2 in 6 months) | 8 | Minor issues |
  | Frequent late or missed | 0 | Payment discipline concern |

- **Reduce NSF component weight** — Rent/utility payment history partially overlaps with what NSF measures (ability to meet obligations). Reduce NSF from 25 to 20 points, add payment discipline at 20 points. Total remains 100.
- **Use rent amount as income validation** — If someone pays $1,500/month rent consistently, their income must be at least $4,500-$5,000/month (assuming 30% housing ratio). This cross-validates the income we infer from bank deposits.
- **Late rent as an early warning** — A user who's current on everything but just paid rent late for the first time is showing early financial stress. This could trigger a reduced limit rather than waiting for overdrafts to appear.
