"""Polymarket public trade collector.

Fetches paginated trade history from the official public Data API:
  GET https://data-api.polymarket.com/trades
  Parameters: user, offset, limit[, startTs, endTs]

Separation of concerns:
  - This module handles HTTP transport only.
  - Normalization is in normalization/trades.py.
  - Raw storage is in storage/raw.py.
  - The CLI orchestrator is in scripts/collect_historical_trades.py.

API notes (verified 2026-08-14 from official docs; live response shape not
confirmed due to network restriction — see tests/fixtures/README.md):
  - Response is a JSON array.
  - Pagination uses offset/limit; empty array signals end.
  - Documented offset upper bound: 10 000 (see README Known Limitations).
  - ``startTs`` / ``endTs`` epoch-second parameters narrow the query window;
    use these to bypass the offset ceiling for deep history.
  - Does not require authentication for public wallet addresses.
  - ``price`` and ``size`` are JSON numbers; parsed with parse_float=Decimal.
TODO: Confirm parameter names (startTs/endTs vs start/end/startTime/endTime)
      against a live response before production use.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"

# Documented API offset ceiling.  The API may silently return empty results
# past this bound.  Use time-window parameters (startTs/endTs) for deep history.
OFFSET_CEILING = 10_000


class PolymarketPublicTradeCollector:
    """Thin HTTP client for public trade history pages.

    Parameters
    ----------
    base_url:
        Base URL of the Data API (default ``DATA_API_BASE``).
    timeout_seconds:
        Per-request timeout.
    client:
        Optional pre-built ``httpx.AsyncClient`` (used in tests via
        ``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str = DATA_API_BASE,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=0.5, max=8))
    async def fetch_page(
        self,
        *,
        account: str,
        offset: int = 0,
        limit: int = 100,
        window_start: int | None = None,
        window_end: int | None = None,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Fetch one page of trade history.

        Parameters
        ----------
        account:
            Proxy wallet address to query.
        offset:
            Page offset within the current window.
        limit:
            Maximum number of records per page.
        window_start:
            Optional lower time bound as Unix epoch **seconds** (``startTs``
            parameter).  When provided together with ``window_end``, results
            are restricted to ``[window_start, window_end)``, allowing full
            history retrieval across multiple non-overlapping windows.
        window_end:
            Optional upper time bound as Unix epoch **seconds** (``endTs``
            parameter).

        Returns
        -------
        (raw_bytes, records):
            ``raw_bytes`` is the exact HTTP response body for immutable storage.
            ``records`` is the parsed JSON list, with numeric fields decoded as
            ``Decimal`` (via ``json.loads(..., parse_float=Decimal)``) to avoid
            float precision loss on ``price`` and ``size``.

        Raises
        ------
        TypeError:
            If the response top-level JSON is not a list.
        httpx.HTTPStatusError:
            On non-2xx responses.
        """
        url = f"{self._base_url}/trades"
        params: dict[str, str | int] = {"user": account, "offset": offset, "limit": limit}
        if window_start is not None:
            params["startTs"] = window_start
        if window_end is not None:
            params["endTs"] = window_end
        if self._client is not None:
            response = await self._client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        raw_bytes = response.content
        # Parse with parse_float=Decimal so JSON numbers for price/size arrive
        # as Decimal objects rather than floats, preserving precision.
        payload = json.loads(raw_bytes, parse_float=Decimal)
        if not isinstance(payload, list):
            raise TypeError(f"Expected list payload from {url}, got {type(payload).__name__}")
        return raw_bytes, payload

    def endpoint_url(
        self,
        *,
        account: str,
        offset: int,
        limit: int,
        window_start: int | None = None,
        window_end: int | None = None,
    ) -> str:
        base = f"{self._base_url}/trades?user={account}&offset={offset}&limit={limit}"
        if window_start is not None:
            base += f"&startTs={window_start}"
        if window_end is not None:
            base += f"&endTs={window_end}"
        return base
