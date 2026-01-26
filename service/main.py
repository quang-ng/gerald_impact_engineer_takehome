"""
Gerald BNPL Decision Service

A FastAPI-based service for making Buy Now, Pay Later credit decisions.
This service evaluates user creditworthiness based on bank transaction data
and determines appropriate credit limits.

Gerald's $0-Fee Model:
----------------------
Unlike traditional BNPL providers that rely on late fees and penalties,
Gerald operates on a $0-fee model. This means:

1. Revenue comes from merchant fees and subscriptions, not user penalties
2. Every default directly impacts the bottom line
3. Risk assessment must be more conservative than fee-based models
4. User experience and trust are paramount

This service implements risk scoring that balances:
- Approving users who will benefit from and repay advances
- Denying users likely to default (protecting both Gerald and the user)
- Being inclusive of non-traditional income patterns (gig workers)
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from service.api import router
from service.config import settings
from service.database import engine, Base
from service.services.bank_client import BankApiError
from service.logging import (
    configure_logging,
    get_logger,
    set_request_context,
    clear_request_context,
    generate_request_id,
)

# Configure structured logging
configure_logging()
logger = get_logger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

DECISION_COUNT = Counter(
    "bnpl_decisions_total",
    "Total BNPL decisions made",
    ["approved", "score_band"]
)

DECISION_AMOUNT = Histogram(
    "bnpl_decision_amount_cents",
    "BNPL decision amounts requested",
    buckets=[10000, 20000, 30000, 40000, 50000, 60000, 100000]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info(
        "service_starting",
        service_name=settings.service_name,
        bank_api_base=settings.bank_api_base,
    )

    # Create tables if they don't exist (in production, use migrations)
    Base.metadata.create_all(bind=engine)

    logger.info("service_started", service_name=settings.service_name)

    yield

    logger.info("service_stopping", service_name=settings.service_name)


app = FastAPI(
    title="Gerald BNPL Decision Service",
    description="Buy Now, Pay Later decision engine for Gerald's $0-fee model",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Middleware for request tracing, logging, and metrics.

    Sets up request context with:
    - request_id: Unique identifier for tracing
    - Timing for duration_ms calculation
    - Prometheus metrics collection
    """
    method = request.method
    path = request.url.path

    # Skip logging/metrics for health and metrics endpoints
    if path in ("/health", "/metrics"):
        return await call_next(request)

    # Generate and set request ID
    request_id = request.headers.get("X-Request-ID") or generate_request_id()
    set_request_context(request_id)

    # Store request_id in request state for access in route handlers
    request.state.request_id = request_id

    start_time = time.perf_counter()

    # Log request received
    logger.info("request_received", method=method, path=path)

    try:
        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Log request completed
        logger.info(
            "request_completed",
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        # Record Prometheus metrics
        REQUEST_COUNT.labels(
            method=method,
            endpoint=path,
            status=response.status_code
        ).inc()

        REQUEST_LATENCY.labels(
            method=method,
            endpoint=path
        ).observe(duration_ms / 1000)  # Convert to seconds for histogram

        # Add request_id to response headers for tracing
        response.headers["X-Request-ID"] = request_id

        return response

    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.error(
            "request_failed",
            method=method,
            path=path,
            duration_ms=round(duration_ms, 2),
            error=str(e),
        )

        REQUEST_COUNT.labels(
            method=method,
            endpoint=path,
            status=500
        ).inc()

        raise

    finally:
        clear_request_context()


@app.exception_handler(BankApiError)
async def bank_api_error_handler(request: Request, exc: BankApiError):
    """Handle bank API errors."""
    request_id = getattr(request.state, "request_id", "unknown")

    logger.error(
        "bank_api_error",
        status_code=exc.status_code,
        detail=exc.detail,
    )

    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.detail},
            headers={"X-Request-ID": request_id},
        )
    return JSONResponse(
        status_code=502,
        content={"detail": f"Bank API error: {exc.detail}"},
        headers={"X-Request-ID": request_id},
    )


# Include API routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "ok", "service": settings.service_name}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
