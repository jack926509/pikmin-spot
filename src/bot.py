import asyncio
from typing import Any, Optional

import httpx
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from src.cache import image_cache, in_flight
from src.config import settings
from src.formatter import (
    format_no_coords,
    format_success,
    format_unknown,
    format_vision_failed,
)
from src.logger import get_logger
from src.resolver import resolve
from src.slack_blocks import no_coords_blocks, success_blocks, text_blocks
from src.vision import VisionError, identify_place

log = get_logger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SEC = 30
DOWNLOAD_MAX_ATTEMPTS = 3

WELCOME = (
    "👋 嗨!我是 Pikmin Bloom 菇點座標識別 Bot。\n\n"
    "📸 *用法*:把菇點截圖貼到我所在的頻道,或直接 DM 我\n"
    "📍 *回傳*:GPS 座標 + Google Maps 連結\n\n"
    "輸入 `/pikmin-help` 看完整說明。"
)

HELP_TEXT = (
    "📖 *使用說明*\n\n"
    "1. 在 Pikmin Bloom 點開菇點詳細頁面\n"
    "2. 截圖(確認 TITLE 文字清楚可見)\n"
    "3. 上傳到我所在的頻道,或私訊我\n\n"
    "✅ *支援*:全球已收錄於 Wikidata / Wikipedia / OSM 的地標\n"
    "❌ *不支援*:只有經緯度的野菇點(無命名)\n\n"
    "資料來源:Wikidata · Wikipedia · OpenStreetMap (Nominatim/Photon)\n"
    "識別模型:OpenAI gpt-4o-mini"
)


