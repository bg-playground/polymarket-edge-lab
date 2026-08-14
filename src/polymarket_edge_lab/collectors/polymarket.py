"""Polymarket public trade collector scaffold.

Milestone 1 intentionally leaves response normalization separate from transport.
Before extending this module, confirm the current official endpoint and response
shape against live public API responses and update tests/fixtures accordingly.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class PolymarketPublicTradeCollector:
    """Thin async HTTP client for public trade history."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=0.5, max=8))
    async def fetch_page(
        self,
        *,
        account: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params = {"user": account, "offset": offset, "limit": limit}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"{self._base_url}/trades", params=params)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            raise TypeError(f"Expected list payload, got {type(payload).__name__}")
        return payload
