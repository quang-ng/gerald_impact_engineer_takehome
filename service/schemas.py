"""Pydantic schemas for request/response validation."""
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    """Request body for POST /v1/decision."""
    user_id: str = Field(..., description="The user identifier")
    amount_cents_requested: int = Field(..., gt=0, description="Amount requested in cents")


class DecisionFactors(BaseModel):
    """Risk factors that influenced the decision."""
    avg_daily_balance: float = Field(..., description="Average daily balance in dollars")
    income_ratio: float = Field(..., description="Income to spending ratio")
    nsf_count: int = Field(..., description="Number of NSF/overdraft events")
    risk_score: int = Field(..., ge=0, le=100, description="Computed risk score (0-100)")


class DecisionResponse(BaseModel):
    """Response body for POST /v1/decision."""
    approved: bool
    credit_limit_cents: int
    amount_granted_cents: int
    plan_id: Optional[str] = None
    decision_factors: DecisionFactors


class InstallmentSchema(BaseModel):
    """Schema for a single installment."""
    id: str
    due_date: date
    amount_cents: int
    status: str


class PlanResponse(BaseModel):
    """Response body for GET /v1/plan/{plan_id}."""
    plan_id: str
    user_id: str
    total_cents: int
    created_at: datetime
    installments: list[InstallmentSchema]


class DecisionHistoryItem(BaseModel):
    """Single item in decision history."""
    decision_id: str
    user_id: str
    requested_cents: int
    approved: bool
    credit_limit_cents: int
    amount_granted_cents: int
    risk_score: Optional[int]
    created_at: datetime


class DecisionHistoryResponse(BaseModel):
    """Response body for GET /v1/decision/history."""
    user_id: str
    decisions: list[DecisionHistoryItem]
