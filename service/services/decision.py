"""Decision service for BNPL approvals."""
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from service.models import BnplDecision, BnplPlan, BnplInstallment
from service.schemas import (
    DecisionRequest, DecisionResponse, DecisionFactors,
    PlanResponse, InstallmentSchema,
    DecisionHistoryResponse, DecisionHistoryItem
)
from service.scoring import RiskCalculator, score_to_credit_limit
from service.scoring.credit_limit import get_amount_granted
from service.services.bank_client import BankClient, BankApiError

logger = structlog.get_logger()


class DecisionService:
    """
    Service for making BNPL decisions.

    This service orchestrates:
    1. Fetching transaction data from the bank API
    2. Calculating risk scores
    3. Mapping scores to credit limits
    4. Persisting decisions to the database
    5. Creating repayment plans for approved decisions
    """

    def __init__(self, db: Session, bank_client: Optional[BankClient] = None):
        """
        Initialize the decision service.

        Args:
            db: SQLAlchemy database session
            bank_client: Bank API client (defaults to new instance)
        """
        self.db = db
        self.bank_client = bank_client or BankClient()
        self.risk_calculator = RiskCalculator()

    async def make_decision(self, request: DecisionRequest) -> DecisionResponse:
        """
        Make a BNPL decision for a user.

        Args:
            request: Decision request with user_id and amount_cents_requested

        Returns:
            DecisionResponse with approval status, limits, and risk factors
        """
        logger.info("processing_decision",
                   user_id=request.user_id,
                   amount_requested=request.amount_cents_requested)

        # Fetch transactions from bank
        try:
            bank_data = await self.bank_client.get_transactions(request.user_id)
            transactions = bank_data.get("transactions", [])
        except BankApiError as e:
            if e.status_code == 404:
                # User not found - treat as thin file (no transactions)
                logger.info("user_not_found_treating_as_thin_file",
                           user_id=request.user_id)
                transactions = []
            else:
                raise

        # Calculate risk score
        risk_score = self.risk_calculator.calculate(transactions)

        # Map score to credit limit
        credit_limit_cents, score_band = score_to_credit_limit(risk_score.total_score)

        # Determine approval and amount granted
        approved = credit_limit_cents > 0
        amount_granted_cents = get_amount_granted(
            credit_limit_cents, request.amount_cents_requested
        ) if approved else 0

        # Create decision factors for response
        decision_factors = DecisionFactors(
            avg_daily_balance=risk_score.avg_daily_balance_dollars,
            income_ratio=risk_score.factors.income_ratio,
            nsf_count=risk_score.factors.nsf_count,
            risk_score=risk_score.total_score,
        )

        # Persist decision
        decision = BnplDecision(
            id=uuid.uuid4(),
            user_id=request.user_id,
            requested_cents=request.amount_cents_requested,
            approved=approved,
            credit_limit_cents=credit_limit_cents,
            amount_granted_cents=amount_granted_cents,
            score_numeric=risk_score.total_score,
            score_band=score_band,
            risk_factors={
                "avg_daily_balance_cents": risk_score.factors.avg_daily_balance_cents,
                "income_ratio": risk_score.factors.income_ratio,
                "nsf_count": risk_score.factors.nsf_count,
                "negative_balance_days": risk_score.factors.negative_balance_days,
                "transaction_count": risk_score.factors.transaction_count,
                "income_regularity_score": risk_score.factors.income_regularity_score,
            },
        )
        self.db.add(decision)

        # Create plan if approved
        plan_id = None
        if approved and amount_granted_cents > 0:
            plan = self._create_repayment_plan(decision, request.user_id, amount_granted_cents)
            plan_id = str(plan.id)

        self.db.commit()

        logger.info("decision_made",
                   user_id=request.user_id,
                   approved=approved,
                   credit_limit_cents=credit_limit_cents,
                   amount_granted_cents=amount_granted_cents,
                   risk_score=risk_score.total_score,
                   score_band=score_band)

        return DecisionResponse(
            approved=approved,
            credit_limit_cents=credit_limit_cents,
            amount_granted_cents=amount_granted_cents,
            plan_id=plan_id,
            decision_factors=decision_factors,
        )

    def _create_repayment_plan(
        self, decision: BnplDecision, user_id: str, amount_cents: int
    ) -> BnplPlan:
        """
        Create a repayment plan with 4 bi-weekly installments.

        Gerald's standard repayment schedule:
        - 4 installments over 8 weeks
        - Bi-weekly payments aligned with typical payroll cycles
        - Equal installments (with rounding adjustment on last payment)
        """
        plan = BnplPlan(
            id=uuid.uuid4(),
            decision_id=decision.id,
            user_id=user_id,
            total_cents=amount_cents,
        )
        self.db.add(plan)

        # Calculate installment amounts (4 bi-weekly payments)
        num_installments = 4
        base_amount = amount_cents // num_installments
        remainder = amount_cents % num_installments

        start_date = datetime.now().date()

        for i in range(num_installments):
            due_date = start_date + timedelta(weeks=2 * (i + 1))
            # Add remainder to last installment
            installment_amount = base_amount + (remainder if i == num_installments - 1 else 0)

            installment = BnplInstallment(
                id=uuid.uuid4(),
                plan_id=plan.id,
                due_date=due_date,
                amount_cents=installment_amount,
                status="scheduled",
            )
            self.db.add(installment)

        return plan

    def get_plan(self, plan_id: str) -> Optional[PlanResponse]:
        """
        Fetch a repayment plan by ID.

        Args:
            plan_id: UUID of the plan

        Returns:
            PlanResponse or None if not found
        """
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            return None

        plan = self.db.query(BnplPlan).filter(BnplPlan.id == plan_uuid).first()
        if not plan:
            return None

        installments = [
            InstallmentSchema(
                id=str(inst.id),
                due_date=inst.due_date,
                amount_cents=inst.amount_cents,
                status=inst.status,
            )
            for inst in sorted(plan.installments, key=lambda x: x.due_date)
        ]

        return PlanResponse(
            plan_id=str(plan.id),
            user_id=plan.user_id,
            total_cents=plan.total_cents,
            created_at=plan.created_at,
            installments=installments,
        )

    def get_decision_history(self, user_id: str) -> DecisionHistoryResponse:
        """
        Get decision history for a user.

        Args:
            user_id: The user identifier

        Returns:
            DecisionHistoryResponse with list of past decisions
        """
        decisions = (
            self.db.query(BnplDecision)
            .filter(BnplDecision.user_id == user_id)
            .order_by(BnplDecision.created_at.desc())
            .all()
        )

        items = [
            DecisionHistoryItem(
                decision_id=str(d.id),
                user_id=d.user_id,
                requested_cents=d.requested_cents,
                approved=d.approved,
                credit_limit_cents=d.credit_limit_cents,
                amount_granted_cents=d.amount_granted_cents,
                risk_score=d.score_numeric,
                created_at=d.created_at,
            )
            for d in decisions
        ]

        return DecisionHistoryResponse(user_id=user_id, decisions=items)
