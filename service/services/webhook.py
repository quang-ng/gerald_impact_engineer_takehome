"""Webhook service for notifying external systems of decisions."""
import uuid
from datetime import datetime
from typing import Optional

import httpx
import structlog
from sqlalchemy.orm import Session

from service.config import settings
from service.models import OutboundWebhook

logger = structlog.get_logger()


class WebhookService:
    """
    Service for sending webhooks to external systems.

    Manages webhook delivery with:
    - Persistence of webhook attempts
    - Retry tracking
    - Async delivery
    """

    MAX_ATTEMPTS = 3

    def __init__(self, db: Session, target_url: Optional[str] = None):
        """
        Initialize the webhook service.

        Args:
            db: SQLAlchemy database session
            target_url: Webhook target URL (defaults to settings.ledger_webhook_url)
        """
        self.db = db
        self.target_url = target_url or settings.ledger_webhook_url

    async def send_decision_webhook(self, decision_data: dict) -> bool:
        """
        Send a decision notification webhook.

        Args:
            decision_data: Decision data to send

        Returns:
            True if webhook was delivered successfully
        """
        webhook = OutboundWebhook(
            id=uuid.uuid4(),
            event_type="decision.created",
            payload=decision_data,
            target_url=self.target_url,
            status="pending",
        )
        self.db.add(webhook)
        self.db.commit()

        return await self._deliver_webhook(webhook)

    async def _deliver_webhook(self, webhook: OutboundWebhook) -> bool:
        """
        Attempt to deliver a webhook.

        Args:
            webhook: The webhook record to deliver

        Returns:
            True if delivery succeeded
        """
        logger.info("delivering_webhook",
                   webhook_id=str(webhook.id),
                   event_type=webhook.event_type,
                   target_url=webhook.target_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    webhook.target_url,
                    json=webhook.payload,
                    headers={"Content-Type": "application/json"},
                )

                webhook.attempts += 1
                webhook.last_attempt_at = datetime.utcnow()

                if response.status_code < 400:
                    webhook.status = "delivered"
                    self.db.commit()
                    logger.info("webhook_delivered",
                               webhook_id=str(webhook.id),
                               status_code=response.status_code)
                    return True
                else:
                    webhook.status = "failed" if webhook.attempts >= self.MAX_ATTEMPTS else "pending"
                    self.db.commit()
                    logger.warning("webhook_delivery_failed",
                                  webhook_id=str(webhook.id),
                                  status_code=response.status_code,
                                  attempts=webhook.attempts)
                    return False

            except httpx.RequestError as e:
                webhook.attempts += 1
                webhook.last_attempt_at = datetime.utcnow()
                webhook.status = "failed" if webhook.attempts >= self.MAX_ATTEMPTS else "pending"
                self.db.commit()

                logger.error("webhook_request_error",
                            webhook_id=str(webhook.id),
                            error=str(e),
                            attempts=webhook.attempts)
                return False

    async def retry_pending_webhooks(self) -> int:
        """
        Retry all pending webhooks that haven't exceeded max attempts.

        Returns:
            Number of webhooks successfully delivered
        """
        pending = (
            self.db.query(OutboundWebhook)
            .filter(OutboundWebhook.status == "pending")
            .filter(OutboundWebhook.attempts < self.MAX_ATTEMPTS)
            .all()
        )

        delivered = 0
        for webhook in pending:
            if await self._deliver_webhook(webhook):
                delivered += 1

        logger.info("pending_webhooks_retried",
                   total=len(pending),
                   delivered=delivered)

        return delivered
