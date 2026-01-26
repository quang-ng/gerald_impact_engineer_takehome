"""Configuration settings for the BNPL Decision Service."""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5433/gerald"

    # External services
    bank_api_base: str = "http://localhost:8001"
    ledger_webhook_url: str = "http://localhost:8002/mock-ledger"

    # Service identification
    service_name: str = "gerald-gateway"

    # Risk scoring configuration
    # These thresholds are calibrated for Gerald's $0-fee model
    # We need to be conservative to maintain profitability without fees
    risk_score_min_approval: float = 0.2  # Minimum score for any approval

    # Transaction analysis window (days)
    analysis_window_days: int = 90

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
