"""Tests for the BNPL risk scoring and credit limit logic."""
import pytest
from datetime import datetime, timedelta

from service.scoring.calculator import RiskCalculator, RiskScore
from service.scoring.credit_limit import score_to_credit_limit, get_amount_granted


class TestScoreToCreditLimit:
    """Test the score-to-credit-limit mapping."""

    def test_score_boundaries(self):
        """Test that score boundaries map to correct credit limits."""
        # Denied tier (0-19)
        assert score_to_credit_limit(0) == (0, "denied")
        assert score_to_credit_limit(19) == (0, "denied")

        # Entry tier (20-39) - $100
        assert score_to_credit_limit(20) == (10000, "entry")
        assert score_to_credit_limit(39) == (10000, "entry")

        # Basic tier (40-54) - $200
        assert score_to_credit_limit(40) == (20000, "basic")
        assert score_to_credit_limit(54) == (20000, "basic")

        # Standard tier (55-64) - $300
        assert score_to_credit_limit(55) == (30000, "standard")
        assert score_to_credit_limit(64) == (30000, "standard")

        # Enhanced tier (65-74) - $400
        assert score_to_credit_limit(65) == (40000, "enhanced")
        assert score_to_credit_limit(74) == (40000, "enhanced")

        # Premium tier (75-84) - $500
        assert score_to_credit_limit(75) == (50000, "premium")
        assert score_to_credit_limit(84) == (50000, "premium")

        # Maximum tier (85-100) - $600
        assert score_to_credit_limit(85) == (60000, "maximum")
        assert score_to_credit_limit(100) == (60000, "maximum")

    def test_amount_granted(self):
        """Test that granted amount is min of limit and requested."""
        # Request less than limit
        assert get_amount_granted(60000, 40000) == 40000

        # Request more than limit
        assert get_amount_granted(30000, 50000) == 30000

        # Request equal to limit
        assert get_amount_granted(40000, 40000) == 40000


