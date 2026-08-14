"""Interfaces for public-data collectors."""

from __future__ import annotations

from typing import Any, Protocol


class TradeCollector(Protocol):
    async def fetch_page(self, *, account: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """Fetch one page of raw public trade records."""
        ...
