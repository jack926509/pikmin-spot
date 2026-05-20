"""bot.py 行為測試:DM/channel mention 判斷、pipeline timeout、safe_update fallback。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import bot
from src.cache import in_flight


def test_is_dm_detects_channel_prefix():
    assert bot._is_dm("D123ABC", "") is True
    assert bot._is_dm("D123ABC", "im") is True
    # channel_type 為 im 也算
    assert bot._is_dm("C456", "im") is True
    # 公開 channel
    assert bot._is_dm("C456", "channel") is False
    assert bot._is_dm("", "") is False


def test_mention_for_skips_dm_includes_channel():
    # DM 不 mention(Slack 已自帶推播)
    assert bot._mention_for("U1", "D123", "im") is None
    # public channel 中 mention(thread 不會自動通知)
    assert bot._mention_for("U1", "C456", "channel") == "U1"
    # 沒 user_id 也不 mention
    assert bot._mention_for("", "C456", "channel") is None


@pytest.mark.asyncio
async def test_handle_image_releases_in_flight_after_timeout():
    """若 pipeline hang 超過 PIPELINE_TIMEOUT_SEC,in_flight 仍應被釋放。"""
    # 確保乾淨狀態
    in_flight.release("file_timeout_test")

    fake_client = MagicMock()
    fake_client.chat_postMessage = AsyncMock(return_value={"ts": "1.0"})

    async def stuck_pipeline(**kw):
        await asyncio.sleep(10)  # 永不結束(會被 timeout 切掉)

    with patch.object(bot, "_pipeline", side_effect=stuck_pipeline):
        with patch.object(bot, "PIPELINE_TIMEOUT_SEC", 0.05):
            await bot._handle_image(
                client=fake_client,
                file_obj={"id": "file_timeout_test", "size": 100},
                channel="C1",
                thread_ts=None,
                user="U1",
            )
    # timeout 後 in_flight 應被釋放,可重新 acquire
    assert in_flight.acquire("file_timeout_test") is True
    in_flight.release("file_timeout_test")


@pytest.mark.asyncio
async def test_handle_image_skips_when_already_in_flight():
    """同 file_id 重覆觸發應直接跳過。"""
    in_flight.release("dup_test")
    in_flight.acquire("dup_test")
    try:
        fake_client = MagicMock()
        fake_pipeline = AsyncMock()
        with patch.object(bot, "_pipeline", fake_pipeline):
            await bot._handle_image(
                client=fake_client,
                file_obj={"id": "dup_test", "size": 100},
                channel="C1",
                thread_ts=None,
                user="U1",
            )
        fake_pipeline.assert_not_called()
    finally:
        in_flight.release("dup_test")


@pytest.mark.asyncio
async def test_safe_update_falls_back_to_post_on_failure():
    fake = MagicMock()
    fake.chat_update = AsyncMock(side_effect=RuntimeError("message not found"))
    fake.chat_postMessage = AsyncMock(return_value={"ts": "2.0"})
    await bot._safe_update(fake, "C1", "1.0", "hello")
    fake.chat_update.assert_awaited_once()
    fake.chat_postMessage.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_update_does_not_post_when_update_succeeds():
    fake = MagicMock()
    fake.chat_update = AsyncMock(return_value={"ok": True})
    fake.chat_postMessage = AsyncMock()
    await bot._safe_update(fake, "C1", "1.0", "hello")
    fake.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_safe_post_returns_ts_on_success():
    fake = MagicMock()
    fake.chat_postMessage = AsyncMock(return_value={"ts": "9.9"})
    ts = await bot._safe_post(fake, "C1", None, "hi")
    assert ts == "9.9"


@pytest.mark.asyncio
async def test_safe_post_returns_none_on_failure():
    fake = MagicMock()
    fake.chat_postMessage = AsyncMock(side_effect=RuntimeError("network down"))
    ts = await bot._safe_post(fake, "C1", None, "hi")
    assert ts is None
