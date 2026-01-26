"""API route handlers for the BNPL decision service."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from service.database import get_db
from service.logging import get_logger, set_request_context, log_decision
from service.schemas import (
    DecisionRequest, DecisionResponse,
    PlanResponse,
    DecisionHistoryResponse
)
from service.services.decision import DecisionService
from service.services.webhook import WebhookService
from service.services.bank_client import BankApiError
from service import metrics

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["decisions"])


@router.post("/decision", response_model=DecisionResponse)
async def make_decision(
    request_body: DecisionRequest,
    request: Request,
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
    start_time = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")

    # Set user context for logging
    set_request_context(request_id, user_id=request_body.user_id)

    logger.info(
        "decision_requested",
        user_id=request_body.user_id,
        amount_cents_requested=request_body.amount_cents_requested,
    )

    # Track requested amount
    metrics.record_requested_amount(request_body.amount_cents_requested)

    decision_service = DecisionService(db)

    try:
        # Fetch transactions and log
        logger.info("bank_fetch_started", user_id=request_body.user_id)

        response = await decision_service.make_decision(request_body)

        duration_seconds = time.perf_counter() - start_time
        duration_ms = duration_seconds * 1000

        # Log the decision with all required fields
        log_decision(
            logger=logger,
            user_id=request_body.user_id,
            approved=response.approved,
            credit_limit_cents=response.credit_limit_cents,
            amount_granted_cents=response.amount_granted_cents,
            risk_score=response.decision_factors.risk_score,
            score_band=_get_score_band(response.decision_factors.risk_score),
            duration_ms=duration_ms,
        )

        # Record all decision metrics
        metrics.record_decision(
            approved=response.approved,
            credit_limit_cents=response.credit_limit_cents,
            amount_granted_cents=response.amount_granted_cents,
            score_band=_get_score_band(response.decision_factors.risk_score),
            latency_seconds=duration_seconds,
        )

        # Send webhook notification (fire and forget)
        try:
            webhook_start = time.perf_counter()
            webhook_service = WebhookService(db)

            logger.info("webhook_send_started", user_id=request_body.user_id)

            await webhook_service.send_decision_webhook({
                "event": "decision.created",
                "user_id": request_body.user_id,
                "approved": response.approved,
                "credit_limit_cents": response.credit_limit_cents,
                "amount_granted_cents": response.amount_granted_cents,
                "plan_id": response.plan_id,
            })

            webhook_duration = time.perf_counter() - webhook_start
            logger.info(
                "webhook_send_completed",
                user_id=request_body.user_id,
                duration_ms=round(webhook_duration * 1000, 2),
            )

            # Record webhook metrics
            metrics.record_webhook_delivery(success=True, latency_seconds=webhook_duration)

        except Exception as e:
            webhook_duration = time.perf_counter() - webhook_start
            # Don't fail the request if webhook fails
            logger.error(
                "webhook_send_failed",
                user_id=request_body.user_id,
                error=str(e),
            )
            metrics.record_webhook_delivery(success=False, latency_seconds=webhook_duration)

        return response

    except BankApiError as e:
        duration_seconds = time.perf_counter() - start_time

        logger.error(
            "decision_failed",
            user_id=request_body.user_id,
            duration_ms=round(duration_seconds * 1000, 2),
            error=str(e),
            outcome="error",
        )

        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"User not found: {request_body.user_id}")
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
    start_time = time.perf_counter()

    logger.info("plan_fetch_requested", plan_id=plan_id)

    decision_service = DecisionService(db)
    plan = decision_service.get_plan(plan_id)

    duration_ms = (time.perf_counter() - start_time) * 1000

    if not plan:
        logger.warning(
            "plan_not_found",
            plan_id=plan_id,
            duration_ms=round(duration_ms, 2),
            outcome="not_found",
        )
        raise HTTPException(status_code=404, detail="Plan not found")

    logger.info(
        "plan_fetch_completed",
        plan_id=plan_id,
        user_id=plan.user_id,
        duration_ms=round(duration_ms, 2),
        outcome="success",
    )

    return plan


@router.get("/decision/history", response_model=DecisionHistoryResponse)
async def get_decision_history(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get decision history for a user.

    Returns all past BNPL decisions for the specified user,
    ordered by most recent first.
    """
    start_time = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")
    set_request_context(request_id, user_id=user_id)

    logger.info("history_fetch_requested", user_id=user_id)

    decision_service = DecisionService(db)
    history = decision_service.get_decision_history(user_id)

    duration_ms = (time.perf_counter() - start_time) * 1000

    logger.info(
        "history_fetch_completed",
        user_id=user_id,
        decision_count=len(history.decisions),
        duration_ms=round(duration_ms, 2),
        outcome="success",
    )

    return history


def _get_score_band(score: int) -> str:
    """Map a score to its band name for metrics."""
    if score >= 85:
        return "maximum"
    elif score >= 75:
        return "premium"
    elif score >= 65:
        return "enhanced"
    elif score >= 55:
        return "standard"
    elif score >= 40:
        return "basic"
    elif score >= 20:
        return "entry"
    else:
        return "denied"
