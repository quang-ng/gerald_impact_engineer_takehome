"""API route handlers for the BNPL decision service."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import structlog

from service.database import get_db
from service.schemas import (
    DecisionRequest, DecisionResponse,
    PlanResponse,
    DecisionHistoryResponse
)
from service.services.decision import DecisionService
from service.services.webhook import WebhookService
from service.services.bank_client import BankApiError

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["decisions"])


@router.post("/decision", response_model=DecisionResponse)
async def make_decision(
    request: DecisionRequest,
    db: Session = Depends(get_db),
):
    """
    Request a BNPL decision and credit limit.

    This endpoint:
    1. Fetches the user's bank transaction history
    2. Calculates a risk score based on financial behavior
    3. Maps the score to a credit limit
    4. Creates a repayment plan if approved
    5. Sends a webhook notification to the ledger

    Returns the decision with approval status, credit limit,
    granted amount, plan ID (if approved), and risk factors.
    """
    decision_service = DecisionService(db)

    try:
        response = await decision_service.make_decision(request)

        # Send webhook notification (fire and forget)
        try:
            webhook_service = WebhookService(db)
            await webhook_service.send_decision_webhook({
                "event": "decision.created",
                "user_id": request.user_id,
                "approved": response.approved,
                "credit_limit_cents": response.credit_limit_cents,
                "amount_granted_cents": response.amount_granted_cents,
                "plan_id": response.plan_id,
            })
        except Exception as e:
            # Don't fail the request if webhook fails
            logger.error("webhook_send_failed", error=str(e))

        return response

    except BankApiError as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"User not found: {request.user_id}")
        raise HTTPException(status_code=502, detail=f"Bank API error: {e.detail}")


@router.get("/plan/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
):
    """
    Fetch a repayment plan by ID.

    Returns the plan details including all scheduled installments
    with their due dates and amounts.
    """
    decision_service = DecisionService(db)
    plan = decision_service.get_plan(plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    return plan


@router.get("/decision/history", response_model=DecisionHistoryResponse)
async def get_decision_history(
    user_id: str,
    db: Session = Depends(get_db),
):
    """
    Get decision history for a user.

    Returns all past BNPL decisions for the specified user,
    ordered by most recent first.
    """
    decision_service = DecisionService(db)
    return decision_service.get_decision_history(user_id)
