"""
Decision Integration Tests for BNPL Service.

These tests verify the full decision flow from API request to response,
including risk scoring, credit limit assignment, and plan creation.

Tests mock external dependencies (bank API, database) to focus on
business logic validation.
"""
import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from service.main import app
from service.scoring.calculator import RiskCalculator


# =============================================================================
# TEST CLIENT FIXTURE
# =============================================================================

@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.query = MagicMock()
    return db


# =============================================================================
# TRANSACTION GENERATORS
# =============================================================================

def generate_transactions(
    days: int = 90,
    income_amount: int = 300000,
    income_frequency: int = 14,
    spending_amount: int = 8000,
    spending_frequency: int = 3,
    starting_balance: int = 100000,
    nsf_days: list = None,
) -> list:
    """Generate realistic transaction history for testing."""
    today = datetime.now()
    transactions = []
    balance = starting_balance
    nsf_days = nsf_days or []

    for i in range(days):
        date = (today - timedelta(days=days - i)).strftime("%Y-%m-%d")

        if i % income_frequency == 0:
            balance += income_amount
            transactions.append({
                "transaction_id": f"inc-{i}",
                "date": date,
                "amount_cents": income_amount,
                "type": "credit",
                "description": "Direct Deposit",
                "category": "income",
                "merchant": None,
                "balance_cents": balance,
                "nsf": False,
            })

        if i % spending_frequency == 0:
            balance -= spending_amount
            nsf = i in nsf_days or balance < 0
            transactions.append({
                "transaction_id": f"exp-{i}",
                "date": date,
                "amount_cents": spending_amount,
                "type": "debit",
                "description": "Purchase",
                "category": "shopping",
                "merchant": "Store",
                "balance_cents": balance,
                "nsf": nsf,
            })

    return transactions


def get_user_good_transactions() -> list:
    """Financially healthy user with high balance, good ratio, no NSF."""
    return generate_transactions(
        days=90,
        income_amount=350000,
        income_frequency=14,
        spending_amount=25000,
        spending_frequency=3,
        starting_balance=150000,
    )


def get_user_highutil_transactions() -> list:
    """High-utilization user with low balance, breakeven ratio."""
    return generate_transactions(
        days=90,
        income_amount=200000,
        income_frequency=14,
        spending_amount=60000,
        spending_frequency=3,
        starting_balance=30000,
    )


def get_user_overdraft_transactions() -> list:
    """User with chronic overdrafts and poor financial health."""
    today = datetime.now()
    transactions = []
    balance = -10000

    for i in range(60):
        date = (today - timedelta(days=60 - i)).strftime("%Y-%m-%d")

        if i % 30 == 0:
            balance += 150000
            transactions.append({
                "transaction_id": f"inc-{i}",
                "date": date,
                "amount_cents": 150000,
                "type": "credit",
                "description": "Payroll",
                "category": "income",
                "merchant": None,
                "balance_cents": balance,
                "nsf": False,
            })

        if i % 5 == 0:
            balance -= 40000
            transactions.append({
                "transaction_id": f"exp-{i}",
                "date": date,
                "amount_cents": 40000,
                "type": "debit",
                "description": "Purchase",
                "category": "shopping",
                "merchant": "Store",
                "balance_cents": balance,
                "nsf": balance < 0,
            })

    return transactions


def get_user_thin_file_transactions() -> list:
    """User with limited transaction history (<10 transactions)."""
    today = datetime.now()
    return [
        {
            "transaction_id": "inc-1",
            "date": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
            "amount_cents": 200000,
            "type": "credit",
            "description": "Payroll",
            "category": "income",
            "merchant": None,
            "balance_cents": 200000,
            "nsf": False,
        },
        {
            "transaction_id": "exp-1",
            "date": (today - timedelta(days=3)).strftime("%Y-%m-%d"),
            "amount_cents": 50000,
            "type": "debit",
            "description": "Purchase",
            "category": "shopping",
            "merchant": "Store",
            "balance_cents": 150000,
            "nsf": False,
        },
        {
            "transaction_id": "exp-2",
            "date": today.strftime("%Y-%m-%d"),
            "amount_cents": 30000,
            "type": "debit",
            "description": "Purchase",
            "category": "shopping",
            "merchant": "Store",
            "balance_cents": 120000,
            "nsf": False,
        },
    ]


