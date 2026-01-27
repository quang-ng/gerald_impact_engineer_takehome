"""
Tests for risk scoring logic components.

These tests focus on individual scoring components and edge cases
to ensure the risk calculator behaves correctly at boundaries.
"""
from datetime import datetime, timedelta

from service.scoring.calculator import RiskCalculator


class TestAvgDailyBalanceCarryForward:
    """Tests for average daily balance calculation with carry-forward logic."""

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
    ) -> dict:
        """Helper to create a transaction dict."""
        return {
            "transaction_id": f"txn-{date}-{amount_cents}",
            "date": date,
            "amount_cents": amount_cents,
            "type": type,
            "description": "Test transaction",
            "category": "shopping",
            "merchant": "Test Merchant",
            "balance_cents": balance_cents,
            "nsf": nsf,
        }

    def test_balance_carries_forward_on_no_transaction_days(self):
        """Balance should carry forward on days with no transactions."""
        today = datetime.now()

        # Day 0: Balance set to $1000
        # Days 1-9: No transactions (balance should carry forward at $1000)
        # Day 10: Transaction updates balance to $800
        transactions = [
            self._make_transaction(
                (today - timedelta(days=10)).strftime("%Y-%m-%d"),
                100000, "credit", 100000
            ),
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                20000, "debit", 80000
            ),
        ]

        score = self.calculator.calculate(transactions)

        # Average over 11 days: (100000 * 10 + 80000) / 11 = 98181.8
        # Should be close to $1000 due to carry-forward
        assert score.factors.avg_daily_balance_cents >= 90000
        assert score.factors.avg_daily_balance_cents <= 100000

    def test_balance_updates_on_transaction_days(self):
        """Balance should update to transaction's ending balance on that day."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                50000, "credit", 50000
            ),
            self._make_transaction(
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                30000, "credit", 80000
            ),
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                10000, "debit", 70000
            ),
        ]

        score = self.calculator.calculate(transactions)

        # Average: (50000 + 80000 + 70000) / 3 = 66666.67
        assert abs(score.factors.avg_daily_balance_cents - 66667) < 100

    def test_multiple_transactions_same_day_uses_last_balance(self):
        """Multiple transactions on same day should use the last balance."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 100000, "credit", 100000),
            self._make_transaction(today, 20000, "debit", 80000),
            self._make_transaction(today, 30000, "debit", 50000),  # Final balance
        ]

        score = self.calculator.calculate(transactions)

        # Only one day, final balance is $500
        assert score.factors.avg_daily_balance_cents == 50000

    def test_negative_balance_carry_forward(self):
        """Negative balances should also carry forward correctly."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=4)).strftime("%Y-%m-%d"),
                50000, "credit", 50000
            ),
            self._make_transaction(
                (today - timedelta(days=3)).strftime("%Y-%m-%d"),
                80000, "debit", -30000  # Goes negative
            ),
            # Days 2, 1: No transactions, carries -$300
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                10000, "credit", -20000
            ),
        ]

        score = self.calculator.calculate(transactions)

        # Average: (50000 + -30000 + -30000 + -30000 + -20000) / 5 = -12000
        assert score.factors.avg_daily_balance_cents < 0


class TestIncomeSpendRatioCalculation:
    """Tests for income vs spending ratio calculation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.calculator = RiskCalculator(analysis_window_days=90)

    def _make_transaction(
        self,
        date: str,
        amount_cents: int,
        type: str,
        balance_cents: int,
    ) -> dict:
        """Helper to create a transaction dict."""
        return {
            "transaction_id": f"txn-{date}-{amount_cents}-{type}",
            "date": date,
            "amount_cents": amount_cents,
            "type": type,
            "description": "Test transaction",
            "category": "income" if type == "credit" else "shopping",
            "merchant": "Test Merchant",
            "balance_cents": balance_cents,
            "nsf": False,
        }

    def test_basic_ratio_calculation(self):
        """Income ratio should be total credits / total debits."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 100000, "credit", 100000),  # $1000 income
            self._make_transaction(today, 50000, "debit", 50000),     # $500 spend
        ]

        score = self.calculator.calculate(transactions)

        # 100000 / 50000 = 2.0
        assert score.factors.income_ratio == 2.0

    def test_ratio_greater_than_one(self):
        """Ratio > 1 means income exceeds spending."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 150000, "credit", 150000),
            self._make_transaction(today, 100000, "debit", 50000),
        ]

        score = self.calculator.calculate(transactions)

        # 150000 / 100000 = 1.5
        assert score.factors.income_ratio == 1.5
        # Should get high income score (>= 1.3 = 30 points)
        assert score.total_score >= 30  # At least the income component

    def test_ratio_less_than_one(self):
        """Ratio < 1 means spending exceeds income."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 50000, "credit", 50000),
            self._make_transaction(today, 100000, "debit", -50000),
        ]

        score = self.calculator.calculate(transactions)

        # 50000 / 100000 = 0.5
        assert score.factors.income_ratio == 0.5

    def test_zero_debits_returns_zero_ratio(self):
        """Zero debits should result in zero ratio (not division error)."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 100000, "credit", 100000),
        ]

        score = self.calculator.calculate(transactions)

        # With no debits, ratio is 0 (safe default)
        assert score.factors.income_ratio == 0

    def test_multiple_income_and_spend_transactions(self):
        """Should sum all credits and debits correctly."""
        today = datetime.now()
        balance = 0

        transactions = []
        # Multiple income events
        for i in range(3):
            balance += 50000
            transactions.append(self._make_transaction(
                (today - timedelta(days=i)).strftime("%Y-%m-%d"),
                50000, "credit", balance
            ))

        # Multiple spending events
        for i in range(3, 6):
            balance -= 30000
            transactions.append(self._make_transaction(
                (today - timedelta(days=i)).strftime("%Y-%m-%d"),
                30000, "debit", balance
            ))

        score = self.calculator.calculate(transactions)

        # Total credits: 150000, Total debits: 90000
        # Ratio: 150000 / 90000 = 1.67
        assert abs(score.factors.income_ratio - 1.67) < 0.01


