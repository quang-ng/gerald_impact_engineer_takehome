"""
Risk Calculator for BNPL Decisions

This module implements Gerald's risk scoring logic for Buy Now, Pay Later decisions.
The scoring system is designed to support Gerald's $0-fee business model by:

1. Identifying users who are likely to repay without needing fee-based recovery
2. Balancing approval rates with default risk to maintain profitability
3. Rewarding positive financial behaviors (stable income, low overdrafts)
4. Being inclusive of non-traditional income patterns (gig workers, freelancers)

PHILOSOPHY:
-----------
Gerald's $0-fee model means we cannot rely on late fees or penalty charges to
recover from defaults. This makes risk assessment critical - we need to approve
users who will repay, not users who will generate fee revenue.

Key principles:
- Approve good risks at higher limits to maximize user value
- Deny high risks entirely rather than approve at low limits with high fees
- Reward financial stability over credit history length
- Account for income volatility (gig economy) without penalizing it unfairly
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from service.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Transaction:
    """Represents a single bank transaction."""
    transaction_id: str
    date: str  # YYYY-MM-DD
    amount_cents: int
    type: str  # "debit" or "credit"
    description: str
    category: str
    merchant: Optional[str]
    balance_cents: int
    nsf: bool


@dataclass
class RiskFactors:
    """Computed risk factors from transaction analysis."""
    avg_daily_balance_cents: float
    income_ratio: float  # total_credits / total_debits
    nsf_count: int
    negative_balance_days: int
    transaction_count: int
    income_regularity_score: float  # 0-1, higher = more regular


@dataclass
class RiskScore:
    """Final risk score with component breakdown."""
    total_score: int  # 0-100
    factors: RiskFactors

    @property
    def avg_daily_balance_dollars(self) -> float:
        """Convert average daily balance to dollars for API response."""
        return round(self.factors.avg_daily_balance_cents / 100, 2)


class RiskCalculator:
    """
    Calculates risk scores from transaction data.

    SCORING METHODOLOGY:
    --------------------
    The risk score (0-100) is computed from four components:

    1. Average Daily Balance Score (0-30 points)
       WHY: Users with positive balances have a buffer for repayment.
       A higher average balance indicates financial stability and the
       ability to absorb unexpected expenses without defaulting.

       Thresholds:
       - >= $1000 avg: 30 points (excellent buffer)
       - >= $500 avg:  25 points (good buffer)
       - >= $100 avg:  15 points (minimal buffer)
       - >= $0 avg:    10 points (breakeven, risky)
       - < $0 avg:     0 points (chronically negative)

    2. Income vs. Spending Ratio Score (0-30 points)
       WHY: Users who earn more than they spend can repay from income.
       This is critical for Gerald's model - we want users whose
       natural cash flow will cover the BNPL repayment.

       Thresholds:
       - >= 1.3 ratio: 30 points (strong positive cash flow)
       - >= 1.1 ratio: 25 points (positive cash flow)
       - >= 1.0 ratio: 15 points (breakeven)
       - >= 0.8 ratio: 5 points (slight negative, but manageable)
       - < 0.8 ratio:  0 points (significant cash burn)

    3. NSF/Overdraft Score (0-25 points)
       WHY: NSF events are the strongest predictor of future defaults.
       Users who frequently overdraft lack the cash flow discipline
       needed to repay BNPL advances reliably.

       Thresholds:
       - 0 NSF events:   25 points (excellent)
       - 1-2 NSF events: 15 points (occasional issues)
       - 3-4 NSF events: 5 points (pattern of issues)
       - 5+ NSF events:  0 points (chronic overdrafts)

    4. Income Regularity Score (0-15 points)
       WHY: Regular income (even if variable in amount) suggests
       predictable cash inflows we can time repayment against.

       This component is WEIGHTED LOWER than others because:
       - Gig workers may have irregular income timing but stable totals
       - We don't want to unfairly penalize non-traditional employment
       - The income RATIO already captures total income adequacy

       Thresholds:
       - >= 0.8 regularity: 15 points (very predictable)
       - >= 0.5 regularity: 10 points (somewhat predictable)
       - >= 0.3 regularity: 5 points (irregular but present)
       - < 0.3 regularity:  0 points (highly unpredictable)

    5. Thin File Penalty (0 to -30 points)
       WHY: Limited transaction history creates uncertainty.
       For Gerald's $0-fee model, we need sufficient data to trust
       the patterns we observe. A "thin file" could indicate:
       - Newly opened account (no established behavior)
       - Account specifically opened to obtain BNPL (gaming)
       - Primary banking elsewhere (incomplete picture)

       We apply a penalty rather than deny outright because:
       - New users deserve access if other signals are strong
       - The penalty scales with how thin the file is
       - Combined with other factors, thin file alone won't cause denial

       Thresholds:
       - >= 30 transactions: 0 penalty (sufficient history)
       - 20-29 transactions: -10 penalty (moderate history)
       - 10-19 transactions: -20 penalty (limited history)
       - < 10 transactions:  -30 penalty (very thin file)

    TRADE-OFFS:
    -----------
    - Higher thresholds = fewer approvals but lower default rate
    - Lower thresholds = more approvals but higher default rate

    For Gerald's $0-fee model, we lean conservative because:
    - No fee revenue to offset defaults
    - Customer acquisition cost is high; defaults waste that investment
    - Better to approve fewer users at higher limits than many at low limits
    """

    def __init__(self, analysis_window_days: int = 90):
        """
        Initialize the calculator.

        Args:
            analysis_window_days: Number of days of transaction history to analyze.
                                 Default 90 days balances recency with stability.
        """
        self.analysis_window_days = analysis_window_days

    def calculate(self, transactions: list[dict]) -> RiskScore:
        """
        Calculate risk score from transaction data.

        Args:
            transactions: List of transaction dictionaries from bank API

        Returns:
            RiskScore with total score and component breakdown
        """
        if not transactions:
            logger.warning("no_transactions_found")
            return RiskScore(
                total_score=0,
                factors=RiskFactors(
                    avg_daily_balance_cents=0,
                    income_ratio=0,
                    nsf_count=0,
                    negative_balance_days=0,
                    transaction_count=0,
                    income_regularity_score=0,
                )
            )

        # Convert to Transaction objects
        txns = [Transaction(**t) for t in transactions]

        # Filter to analysis window
        cutoff_date = datetime.now() - timedelta(days=self.analysis_window_days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        txns = [t for t in txns if t.date >= cutoff_str]

        if not txns:
            logger.warning("no_transactions_in_window", window_days=self.analysis_window_days)
            return RiskScore(
                total_score=0,
                factors=RiskFactors(
                    avg_daily_balance_cents=0,
                    income_ratio=0,
                    nsf_count=0,
                    negative_balance_days=0,
                    transaction_count=0,
                    income_regularity_score=0,
                )
            )

        # Sort by date
        txns.sort(key=lambda t: t.date)

        # Calculate factors
        factors = self._compute_factors(txns)

        # Calculate score components
        balance_score = self._score_avg_balance(factors.avg_daily_balance_cents)
        income_score = self._score_income_ratio(factors.income_ratio)
        nsf_score = self._score_nsf_count(factors.nsf_count)
        regularity_score = self._score_income_regularity(factors.income_regularity_score)
        thin_file_penalty = self._thin_file_penalty(factors.transaction_count)

        total_score = balance_score + income_score + nsf_score + regularity_score + thin_file_penalty
        # Clamp to 0-100 range
        total_score = max(0, min(100, total_score))

        logger.info(
            "risk_scored",
            total_score=total_score,
            balance_score=balance_score,
            income_score=income_score,
            nsf_score=nsf_score,
            regularity_score=regularity_score,
            thin_file_penalty=thin_file_penalty,
            transaction_count=factors.transaction_count,
            avg_daily_balance_cents=factors.avg_daily_balance_cents,
            income_ratio=factors.income_ratio,
            nsf_count=factors.nsf_count,
        )

        return RiskScore(total_score=total_score, factors=factors)

    def _compute_factors(self, transactions: list[Transaction]) -> RiskFactors:
        """Compute all risk factors from transactions."""
        # Calculate average daily balance with carry-forward
        avg_balance = self._calculate_avg_daily_balance(transactions)

        # Calculate income ratio
        total_credits = sum(t.amount_cents for t in transactions if t.type == "credit")
        total_debits = sum(t.amount_cents for t in transactions if t.type == "debit")
        income_ratio = total_credits / total_debits if total_debits > 0 else 0

        # Count NSF events (explicit flag OR balance goes negative after debit)
        nsf_count = self._count_nsf_events(transactions)

        # Count days with negative balance
        negative_days = self._count_negative_balance_days(transactions)

        # Calculate income regularity
        regularity = self._calculate_income_regularity(transactions)

        return RiskFactors(
            avg_daily_balance_cents=avg_balance,
            income_ratio=round(income_ratio, 2),
            nsf_count=nsf_count,
            negative_balance_days=negative_days,
            transaction_count=len(transactions),
            income_regularity_score=regularity,
        )

    def _calculate_avg_daily_balance(self, transactions: list[Transaction]) -> float:
        """
        Calculate average daily balance over the analysis window.

        Uses carry-forward logic: for days with no transactions,
        we carry forward the last known balance.
        """
        if not transactions:
            return 0

        # Get date range
        start_date = datetime.strptime(transactions[0].date, "%Y-%m-%d")
        end_date = datetime.strptime(transactions[-1].date, "%Y-%m-%d")

        # Build a map of date -> end-of-day balance
        daily_balances = {}
        for txn in transactions:
            # Use the balance after the transaction
            daily_balances[txn.date] = txn.balance_cents

        # Calculate total balance across all days with carry-forward
        total_balance = 0
        current_date = start_date
        last_balance = transactions[0].balance_cents

        days_count = 0
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in daily_balances:
                last_balance = daily_balances[date_str]
            total_balance += last_balance
            days_count += 1
            current_date += timedelta(days=1)

        return total_balance / days_count if days_count > 0 else 0

    def _count_nsf_events(self, transactions: list[Transaction]) -> int:
        """
        Count NSF/overdraft events.

        An NSF event is either:
        1. Transaction has nsf=true flag
        2. A debit transaction causes balance to go negative
        """
        nsf_count = 0
        prev_balance = None

        for txn in transactions:
            # Check explicit NSF flag
            if txn.nsf:
                nsf_count += 1
            # Check if debit caused negative balance
            elif txn.type == "debit" and txn.balance_cents < 0:
                if prev_balance is not None and prev_balance >= 0:
                    nsf_count += 1
            prev_balance = txn.balance_cents

        return nsf_count

    def _count_negative_balance_days(self, transactions: list[Transaction]) -> int:
        """Count days where the balance was negative."""
        negative_dates = set()
        for txn in transactions:
            if txn.balance_cents < 0:
                negative_dates.add(txn.date)
        return len(negative_dates)

    def _calculate_income_regularity(self, transactions: list[Transaction]) -> float:
        """
        Calculate income regularity score (0-1).

        Higher score = more regular income patterns.
        We look at the consistency of credit (income) transactions.
        """
        income_txns = [t for t in transactions if t.type == "credit"]
        if len(income_txns) < 2:
            return 0

        # Get unique income dates
        income_dates = sorted(set(t.date for t in income_txns))
        if len(income_dates) < 2:
            return 0

        # Calculate gaps between income events
        gaps = []
        for i in range(1, len(income_dates)):
            d1 = datetime.strptime(income_dates[i-1], "%Y-%m-%d")
            d2 = datetime.strptime(income_dates[i], "%Y-%m-%d")
            gaps.append((d2 - d1).days)

        if not gaps:
            return 0

        # Calculate coefficient of variation (lower = more regular)
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap == 0:
            return 1.0

        variance = sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)
        std_dev = variance ** 0.5
        cv = std_dev / avg_gap

        # Convert CV to 0-1 score (lower CV = higher score)
        # CV of 0 = perfectly regular = score 1.0
        # CV of 1+ = very irregular = score 0
        regularity = max(0, 1 - cv)
        return round(regularity, 2)

    def _score_avg_balance(self, avg_balance_cents: float) -> int:
        """
        Score average daily balance (0-30 points).

        Rationale for thresholds:
        - $1000+ buffer: Can absorb a typical BNPL advance ($100-$600)
        - $500+ buffer: Can absorb smaller advances
        - $100+ buffer: Minimal cushion
        - $0+ (positive): At least not in the red
        - Negative: Chronically overdrawn, high risk
        """
        avg_dollars = avg_balance_cents / 100

        if avg_dollars >= 1000:
            return 30
        elif avg_dollars >= 500:
            return 25
        elif avg_dollars >= 100:
            return 15
        elif avg_dollars >= 0:
            return 10
        else:
            return 0

    def _score_income_ratio(self, ratio: float) -> int:
        """
        Score income vs spending ratio (0-30 points).

        Rationale for thresholds:
        - >= 1.3: Strong positive cash flow, 30% income surplus
        - >= 1.1: Healthy positive cash flow, 10% surplus
        - >= 1.0: Breakeven, risky but possible
        - >= 0.8: 20% deficit, marginal
        - < 0.8: Significant cash burn, too risky
        """
        if ratio >= 1.3:
            return 30
        elif ratio >= 1.1:
            return 25
        elif ratio >= 1.0:
            return 15
        elif ratio >= 0.8:
            return 5
        else:
            return 0

    def _score_nsf_count(self, nsf_count: int) -> int:
        """
        Score NSF/overdraft count (0-25 points).

        Rationale for thresholds:
        - 0 NSF: No overdraft history, lowest risk
        - 1-2 NSF: Occasional issues, may be one-time circumstances
        - 3-4 NSF: Pattern emerging, concerning
        - 5+ NSF: Chronic overdrafts, high default risk

        This is heavily weighted because NSF history is the
        strongest predictor of future payment failures.
        """
        if nsf_count == 0:
            return 25
        elif nsf_count <= 2:
            return 15
        elif nsf_count <= 4:
            return 5
        else:
            return 0

    def _score_income_regularity(self, regularity: float) -> int:
        """
        Score income regularity (0-15 points).

        Lower weight than other factors because:
        - Gig economy workers may have irregular timing
        - Total income (captured in ratio) matters more than timing
        - We want to be inclusive of non-traditional employment

        Rationale for thresholds:
        - >= 0.8: Very regular income (e.g., bi-weekly payroll)
        - >= 0.5: Somewhat regular (e.g., gig worker with steady work)
        - >= 0.3: Irregular but present
        - < 0.3: Highly unpredictable
        """
        if regularity >= 0.8:
            return 15
        elif regularity >= 0.5:
            return 10
        elif regularity >= 0.3:
            return 5
        else:
            return 0

    def _thin_file_penalty(self, transaction_count: int) -> int:
        """
        Apply penalty for thin transaction files (0 to -30 points).

        WHY: Limited transaction history creates uncertainty that is
        particularly dangerous for Gerald's $0-fee model. We need enough
        data to trust the patterns we observe.

        Rationale for thresholds:
        - >= 30 transactions: Sufficient history to establish patterns
        - 20-29 transactions: Moderate history, some uncertainty
        - 10-19 transactions: Limited history, significant uncertainty
        - < 10 transactions: Very thin file, high uncertainty

        This is a PENALTY (negative) applied to the base score.
        Combined with positive signals, a thin file user can still
        be approved, but at lower limits.
        """
        if transaction_count >= 30:
            return 0
        elif transaction_count >= 20:
            return -10
        elif transaction_count >= 10:
            return -20
        else:
            return -30
