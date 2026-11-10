"""Small retry helper for outbound HTTP calls (Zendesk, Slack)."""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    **kwargs,
) -> httpx.Response:
    """Retry on network errors, 429 and 5xx with exponential backoff (honours Retry-After)."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code not in RETRY_STATUSES or attempt == attempts:
                return resp
            delay = float(resp.headers.get("Retry-After", base_delay * 2 ** (attempt - 1)))
            log.warning("%s %s -> %s, retrying in %.1fs", method, url, resp.status_code, delay)
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            log.warning("%s %s failed (%s), retrying in %.1fs", method, url, exc, delay)
        await asyncio.sleep(min(delay, 10))
    raise RuntimeError("unreachable") from last_exc
