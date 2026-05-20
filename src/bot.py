import asyncio
import time
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
# 整段 pipeline 的硬上限:vision(30s) + resolver(~30s) + 餘裕 30s
# 防 stuck task 永遠不釋放 in_flight。
PIPELINE_TIMEOUT_SEC = 90.0

WELCOME = (
    "👋 嗨!我是 Pikmin Bloom 菇點座標識別 Bot。\n\n"
    "📸 *用法*:把菇點截圖貼到我所在的頻道,或直接 DM 我\n"
    "📍 *回傳*:GPS 座標 + Google Maps / Apple Maps 連結\n\n"
    "輸入 `/pikmin-help` 看完整說明。"
)

HELP_TEXT = (
    "📖 *使用說明*\n\n"
    "1. 在 Pikmin Bloom 點開菇點詳細頁面\n"
    "2. 截圖(確認 TITLE 文字清楚可見)\n"
    "3. 上傳到我所在的頻道,或私訊我\n\n"
    "✅ *支援*:全球已收錄於 Wikidata / Wikipedia / OSM 的地標\n"
    "✅ *部分支援*:社區小景點(由 AI 推理層提供近似座標,會標記為「大致位置」)\n"
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

    @app.action("open_apple_maps")
    async def _ack_apple(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    @app.action("open_osm")
    async def _ack_osm(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    @app.action("open_search")
    async def _ack_search(ack) -> None:  # type: ignore[no-untyped-def]
        await ack()

    @app.action("open_wiki")
    async def _ack_wiki(ack) -> None:  # type: ignore[no-untyped-def]
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
            channel_type=event.get("channel_type", ""),
        )

    @app.event("file_shared")
    async def _on_file_shared(event, client) -> None:  # type: ignore[no-untyped-def]
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
            channel_type="",
        )

    return app


def _channel_from_shares(file_obj: dict) -> Optional[str]:
    shares = file_obj.get("shares") or {}
    for kind in ("public", "private"):
        bucket = shares.get(kind) or {}
        if bucket:
            return next(iter(bucket.keys()))
    return None


def _is_dm(channel: str, channel_type: str) -> bool:
    """DM channel id 以 'D' 開頭;im 是 channel_type 的另一個訊號。"""
    if channel_type == "im":
        return True
    return bool(channel) and channel.startswith("D")


def _mention_for(user: str, channel: str, channel_type: str) -> Optional[str]:
    """決定是否在最終訊息 @-mention 使用者來推播。
    DM 不需要(Slack 自會通知);channel 中需要(thread 不會自動推播)。"""
    if not user:
        return None
    if _is_dm(channel, channel_type):
        return None
    return user


async def _handle_image(
    *,
    client: AsyncWebClient,
    file_obj: dict,
    channel: str,
    thread_ts: Optional[str],
    user: str,
    channel_type: str = "",
) -> None:
    file_id = file_obj.get("id") or ""
    if not in_flight.acquire(file_id):
        return
    start = time.monotonic()
    try:
        await asyncio.wait_for(
            _pipeline(
                client=client,
                file_obj=file_obj,
                channel=channel,
                thread_ts=thread_ts,
                user=user,
                channel_type=channel_type,
            ),
            timeout=PIPELINE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        log.warning(
            "pipeline timeout",
            file_id=file_id,
            elapsed_s=round(time.monotonic() - start, 1),
        )
        await _safe_post(
            client, channel, thread_ts,
            f"⏱️ 處理超時(> {int(PIPELINE_TIMEOUT_SEC)}s),請稍後重試一次。",
        )
    except Exception:
        log.exception("handle_image failed", user_id=user, file_id=file_id)
        await _safe_post(
            client, channel, thread_ts,
            "⚠️ 處理失敗,請稍後重試。若持續失敗請通知管理員。",
        )
    finally:
        in_flight.release(file_id)


async def _pipeline(
    *,
    client: AsyncWebClient,
    file_obj: dict,
    channel: str,
    thread_ts: Optional[str],
    user: str,
    channel_type: str,
) -> None:
    """純識別管線(會被外層 wait_for 包覆 timeout)。"""
    file_id = file_obj.get("id") or ""

    size = int(file_obj.get("size") or 0)
    if size > MAX_IMAGE_BYTES:
        await _safe_post(
            client, channel, thread_ts,
            f"⚠️ 圖片太大(> {MAX_IMAGE_BYTES // 1024 // 1024}MB),請壓縮後再傳。",
        )
        return

    status_ts = await _safe_post(
        client, channel, thread_ts, "🔍 *步驟 1/3* — 下載圖片中…",
    )
    if not status_ts:
        log.warning("could not post status message", file_id=file_id)
        return

    try:
        image_bytes = await _download_slack_file(file_obj)
    except Exception as e:
        log.warning("download failed", file_id=file_id, error=str(e))
        await _safe_update(
            client, channel, status_ts,
            "⚠️ 下載圖片失敗。請重新上傳一次截圖。",
        )
        return

    cached = image_cache.get(image_bytes)
    if cached:
        place, coords = cached
        mention = _mention_for(user, channel, channel_type)
        await _safe_update(
            client, channel, status_ts,
            format_success(place, coords),
            blocks=success_blocks(place, coords, mention_user=mention),
        )
        log.info(
            "done (cached)",
            user_id=user,
            source=coords.source,
            candidate=place.candidates[0] if place.candidates else "",
        )
        return

    await _safe_update(client, channel, status_ts, "🧠 *步驟 2/3* — AI 識別圖片…")

    try:
        place = await identify_place(image_bytes)
    except VisionError as e:
        log.warning("vision error", user_id=user, error=str(e))
        await _safe_update(client, channel, status_ts, format_vision_failed())
        return

    if not place.candidates:
        await _safe_update(client, channel, status_ts, format_unknown())
        return

    await _safe_update(
        client, channel, status_ts,
        f"🌍 *步驟 3/3* — 查詢座標中…(候選:*{place.candidates[0]}*)",
    )

    coords = await resolve(place)
    mention = _mention_for(user, channel, channel_type)

    if not coords:
        await _safe_update(
            client, channel, status_ts,
            format_no_coords(place),
            blocks=no_coords_blocks(place, mention_user=mention),
        )
        return

    image_cache.put(image_bytes, place, coords)
    await _safe_update(
        client, channel, status_ts,
        format_success(place, coords),
        blocks=success_blocks(place, coords, mention_user=mention),
    )
    log.info(
        "done",
        user_id=user,
        source=coords.source,
        candidate=place.candidates[0],
        is_approximate=coords.is_approximate,
    )


async def _safe_post(
    client: AsyncWebClient,
    channel: str,
    thread_ts: Optional[str],
    text: str,
    blocks: Optional[list[dict]] = None,
) -> Optional[str]:
    """安全發送訊息。回傳 ts 或 None(失敗則 None,呼叫端可繼續)。"""
    kwargs: dict[str, Any] = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    if blocks is not None:
        kwargs["blocks"] = blocks
    try:
        resp = await client.chat_postMessage(**kwargs)
        return resp.get("ts")
    except Exception as e:
        log.warning("chat.postMessage failed", channel=channel, error=str(e))
        return None


async def _safe_update(
    client: AsyncWebClient,
    channel: str,
    ts: str,
    text: str,
    blocks: Optional[list[dict]] = None,
) -> None:
    """更新訊息;若失敗(訊息被刪、channel 變更等)退回 fresh post,
    避免單一錯誤吃掉整個結果。"""
    kwargs: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
    if blocks is not None:
        kwargs["blocks"] = blocks
    try:
        await client.chat_update(**kwargs)
        return
    except Exception as e:
        log.warning("chat.update failed, falling back to post", error=str(e))

    fallback: dict[str, Any] = {"channel": channel, "text": text}
    if blocks is not None:
        fallback["blocks"] = blocks
    try:
        await client.chat_postMessage(**fallback)
    except Exception as e:
        log.warning("chat.postMessage fallback also failed", error=str(e))


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