class TestNSFCounting:
    """Tests for NSF/overdraft event counting."""

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
    ) -> dict:
        """Helper to create a transaction dict."""
        return {
            "transaction_id": f"txn-{date}-{amount_cents}",
            "date": date,
            "amount_cents": amount_cents,
            "type": type,
            "description": "Test transaction",
            "category": "shopping",
            "merchant": "Test Merchant",
            "balance_cents": balance_cents,
            "nsf": nsf,
        }

    def test_counts_explicit_nsf_flag(self):
        """Should count transactions with nsf=true flag."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 100000, "credit", 100000),
            self._make_transaction(today, 50000, "debit", 50000, nsf=True),
            self._make_transaction(today, 30000, "debit", 20000, nsf=True),
            self._make_transaction(today, 10000, "debit", 10000, nsf=False),
        ]

        score = self.calculator.calculate(transactions)

        assert score.factors.nsf_count == 2

    def test_counts_balance_going_negative(self):
        """Should count when debit causes balance to go from positive to negative."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                100000, "credit", 100000
            ),
            self._make_transaction(
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                50000, "debit", 50000  # Still positive
            ),
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                80000, "debit", -30000  # Goes negative - this is an NSF event
            ),
        ]

        score = self.calculator.calculate(transactions)

        assert score.factors.nsf_count == 1

    def test_already_negative_balance_not_double_counted(self):
        """If already negative, another debit shouldn't count as new NSF."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                50000, "credit", 50000
            ),
            self._make_transaction(
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                80000, "debit", -30000  # First NSF (goes negative)
            ),
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                20000, "debit", -50000  # Already negative, not a new NSF
            ),
        ]

        score = self.calculator.calculate(transactions)

        # Only 1 NSF event (the first one that caused negative)
        assert score.factors.nsf_count == 1

    def test_no_nsf_for_healthy_account(self):
        """Account that stays positive should have 0 NSF count."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                100000, "credit", 100000
            ),
            self._make_transaction(
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                30000, "debit", 70000
            ),
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                20000, "debit", 50000
            ),
        ]

        score = self.calculator.calculate(transactions)

        assert score.factors.nsf_count == 0
        # Should get full NSF score (25 points)
        # Total: balance(15-30) + income(varies) + nsf(25) + regularity(0-15) - thin(-30)
        # With thin file penalty, but 0 NSF should help

    def test_multiple_nsf_events(self):
        """Should correctly count multiple NSF events."""
        today = datetime.now()

        transactions = [
            self._make_transaction(
                (today - timedelta(days=5)).strftime("%Y-%m-%d"),
                100000, "credit", 100000
            ),
            # First NSF
            self._make_transaction(
                (today - timedelta(days=4)).strftime("%Y-%m-%d"),
                150000, "debit", -50000
            ),
            # Recovery
            self._make_transaction(
                (today - timedelta(days=3)).strftime("%Y-%m-%d"),
                80000, "credit", 30000
            ),
            # Second NSF
            self._make_transaction(
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                60000, "debit", -30000
            ),
            # Recovery
            self._make_transaction(
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                50000, "credit", 20000
            ),
            # Third NSF (via flag)
            self._make_transaction(
                today.strftime("%Y-%m-%d"),
                10000, "debit", 10000, nsf=True
            ),
        ]

        score = self.calculator.calculate(transactions)

        # 2 from balance going negative + 1 from flag = 3
        assert score.factors.nsf_count == 3

    def test_credit_transaction_doesnt_trigger_nsf(self):
        """Credit (deposit) transactions should never trigger NSF."""
        today = datetime.now().strftime("%Y-%m-%d")

        transactions = [
            self._make_transaction(today, 50000, "credit", -50000),  # Still negative after credit
        ]

        score = self.calculator.calculate(transactions)

        assert score.factors.nsf_count == 0