def get_user_gig_transactions() -> list:
    """Gig worker with irregular but positive income."""
    today = datetime.now()
    transactions = []
    balance = 50000

    for i in range(60):
        date = (today - timedelta(days=60 - i)).strftime("%Y-%m-%d")

        if i % 5 == 0 or i % 7 == 0:
            amount = 40000 + (i * 1000) % 30000
            balance += amount
            transactions.append({
                "transaction_id": f"gig-{i}",
                "date": date,
                "amount_cents": amount,
                "type": "credit",
                "description": "Gig Payment",
                "category": "income",
                "merchant": "Uber",
                "balance_cents": balance,
                "nsf": False,
            })

        if i % 2 == 0:
            balance -= 12000
            transactions.append({
                "transaction_id": f"exp-{i}",
                "date": date,
                "amount_cents": 12000,
                "type": "debit",
                "description": "Purchase",
                "category": "shopping",
                "merchant": "Store",
                "balance_cents": balance,
                "nsf": False,
            })

    return transactions


def get_user_new_account_transactions() -> list:
    """Brand new account with only 1 transaction."""
    today = datetime.now()
    return [
        {
            "transaction_id": "open-1",
            "date": today.strftime("%Y-%m-%d"),
            "amount_cents": 50000,
            "type": "credit",
            "description": "Initial Deposit",
            "category": "transfer",
            "merchant": None,
            "balance_cents": 50000,
            "nsf": False,
        },
    ]


# =============================================================================
# HELPER: Calculate expected score from transactions
# =============================================================================

def calculate_expected_score(transactions: list) -> dict:
    """Calculate expected score and factors from transactions."""
    calculator = RiskCalculator(analysis_window_days=90)
    score = calculator.calculate(transactions)
    return {
        "risk_score": score.total_score,
        "avg_daily_balance_cents": score.factors.avg_daily_balance_cents,
        "income_ratio": score.factors.income_ratio,
        "nsf_count": score.factors.nsf_count,
        "transaction_count": score.factors.transaction_count,
    }


# =============================================================================
# HELPER: Create mock patches for decision tests
# =============================================================================

