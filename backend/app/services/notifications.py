"""Notification delivery — optional outbound webhooks.

Supports multiple named webhook endpoints for events:
- job.completed
- job.failed
- job.needs_attention
- import.completed

Required webhooks can block final Job completion.
Optional webhook failures do not block cleanup.
Delivery retries and result history are persisted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationService:
    """Manages webhook notification delivery with retry."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_notification(
        self,
        target_url: str,
        event_type: str,
        payload: dict[str, Any],
        required: bool = False,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Send a webhook notification with retry.

        Returns {'success': bool, 'response_code': int | None, 'error': str}
        """
        body = {
            "event": event_type,
            "timestamp": _utcnow().isoformat(),
            "data": payload,
        }

        for attempt in range(1, max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.post(target_url, json=body)

                if response.status_code < 400:
                    return {"success": True, "response_code": response.status_code, "error": ""}

                logger.warning(
                    "Notification to %s returned %d (attempt %d/%d)",
                    target_url,
                    response.status_code,
                    attempt,
                    max_retries,
                )

                if attempt < max_retries:
                    # Exponential backoff
                    await asyncio.sleep(2**attempt + 1)

            except Exception as e:
                logger.warning(
                    "Notification to %s failed (attempt %d/%d): %s",
                    target_url,
                    attempt,
                    max_retries,
                    e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt + 1)

        return {
            "success": False,
            "response_code": None,
            "error": f"Failed after {max_retries} attempts",
        }