class TestRiskCalculator:
    """Test the risk calculator logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.calculator = RiskCalculator(analysis_window_days=90)

    def _make_transaction(
        self,
        date: str,
        amount_cents: int,
        type: str,
        balance_cents: int,
        nsf: bool = False,
        category: str = "shopping",
    ) -> dict:
        """Helper to create a transaction dict."""
        return {
            "transaction_id": f"txn-{date}-{amount_cents}",
            "date": date,
            "amount_cents": amount_cents,
            "type": type,
            "description": "Test transaction",
            "category": category,
            "merchant": "Test Merchant",
            "balance_cents": balance_cents,
            "nsf": nsf,
        }

    def test_empty_transactions(self):
        """Empty transactions should result in zero score."""
        score = self.calculator.calculate([])
        assert score.total_score == 0
        assert score.factors.transaction_count == 0

    def test_excellent_user(self):
        """User with high balance, good income ratio, no NSF should score high."""
        today = datetime.now()
        transactions = []
        balance = 150000  # Start with $1500

        # Generate 3 months of healthy financial activity
        for i in range(90):
            date = (today - timedelta(days=90-i)).strftime("%Y-%m-%d")

            # Bi-weekly income of $3000
            if i % 14 == 0:
                balance += 300000
                transactions.append(self._make_transaction(
                    date, 300000, "credit", balance, category="income"
                ))

            # Daily spending averaging ~$80/day
            if i % 3 == 0:
                balance -= 8000
                transactions.append(self._make_transaction(
                    date, 8000, "debit", balance
                ))

        score = self.calculator.calculate(transactions)

        # Should be in the high score range
        assert score.total_score >= 70
        assert score.factors.nsf_count == 0
        assert score.factors.income_ratio > 1.0
        assert score.factors.avg_daily_balance_cents > 100000

    def test_risky_user_with_nsf(self):
        """User with NSF events should score lower."""
        today = datetime.now()
        transactions = []
        balance = 10000  # Start low

        for i in range(30):
            date = (today - timedelta(days=30-i)).strftime("%Y-%m-%d")

            # One income event
            if i == 0:
                balance += 200000
                transactions.append(self._make_transaction(
                    date, 200000, "credit", balance, category="income"
                ))

            # Heavy spending causing overdrafts
            if i % 5 == 0:
                balance -= 50000
                nsf = balance < 0
                transactions.append(self._make_transaction(
                    date, 50000, "debit", balance, nsf=nsf
                ))

        score = self.calculator.calculate(transactions)

        # Should have NSF events
        assert score.factors.nsf_count > 0
        # Should score lower
        assert score.total_score < 60

    def test_thin_file_user(self):
        """User with very few transactions should score low."""
        today = datetime.now().strftime("%Y-%m-%d")
        transactions = [
            self._make_transaction(today, 5000, "debit", 45000),
            self._make_transaction(today, 10000, "credit", 55000, category="income"),
        ]

        score = self.calculator.calculate(transactions)

        # Thin file should have low income regularity
        assert score.factors.income_regularity_score < 0.5
        # Limited data means uncertain risk
        assert score.total_score < 50

    def test_gig_worker_pattern(self):
        """Gig worker with irregular but positive income should score reasonably."""
        today = datetime.now()
        transactions = []
        balance = 50000

        for i in range(60):
            date = (today - timedelta(days=60-i)).strftime("%Y-%m-%d")

            # Irregular income (3-7 days apart, variable amounts)
            if i % 5 == 0 or i % 7 == 0:
                amount = 50000 + (i * 1000) % 30000  # Variable $500-$800
                balance += amount
                transactions.append(self._make_transaction(
                    date, amount, "credit", balance, category="income"
                ))

            # Regular spending
            if i % 2 == 0:
                balance -= 15000
                transactions.append(self._make_transaction(
                    date, 15000, "debit", balance
                ))

        score = self.calculator.calculate(transactions)

        # Income ratio should be positive (gig worker is earning more than spending)
        assert score.factors.income_ratio > 1.0
        # Should still be approvable despite irregular timing
        assert score.total_score >= 40

    def test_chronic_overdraft_user(self):
        """User with chronic overdrafts should be denied."""
        today = datetime.now()
        transactions = []
        balance = -50000  # Start negative

        for i in range(30):
            date = (today - timedelta(days=30-i)).strftime("%Y-%m-%d")

            # Minimal income
            if i % 14 == 0:
                balance += 100000
                transactions.append(self._make_transaction(
                    date, 100000, "credit", balance, category="income"
                ))

            # Spending exceeds income, with NSF
            if i % 3 == 0:
                balance -= 40000
                transactions.append(self._make_transaction(
                    date, 40000, "debit", balance, nsf=True
                ))

        score = self.calculator.calculate(transactions)

        # Should have many NSF events
        assert score.factors.nsf_count >= 5
        # Average balance should be negative
        assert score.factors.avg_daily_balance_cents < 0
        # Should be in denial range
        assert score.total_score < 20

    def test_income_ratio_calculation(self):
        """Test that income ratio is calculated correctly."""
        today = datetime.now().strftime("%Y-%m-%d")
        transactions = [
            self._make_transaction(today, 100000, "credit", 100000, category="income"),
            self._make_transaction(today, 50000, "debit", 50000),
        ]

        score = self.calculator.calculate(transactions)

        # Income / Spending = 100000 / 50000 = 2.0
        assert score.factors.income_ratio == 2.0

    def test_average_daily_balance_carry_forward(self):
        """Test that balance is carried forward for days with no transactions."""
        today = datetime.now()
        transactions = [
            # Day 1: Set balance to $1000
            self._make_transaction(
                (today - timedelta(days=10)).strftime("%Y-%m-%d"),
                100000, "credit", 100000, category="income"
            ),
            # Day 10: Still at $1000 (no transactions between)
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                10000, "debit", 90000
            ),
        ]

        score = self.calculator.calculate(transactions)

        # Balance should be carried forward, so average should be close to $1000
        # (100000 for ~9 days, then 90000 for day 10)
        # Average = (100000 * 9 + 90000) / 10 = 99000
        assert score.factors.avg_daily_balance_cents >= 90000


class TestIntegration:
    """Integration tests combining scoring and credit limit logic."""

    def test_full_decision_flow(self):
        """Test the full flow from transactions to credit limit."""
        calculator = RiskCalculator()
        today = datetime.now()

        # Create a "good" user's transaction history
        transactions = []
        balance = 200000

        for i in range(90):
            date = (today - timedelta(days=90-i)).strftime("%Y-%m-%d")

            if i % 14 == 0:  # Bi-weekly income
                balance += 350000
                transactions.append({
                    "transaction_id": f"inc-{i}",
                    "date": date,
                    "amount_cents": 350000,
                    "type": "credit",
                    "description": "Direct Deposit",
                    "category": "income",
                    "merchant": None,
                    "balance_cents": balance,
                    "nsf": False,
                })

            if i % 3 == 0:  # Regular spending
                balance -= 25000
                transactions.append({
                    "transaction_id": f"exp-{i}",
                    "date": date,
                    "amount_cents": 25000,
                    "type": "debit",
                    "description": "Purchase",
                    "category": "shopping",
                    "merchant": "Store",
                    "balance_cents": balance,
                    "nsf": False,
                })

        # Calculate score
        score = calculator.calculate(transactions)

        # Map to credit limit
        limit_cents, band = score_to_credit_limit(score.total_score)

        # Good user should be approved with reasonable limit
        assert limit_cents > 0
        assert band in ["basic", "standard", "enhanced", "premium", "maximum"]

        # Test amount granted
        requested = 40000  # $400
        granted = get_amount_granted(limit_cents, requested)
        assert granted <= limit_cents
        assert granted <= requested
