import asyncio
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from src.config import settings
from src.models import Coords

HTTP_TIMEOUT_SEC = 8.0
USER_AGENT = f"PikminCoordBot/1.0 ({settings.CONTACT_EMAIL})"

_RETRY_STATUS = (429, 500, 502, 503, 504)
_RETRY_MAX_ATTEMPTS = 3
_RETRY_INITIAL_BACKOFF = 0.2


async def http_get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[dict] = None,
    max_attempts: int = _RETRY_MAX_ATTEMPTS,
) -> httpx.Response:
    """GET with exponential-backoff retry on 5xx/429 與連線錯誤。
    用盡重試後若仍有 response(5xx/429)則回傳該 response(交由 caller
    的 raise_for_status 處理);若全是連線錯誤則重新拋出最後的例外。"""
    last_exc: Optional[Exception] = None
    last_response: Optional[httpx.Response] = None
    for attempt in range(max_attempts):
        try:
            r = await client.get(url, params=params)
            last_response = r
            if r.status_code in _RETRY_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"transient {r.status_code}", request=r.request, response=r
                )
            else:
                return r
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_exc = e
        if attempt < max_attempts - 1:
            await asyncio.sleep(_RETRY_INITIAL_BACKOFF * (2 ** attempt))
    if last_response is not None:
        return last_response
    if last_exc is not None:
        raise last_exc
    raise httpx.HTTPError("retry exhausted without response")


class GeocoderProvider(ABC):
    name: str

    @abstractmethod
    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        """單次查詢。找不到回 None,網路錯誤拋 ProviderError。"""


class ProviderError(Exception):
    pass
