from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.providers import base


def _resp(status: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.request = MagicMock()
    return r


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(base, "_RETRY_INITIAL_BACKOFF", 0.0)


@pytest.mark.asyncio
async def test_http_get_with_retry_succeeds_first_try():
    client = MagicMock()
    r200 = _resp(200)
    client.get = AsyncMock(return_value=r200)
    out = await base.http_get_with_retry(client, "http://x")
    assert out is r200
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_get_with_retry_retries_on_503_then_succeeds():
    client = MagicMock()
    client.get = AsyncMock(side_effect=[_resp(503), _resp(200)])
    out = await base.http_get_with_retry(client, "http://x", max_attempts=3)
    assert out.status_code == 200
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_http_get_with_retry_retries_on_429_then_succeeds():
    client = MagicMock()
    client.get = AsyncMock(side_effect=[_resp(429), _resp(200)])
    out = await base.http_get_with_retry(client, "http://x", max_attempts=3)
    assert out.status_code == 200


@pytest.mark.asyncio
async def test_http_get_with_retry_returns_last_5xx_after_exhaustion():
    client = MagicMock()
    last = _resp(503)
    client.get = AsyncMock(side_effect=[_resp(503), _resp(503), last])
    out = await base.http_get_with_retry(client, "http://x", max_attempts=3)
    assert out is last  # caller 會 raise_for_status 把它變成錯誤


@pytest.mark.asyncio
async def test_http_get_with_retry_retries_on_connect_error():
    client = MagicMock()
    r200 = _resp(200)
    client.get = AsyncMock(side_effect=[httpx.ConnectError("boom"), r200])
    out = await base.http_get_with_retry(client, "http://x", max_attempts=2)
    assert out is r200


@pytest.mark.asyncio
async def test_http_get_with_retry_reraises_when_all_connect_errors():
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(httpx.ConnectError):
        await base.http_get_with_retry(client, "http://x", max_attempts=2)


@pytest.mark.asyncio
async def test_http_get_with_retry_does_not_retry_on_400():
    client = MagicMock()
    r400 = _resp(400)
    client.get = AsyncMock(return_value=r400)
    out = await base.http_get_with_retry(client, "http://x", max_attempts=3)
    assert out is r400
    client.get.assert_awaited_once()
