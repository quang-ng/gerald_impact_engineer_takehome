"""Client for the Bank API to fetch transaction data."""
import httpx
import structlog
from typing import Optional

from service.config import settings

logger = structlog.get_logger()


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

        logger.info("fetching_transactions",
                   user_id=user_id,
                   url=url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=params)

                if response.status_code == 404:
                    logger.warning("user_not_found", user_id=user_id)
                    raise BankApiError(404, f"User {user_id} not found")

                response.raise_for_status()

                data = response.json()
                transaction_count = len(data.get("transactions", []))
                logger.info("transactions_fetched",
                           user_id=user_id,
                           transaction_count=transaction_count)

                return data

            except httpx.HTTPStatusError as e:
                logger.error("bank_api_error",
                           user_id=user_id,
                           status_code=e.response.status_code,
                           error=str(e))
                raise BankApiError(e.response.status_code, str(e))

            except httpx.RequestError as e:
                logger.error("bank_api_request_error",
                           user_id=user_id,
                           error=str(e))
                raise BankApiError(500, f"Request failed: {e}")