def create_app() -> AsyncApp:
    app = AsyncApp(token=settings.SLACK_BOT_TOKEN)

    @app.command("/pikmin-start")
    async def _start(ack, respond) -> None:  # type: ignore[no-untyped-def]
        await ack()
        await respond(text=WELCOME, blocks=text_blocks(WELCOME))

    @app.command("/pikmin-help")
    async def _help(ack, respond) -> None:  # type: ignore[no-untyped-def]
        await ack()
        await respond(text=HELP_TEXT, blocks=text_blocks(HELP_TEXT))

    # URL buttons open the link client-side, but Slack still posts a
    # block_actions event and expects ack within 3s — without these
    # handlers Bolt logs "unhandled request" 404 on every click.
    @app.action("open_gmaps")
    async def _ack_gmaps(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    @app.action("open_search")
    async def _ack_search(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    @app.event("app_mention")
    async def _on_mention(event, client) -> None:  # type: ignore[no-untyped-def]
        await client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event.get("thread_ts") or event.get("ts"),
            text=HELP_TEXT,
            blocks=text_blocks(HELP_TEXT),
        )

    @app.event("message")
    async def _on_message(event, client) -> None:  # type: ignore[no-untyped-def]
        # 只處理新訊息與 file_share;忽略編輯 / 刪除 / bot 自己的訊息。
        subtype = event.get("subtype")
        if subtype not in (None, "file_share"):
            return
        if event.get("bot_id"):
            return
        images = [
            f for f in (event.get("files") or [])
            if (f.get("mimetype") or "").startswith("image/")
        ]
        if not images:
            # 在 DM 給文字而非圖片時,給點提示。在頻道中靜默以免吵。
            if event.get("channel_type") == "im" and not subtype:
                await client.chat_postMessage(
                    channel=event["channel"],
                    text="請傳一張菇點 *截圖*。輸入 `/pikmin-help` 看說明。",
                )
            return
        await _handle_image(
            client=client,
            file_obj=images[0],
            channel=event["channel"],
            thread_ts=event.get("thread_ts") or event.get("ts"),
            user=event.get("user", ""),
        )

    @app.event("file_shared")
    async def _on_file_shared(event, client) -> None:  # type: ignore[no-untyped-def]
        # 備援:某些情況下檔案僅透過 file_shared 投遞。
        file_id = event.get("file_id") or event.get("file", {}).get("id")
        if not file_id:
            return
        try:
            info = await client.files_info(file=file_id)
        except Exception as e:
            log.warning("files_info failed", file_id=file_id, error=str(e))
            return
        file_obj = info.get("file") or {}
        if not (file_obj.get("mimetype") or "").startswith("image/"):
            return
        channel = event.get("channel_id") or _channel_from_shares(file_obj)
        if not channel:
            return
        await _handle_image(
            client=client,
            file_obj=file_obj,
            channel=channel,
            thread_ts=None,
            user=event.get("user_id", ""),
        )

    return app


def _channel_from_shares(file_obj: dict) -> Optional[str]:
    shares = file_obj.get("shares") or {}
    for kind in ("public", "private"):
        bucket = shares.get(kind) or {}
        if bucket:
            return next(iter(bucket.keys()))
    return None


async def _handle_image(
    *,
    client: AsyncWebClient,
    file_obj: dict,
    channel: str,
    thread_ts: Optional[str],
    user: str,
) -> None:
    file_id = file_obj.get("id") or ""
    if not in_flight.acquire(file_id):
        return

    try:
        size = int(file_obj.get("size") or 0)
        if size > MAX_IMAGE_BYTES:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"⚠️ 圖片太大(> {MAX_IMAGE_BYTES // 1024 // 1024}MB),請壓縮後再傳。",
            )
            return

        status = await client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, text="🔍 識別中…"
        )
        status_ts = status["ts"]

        try:
            image_bytes = await _download_slack_file(file_obj)
        except Exception as e:
            log.warning("download failed", file_id=file_id, error=str(e))
            await _update(client, channel, status_ts, "⚠️ 下載圖片失敗,請稍後重試")
            return

        cached = image_cache.get(image_bytes)
        if cached:
            place, coords = cached
            await _update(
                client, channel, status_ts,
                format_success(place, coords),
                blocks=success_blocks(place, coords),
            )
            log.info(
                "done (cached)",
                user_id=user,
                source=coords.source,
                candidate=place.candidates[0] if place.candidates else "",
            )
            return

        try:
            place = await identify_place(image_bytes)
        except VisionError as e:
            log.warning("vision error", user_id=user, error=str(e))
            await _update(client, channel, status_ts, format_vision_failed())
            return

        if not place.candidates:
            await _update(client, channel, status_ts, format_unknown())
            return

        await _update(
            client, channel, status_ts,
            f"🌍 解析座標…(候選:*{place.candidates[0]}*)",
        )

        coords = await resolve(place)
        if not coords:
            await _update(
                client, channel, status_ts,
                format_no_coords(place),
                blocks=no_coords_blocks(place),
            )
            return

        image_cache.put(image_bytes, place, coords)
        await _update(
            client, channel, status_ts,
            format_success(place, coords),
            blocks=success_blocks(place, coords),
        )
        log.info(
            "done",
            user_id=user,
            source=coords.source,
            candidate=place.candidates[0],
        )
    except Exception:
        log.exception("handle_image failed", user_id=user, file_id=file_id)
        try:
            await client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text="⚠️ 處理失敗,請稍後重試",
            )
        except Exception:
            pass
    finally:
        in_flight.release(file_id)


async def _update(
    client: AsyncWebClient,
    channel: str,
    ts: str,
    text: str,
    blocks: Optional[list[dict]] = None,
) -> None:
    kwargs: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
    if blocks is not None:
        kwargs["blocks"] = blocks
    await client.chat_update(**kwargs)


async def _download_slack_file(file_obj: dict) -> bytes:
    url = file_obj.get("url_private_download") or file_obj.get("url_private")
    if not url:
        raise RuntimeError("Slack file missing url_private")
    headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
    last_exc: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SEC) as http:
        for attempt in range(DOWNLOAD_MAX_ATTEMPTS):
            try:
                r = await http.get(url, headers=headers)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_exc = httpx.HTTPStatusError(
                        f"transient {r.status_code}", request=r.request, response=r
                    )
                else:
                    r.raise_for_status()
                    return r.content
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
            if attempt < DOWNLOAD_MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("Slack file download failed")
