"""
Structured logging configuration for the BNPL Decision Service.

All logs are JSON-formatted with these standard fields:
- timestamp: ISO 8601 timestamp
- event: The log event name (first positional argument)
- request_id: UUID for tracing requests end-to-end
- user_id: User identifier (when available)
- duration_ms: Operation duration in milliseconds
- outcome: Result of the operation (for decision events)

Note: In structlog, the first positional argument to logger.info/warning/error
becomes the 'event' field in the JSON output automatically.
"""
import time
import uuid
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Optional

import structlog

# Context variables for request-scoped data
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")


def add_context_vars(
    logger: structlog.typing.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Processor that adds context variables to log entries."""
    request_id = request_id_ctx.get()
    user_id = user_id_ctx.get()

    if request_id:
        event_dict["request_id"] = request_id
    if user_id:
        event_dict["user_id"] = user_id

    return event_dict


def configure_logging() -> None:
    """Configure structlog with JSON output and context processors."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            add_context_vars,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance."""
    return structlog.get_logger(name)


def set_request_context(request_id: str, user_id: Optional[str] = None) -> None:
    """Set the request context for logging."""
    request_id_ctx.set(request_id)
    if user_id:
        user_id_ctx.set(user_id)


def clear_request_context() -> None:
    """Clear the request context after request completion."""
    request_id_ctx.set("")
    user_id_ctx.set("")


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


class TimedOperation:
    """Context manager for timing operations and logging duration."""

    def __init__(
        self,
        event: str,
        logger: Optional[structlog.stdlib.BoundLogger] = None,
        **extra_fields: Any,
    ):
        self.event = event
        self.logger = logger or get_logger()
        self.extra_fields = extra_fields
        self.start_time: float = 0
        self.duration_ms: float = 0

    def __enter__(self) -> "TimedOperation":
        self.start_time = time.perf_counter()
        self.logger.info(f"{self.event}_started", **self.extra_fields)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.duration_ms = (time.perf_counter() - self.start_time) * 1000

        if exc_type is not None:
            self.logger.error(
                f"{self.event}_failed",
                duration_ms=round(self.duration_ms, 2),
                error=str(exc_val),
                **self.extra_fields,
            )
        else:
            self.logger.info(
                f"{self.event}_completed",
                duration_ms=round(self.duration_ms, 2),
                **self.extra_fields,
            )


def log_decision(
    logger: structlog.stdlib.BoundLogger,
    user_id: str,
    approved: bool,
    credit_limit_cents: int,
    amount_granted_cents: int,
    risk_score: int,
    score_band: str,
    duration_ms: float,
) -> None:
    """Log a BNPL decision with standard fields."""
    outcome = "approved" if approved else "denied"

    logger.info(
        "decision_completed",
        user_id=user_id,
        outcome=outcome,
        approved=approved,
        credit_limit_cents=credit_limit_cents,
        amount_granted_cents=amount_granted_cents,
        risk_score=risk_score,
        score_band=score_band,
        duration_ms=round(duration_ms, 2),
    )
