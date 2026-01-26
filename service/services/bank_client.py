"""Client for the Bank API to fetch transaction data."""
import time
from typing import Optional

import httpx

from service.config import settings
from service.logging import get_logger
from service import metrics

logger = get_logger(__name__)


class BankApiError(Exception):
    """Raised when the bank API returns an error."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Bank API error {status_code}: {detail}")


class BankClient:
    """Client for fetching user transaction data from the bank API."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize the bank client.

        Args:
            base_url: Base URL of the bank API. Defaults to settings.bank_api_base.
        """
        self.base_url = base_url or settings.bank_api_base

    async def get_transactions(self, user_id: str) -> dict:
        """
        Fetch transaction data for a user.

        Args:
            user_id: The user identifier

        Returns:
            Dictionary with user_id and transactions list

        Raises:
            BankApiError: If the API returns an error
        """
        url = f"{self.base_url}/bank/transactions"
        params = {"user_id": user_id}

        start_time = time.perf_counter()

        logger.info("bank_api_request_started", user_id=user_id, url=url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=params)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if response.status_code == 404:
                    duration_seconds = duration_ms / 1000
                    logger.warning(
                        "bank_api_user_not_found",
                        user_id=user_id,
                        duration_ms=round(duration_ms, 2),
                        outcome="not_found",
                    )
                    # Record not found as a failure
                    metrics.record_bank_fetch(success=False, latency_seconds=duration_seconds, error_type="not_found")
                    raise BankApiError(404, f"User {user_id} not found")

                response.raise_for_status()

                data = response.json()
                transaction_count = len(data.get("transactions", []))
                duration_seconds = duration_ms / 1000

                logger.info(
                    "bank_api_request_completed",
                    user_id=user_id,
                    transaction_count=transaction_count,
                    duration_ms=round(duration_ms, 2),
                    outcome="success",
                )

                # Record successful bank fetch metrics
                metrics.record_bank_fetch(success=True, latency_seconds=duration_seconds)

                return data

            except httpx.HTTPStatusError as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                duration_seconds = duration_ms / 1000

                logger.error(
                    "bank_api_http_error",
                    user_id=user_id,
                    status_code=e.response.status_code,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    outcome="error",
                )

                # Record failed bank fetch metrics
                metrics.record_bank_fetch(success=False, latency_seconds=duration_seconds, error_type="http_error")

                raise BankApiError(e.response.status_code, str(e))

            except httpx.RequestError as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                duration_seconds = duration_ms / 1000

                logger.error(
                    "bank_api_request_error",
                    user_id=user_id,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    outcome="error",
                )

                # Record failed bank fetch metrics (connection/timeout error)
                error_type = "timeout" if "timeout" in str(e).lower() else "connection_error"
                metrics.record_bank_fetch(success=False, latency_seconds=duration_seconds, error_type=error_type)

                raise BankApiError(500, f"Request failed: {e}")
