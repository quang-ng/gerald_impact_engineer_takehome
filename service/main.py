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
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from service.api import router
from service.config import settings
from service.database import engine, Base
from service.services.bank_client import BankApiError

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

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
    logger.info("starting_service",
               service_name=settings.service_name,
               bank_api_base=settings.bank_api_base)

    # Create tables if they don't exist (in production, use migrations)
    Base.metadata.create_all(bind=engine)

    yield

    logger.info("shutting_down_service")


app = FastAPI(
    title="Gerald BNPL Decision Service",
    description="Buy Now, Pay Later decision engine for Gerald's $0-fee model",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to track request metrics."""
    import time

    method = request.method
    path = request.url.path

    # Skip metrics endpoint itself
    if path == "/metrics":
        return await call_next(request)

    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time

    REQUEST_COUNT.labels(
        method=method,
        endpoint=path,
        status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        method=method,
        endpoint=path
    ).observe(duration)

    return response


@app.exception_handler(BankApiError)
async def bank_api_error_handler(request: Request, exc: BankApiError):
    """Handle bank API errors."""
    logger.error("bank_api_error",
                status_code=exc.status_code,
                detail=exc.detail)

    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.detail}
        )
    return JSONResponse(
        status_code=502,
        content={"detail": f"Bank API error: {exc.detail}"}
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