def run_decision_test(client, user_id: str, transactions: list, amount_requested: int):
    """Helper to run a decision test with proper mocking."""
    with patch("service.services.decision.BankClient") as mock_bank:
        mock_instance = AsyncMock()
        mock_instance.get_transactions.return_value = {
            "user_id": user_id,
            "transactions": transactions
        }
        mock_bank.return_value = mock_instance

        with patch("service.database.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.add = MagicMock()
            mock_db.commit = MagicMock()
            mock_get_db.return_value = iter([mock_db])

            with patch("service.services.webhook.WebhookService.send_decision_webhook", new_callable=AsyncMock):
                response = client.post("/v1/decision", json={
                    "user_id": user_id,
                    "amount_cents_requested": amount_requested
                })

    return response


# =============================================================================
# APPROVAL TESTS
# =============================================================================

class TestUserGoodApproval:
    """Test approval flow for financially healthy users."""

    def test_user_good_is_approved(self, client):
        """Happy path: approve with plan and correct response."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 40000)

        assert response.status_code == 200
        data = response.json()

        assert data["approved"] is True
        assert data["plan_id"] is not None
        assert data["credit_limit_cents"] > 0
        assert data["amount_granted_cents"] == 40000

    def test_user_good_gets_high_limit(self, client):
        """Good user should receive high credit limit ($400+)."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 60000)

        data = response.json()
        assert data["credit_limit_cents"] >= 40000  # Enhanced tier or better

    def test_user_good_decision_factors_returned(self, client):
        """Decision should include risk factors for transparency."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 40000)

        data = response.json()
        factors = data["decision_factors"]

        assert "risk_score" in factors
        assert "avg_daily_balance_dollars" in factors
        assert "income_ratio" in factors
        assert "nsf_count" in factors
        assert "credit_band" in factors

        assert factors["risk_score"] >= 60
        assert factors["income_ratio"] > 1.0
        assert factors["nsf_count"] == 0


class TestAmountCapping:
    """Test that granted amount is properly capped to credit limit."""

    def test_user_highutil_capped_to_limit(self, client):
        """When requested > limit, grant only up to limit."""
        transactions = get_user_highutil_transactions()

        response = run_decision_test(client, "user_highutil", transactions, 100000)

        data = response.json()

        if data["approved"]:
            granted = data["amount_granted_cents"]
            limit = data["credit_limit_cents"]
            assert granted == limit
            assert granted < 100000

    def test_request_less_than_limit_gets_requested(self, client):
        """When requested < limit, grant the requested amount."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 10000)

        data = response.json()
        assert data["amount_granted_cents"] == 10000


# =============================================================================
# DECLINE TESTS
# =============================================================================

class TestUserOverdraftDecline:
    """Test decline flow for users with poor financial health."""

    def test_user_overdraft_is_declined(self, client):
        """Users with many overdrafts should be declined."""
        transactions = get_user_overdraft_transactions()

        response = run_decision_test(client, "user_overdraft", transactions, 30000)

        data = response.json()

        assert data["approved"] is False
        assert data["plan_id"] is None
        assert data["credit_limit_cents"] == 0
        assert data["amount_granted_cents"] == 0

    def test_overdraft_user_has_high_nsf_count(self, client):
        """Overdraft user decision factors should show high NSF count."""
        transactions = get_user_overdraft_transactions()

        response = run_decision_test(client, "user_overdraft", transactions, 30000)

        data = response.json()
        factors = data["decision_factors"]

        assert factors["nsf_count"] >= 3
        assert factors["risk_score"] < 20


# =============================================================================
# THIN FILE TESTS
# =============================================================================

class TestThinFilePolicy:
    """
    Test policy for users with limited transaction history.

    Gerald's Thin File Policy:
    - < 10 transactions: -30 penalty (very thin)
    - 10-19 transactions: -20 penalty
    - 20-29 transactions: -10 penalty
    - 30+ transactions: no penalty

    Rationale: Limited history creates uncertainty. For Gerald's $0-fee
    model, we need sufficient data to trust observed patterns.
    """

    def test_thin_file_receives_penalty(self, client):
        """Users with thin files should have penalty applied."""
        transactions = get_user_thin_file_transactions()

        response = run_decision_test(client, "user_thin", transactions, 30000)

        data = response.json()

        # With only 3 transactions, thin file penalty (-30) applies
        # Even with good metrics, score should be limited
        assert data["decision_factors"]["risk_score"] <= 55

    def test_very_thin_file_likely_declined(self, client):
        """Brand new accounts should be declined or get minimal limit."""
        transactions = get_user_new_account_transactions()

        response = run_decision_test(client, "user_new", transactions, 30000)

        data = response.json()

        # With 1 transaction: can't calculate ratio, no regularity, max penalty
        if data["approved"]:
            assert data["credit_limit_cents"] <= 10000


# =============================================================================
# GIG WORKER TESTS
# =============================================================================

class TestGigWorkerApproval:
    """Test that gig workers with irregular but positive income are treated fairly."""

    def test_gig_worker_approved_despite_irregularity(self, client):
        """Gig workers should be approved if income exceeds spending."""
        transactions = get_user_gig_transactions()

        response = run_decision_test(client, "user_gig", transactions, 30000)

        data = response.json()

        assert data["approved"] is True
        assert data["credit_limit_cents"] >= 20000

    def test_gig_worker_income_ratio_positive(self, client):
        """Gig worker should have positive income ratio despite irregular timing."""
        transactions = get_user_gig_transactions()

        response = run_decision_test(client, "user_gig", transactions, 30000)

        data = response.json()
        assert data["decision_factors"]["income_ratio"] > 1.0


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_amount_requested(self, client):
        """Requesting $0 should return validation error."""
        response = client.post("/v1/decision", json={
            "user_id": "user_test",
            "amount_cents_requested": 0
        })
        assert response.status_code == 422

    def test_negative_amount_requested(self, client):
        """Requesting negative amount should return validation error."""
        response = client.post("/v1/decision", json={
            "user_id": "user_test",
            "amount_cents_requested": -10000
        })
        assert response.status_code == 422

    def test_very_large_amount_requested(self, client):
        """Requesting very large amount should be capped to limit."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 10000000)

        data = response.json()

        if data["approved"]:
            assert data["amount_granted_cents"] <= 60000
            assert data["amount_granted_cents"] == data["credit_limit_cents"]

    def test_missing_user_id(self, client):
        """Request without user_id should fail validation."""
        response = client.post("/v1/decision", json={
            "amount_cents_requested": 30000
        })
        assert response.status_code == 422

    def test_empty_user_id(self, client):
        """Request with empty user_id should fail validation."""
        response = client.post("/v1/decision", json={
            "user_id": "",
            "amount_cents_requested": 30000
        })
        assert response.status_code == 422

    def test_user_not_found_in_bank(self, client):
        """User not found in bank API should return 404."""
        with patch("service.services.decision.BankClient") as mock_bank:
            from service.services.bank_client import BankApiError
            mock_instance = AsyncMock()
            mock_instance.get_transactions.side_effect = BankApiError(404, "User not found")
            mock_bank.return_value = mock_instance

            with patch("service.database.get_db") as mock_get_db:
                mock_db = MagicMock()
                mock_get_db.return_value = iter([mock_db])

                response = client.post("/v1/decision", json={
                    "user_id": "nonexistent_user",
                    "amount_cents_requested": 30000
                })

        assert response.status_code == 404

    def test_bank_api_error(self, client):
        """Bank API errors should return 502."""
        with patch("service.services.decision.BankClient") as mock_bank:
            from service.services.bank_client import BankApiError
            mock_instance = AsyncMock()
            mock_instance.get_transactions.side_effect = BankApiError(500, "Internal error")
            mock_bank.return_value = mock_instance

            with patch("service.database.get_db") as mock_get_db:
                mock_db = MagicMock()
                mock_get_db.return_value = iter([mock_db])

                response = client.post("/v1/decision", json={
                    "user_id": "user_test",
                    "amount_cents_requested": 30000
                })

        assert response.status_code == 502


# =============================================================================
# PLAN CREATION TESTS
# =============================================================================

class TestPlanCreation:
    """Test that plans are correctly created for approved decisions."""

    def test_approved_decision_creates_plan(self, client):
        """Approved decision should create a repayment plan."""
        transactions = get_user_good_transactions()

        response = run_decision_test(client, "user_good", transactions, 40000)

        data = response.json()

        assert data["approved"] is True
        assert data["plan_id"] is not None

        # Plan ID should be a valid UUID
        try:
            uuid.UUID(data["plan_id"])
        except ValueError:
            pytest.fail("plan_id is not a valid UUID")

    def test_declined_decision_has_no_plan(self, client):
        """Declined decision should not create a plan."""
        transactions = get_user_overdraft_transactions()

        response = run_decision_test(client, "user_overdraft", transactions, 30000)

        data = response.json()

        assert data["approved"] is False
        assert data["plan_id"] is None


# =============================================================================
# SCORE CONSISTENCY TESTS
# =============================================================================

class TestDecisionConsistency:
    """Test that decisions are consistent for the same user data."""

    def test_same_user_gets_consistent_score(self, client):
        """Multiple requests for same user should produce consistent scores."""
        transactions = get_user_good_transactions()
        scores = []

        for _ in range(3):
            response = run_decision_test(client, "user_good", transactions, 40000)
            scores.append(response.json()["decision_factors"]["risk_score"])

        # All scores should be identical
        assert len(set(scores)) == 1


# =============================================================================
# CREDIT BAND MAPPING TESTS
# =============================================================================

class TestCreditBandMapping:
    """Test that scores map correctly to credit bands and limits."""

    def test_score_bands_are_correct(self):
        """Verify score-to-band mapping logic."""
        from service.scoring.credit_limit import score_to_credit_limit

        # Denied: 0-19
        assert score_to_credit_limit(0)[1] == "denied"
        assert score_to_credit_limit(19)[1] == "denied"

        # Entry: 20-39
        assert score_to_credit_limit(20)[1] == "entry"
        assert score_to_credit_limit(39)[1] == "entry"

        # Basic: 40-54
        assert score_to_credit_limit(40)[1] == "basic"
        assert score_to_credit_limit(54)[1] == "basic"

        # Standard: 55-64
        assert score_to_credit_limit(55)[1] == "standard"
        assert score_to_credit_limit(64)[1] == "standard"

        # Enhanced: 65-74
        assert score_to_credit_limit(65)[1] == "enhanced"
        assert score_to_credit_limit(74)[1] == "enhanced"

        # Premium: 75-84
        assert score_to_credit_limit(75)[1] == "premium"
        assert score_to_credit_limit(84)[1] == "premium"

        # Maximum: 85-100
        assert score_to_credit_limit(85)[1] == "maximum"
        assert score_to_credit_limit(100)[1] == "maximum"

    def test_credit_limits_are_correct(self):
        """Verify score-to-limit mapping logic."""
        from service.scoring.credit_limit import score_to_credit_limit

        assert score_to_credit_limit(0)[0] == 0         # Denied
        assert score_to_credit_limit(20)[0] == 10000    # $100 entry
        assert score_to_credit_limit(40)[0] == 20000    # $200 basic
        assert score_to_credit_limit(55)[0] == 30000    # $300 standard
        assert score_to_credit_limit(65)[0] == 40000    # $400 enhanced
        assert score_to_credit_limit(75)[0] == 50000    # $500 premium
        assert score_to_credit_limit(85)[0] == 60000    # $600 maximum