class TestScoreBoundaries:
    """Test edge cases at each scoring threshold."""

    def setup_method(self):
        """Set up test fixtures."""
        self.calculator = RiskCalculator(analysis_window_days=90)

    def test_avg_balance_score_boundaries(self):
        """Test scoring at average daily balance thresholds."""
        # Test the private method directly
        calc = self.calculator

        # >= $1000 = 30 points
        assert calc._score_avg_balance(100000) == 30  # $1000
        assert calc._score_avg_balance(150000) == 30  # $1500

        # >= $500 = 25 points
        assert calc._score_avg_balance(50000) == 25   # $500
        assert calc._score_avg_balance(99999) == 25   # $999.99

        # >= $100 = 15 points
        assert calc._score_avg_balance(10000) == 15   # $100
        assert calc._score_avg_balance(49999) == 15   # $499.99

        # >= $0 = 10 points
        assert calc._score_avg_balance(0) == 10       # $0
        assert calc._score_avg_balance(9999) == 10    # $99.99

        # < $0 = 0 points
        assert calc._score_avg_balance(-1) == 0       # -$0.01
        assert calc._score_avg_balance(-100000) == 0  # -$1000

    def test_income_ratio_score_boundaries(self):
        """Test scoring at income ratio thresholds."""
        calc = self.calculator

        # >= 1.3 = 30 points
        assert calc._score_income_ratio(1.3) == 30
        assert calc._score_income_ratio(2.0) == 30

        # >= 1.1 = 25 points
        assert calc._score_income_ratio(1.1) == 25
        assert calc._score_income_ratio(1.29) == 25

        # >= 1.0 = 15 points
        assert calc._score_income_ratio(1.0) == 15
        assert calc._score_income_ratio(1.09) == 15

        # >= 0.8 = 5 points
        assert calc._score_income_ratio(0.8) == 5
        assert calc._score_income_ratio(0.99) == 5

        # < 0.8 = 0 points
        assert calc._score_income_ratio(0.79) == 0
        assert calc._score_income_ratio(0.5) == 0
        assert calc._score_income_ratio(0) == 0

    def test_nsf_count_score_boundaries(self):
        """Test scoring at NSF count thresholds."""
        calc = self.calculator

        # 0 NSF = 25 points
        assert calc._score_nsf_count(0) == 25

        # 1-2 NSF = 15 points
        assert calc._score_nsf_count(1) == 15
        assert calc._score_nsf_count(2) == 15

        # 3-4 NSF = 5 points
        assert calc._score_nsf_count(3) == 5
        assert calc._score_nsf_count(4) == 5

        # 5+ NSF = 0 points
        assert calc._score_nsf_count(5) == 0
        assert calc._score_nsf_count(10) == 0
        assert calc._score_nsf_count(100) == 0

    def test_income_regularity_score_boundaries(self):
        """Test scoring at income regularity thresholds."""
        calc = self.calculator

        # >= 0.8 = 15 points
        assert calc._score_income_regularity(0.8) == 15
        assert calc._score_income_regularity(1.0) == 15

        # >= 0.5 = 10 points
        assert calc._score_income_regularity(0.5) == 10
        assert calc._score_income_regularity(0.79) == 10

        # >= 0.3 = 5 points
        assert calc._score_income_regularity(0.3) == 5
        assert calc._score_income_regularity(0.49) == 5

        # < 0.3 = 0 points
        assert calc._score_income_regularity(0.29) == 0
        assert calc._score_income_regularity(0.1) == 0
        assert calc._score_income_regularity(0) == 0

    def test_thin_file_penalty_boundaries(self):
        """Test thin file penalty at transaction count thresholds."""
        calc = self.calculator

        # >= 30 transactions = 0 penalty
        assert calc._thin_file_penalty(30) == 0
        assert calc._thin_file_penalty(100) == 0

        # 20-29 transactions = -10 penalty
        assert calc._thin_file_penalty(20) == -10
        assert calc._thin_file_penalty(29) == -10

        # 10-19 transactions = -20 penalty
        assert calc._thin_file_penalty(10) == -20
        assert calc._thin_file_penalty(19) == -20

        # < 10 transactions = -30 penalty
        assert calc._thin_file_penalty(9) == -30
        assert calc._thin_file_penalty(1) == -30
        assert calc._thin_file_penalty(0) == -30

    def test_total_score_clamped_to_0_100(self):
        """Total score should be clamped between 0 and 100."""
        now = datetime.now()

        # Create a transaction that would theoretically score above 100
        # Max possible: 30 + 30 + 25 + 15 + 0 = 100
        # This shouldn't exceed 100
        transactions = []
        for i in range(50):  # Enough to avoid thin file penalty
            transactions.append({
                "transaction_id": f"txn-{i}",
                "date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
                "amount_cents": 100000 if i % 2 == 0 else 30000,
                "type": "credit" if i % 2 == 0 else "debit",
                "description": "Test",
                "category": "income" if i % 2 == 0 else "shopping",
                "merchant": "Test",
                "balance_cents": 200000,
                "nsf": False,
            })

        score = self.calculator.calculate(transactions)

        assert score.total_score <= 100
        assert score.total_score >= 0

    def test_minimum_score_is_zero(self):
        """Score should never go below 0 even with thin file penalty."""
        today = datetime.now().strftime("%Y-%m-%d")

        # Create terrible conditions: negative balance, bad ratio, NSF, thin file
        transactions = [
            {
                "transaction_id": "txn-1",
                "date": today,
                "amount_cents": 10000,
                "type": "credit",
                "description": "Test",
                "category": "income",
                "merchant": "Test",
                "balance_cents": -50000,  # Negative balance
                "nsf": True,
            },
            {
                "transaction_id": "txn-2",
                "date": today,
                "amount_cents": 50000,
                "type": "debit",
                "description": "Test",
                "category": "shopping",
                "merchant": "Test",
                "balance_cents": -100000,
                "nsf": True,
            },
        ]

        score = self.calculator.calculate(transactions)

        # Should be 0, not negative
        assert score.total_score == 0
        assert score.total_score >= 0
