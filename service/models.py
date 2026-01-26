"""SQLAlchemy ORM models for BNPL decision service."""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, BigInteger, Boolean, DateTime, Date,
    Integer, ForeignKey, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from service.database import Base


class BnplDecision(Base):
    """Records a BNPL approval/denial decision."""
    __tablename__ = "bnpl_decision"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, nullable=False, index=True)
    requested_cents = Column(BigInteger, nullable=False)
    approved = Column(Boolean, nullable=False)
    credit_limit_cents = Column(BigInteger, nullable=False)
    amount_granted_cents = Column(BigInteger, nullable=False)
    score_numeric = Column(BigInteger)  # Stored as 0-100 integer
    score_band = Column(Text)
    risk_factors = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationship to plan
    plan = relationship("BnplPlan", back_populates="decision", uselist=False)


class BnplPlan(Base):
    """Represents a BNPL repayment plan."""
    __tablename__ = "bnpl_plan"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id = Column(UUID(as_uuid=True), ForeignKey("bnpl_decision.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Text, nullable=False, index=True)
    total_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    decision = relationship("BnplDecision", back_populates="plan")
    installments = relationship("BnplInstallment", back_populates="plan", cascade="all, delete-orphan")


class BnplInstallment(Base):
    """Individual installment within a repayment plan."""
    __tablename__ = "bnpl_installment"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("bnpl_plan.id", ondelete="CASCADE"), nullable=False)
    due_date = Column(Date, nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    status = Column(Text, nullable=False, default="scheduled")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationship
    plan = relationship("BnplPlan", back_populates="installments")


class OutboundWebhook(Base):
    """Tracks outbound webhook delivery attempts."""
    __tablename__ = "outbound_webhook"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    target_url = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    last_attempt_at = Column(DateTime(timezone=True))
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
