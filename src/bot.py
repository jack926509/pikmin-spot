from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from src.formatter import (
    format_no_coords,
    format_success,
    format_unknown,
    format_vision_failed,
    google_maps_keyboard,
    google_search_keyboard,
)
from src.logger import get_logger
from src.resolver import resolve
from src.vision import VisionError, identify_place

log = get_logger(__name__)

WELCOME = (
    "👋 嗨!我是 Pikmin Bloom 菇點座標識別 Bot。\n\n"
    "📸 *用法*:直接傳一張菇點截圖\n"
    "📍 *回傳*:GPS 座標 + Google Maps + 互動式地圖\n\n"
    "輸入 /help 看完整說明。"
)

HELP_TEXT = (
    "📖 *使用說明*\n\n"
    "1. 在 Pikmin Bloom 點開菇點詳細頁面\n"
    "2. 截圖(確認標題文字清楚可見)\n"
    "3. 傳給我這隻 Bot,等 5~10 秒\n\n"
    "✅ *支援*:全球已收錄於 Wikidata / Wikipedia / OSM 的地標\n"
    "❌ *不支援*:只有經緯度的野菇點(無命名)\n\n"
    "資料來源:Wikidata · Wikipedia · OpenStreetMap (Nominatim/Photon)\n"
    "識別模型:OpenAI gpt-4o-mini"
)


def _non_photo_hint(update: Update) -> str:
    msg = update.message
    if msg is None:
        return "請傳一張菇點 *截圖*。"
    if msg.document:
        return (
            "📎 收到檔案,但請改用 *圖片* 方式傳送:\n"
            "傳送時別勾「以檔案傳送」,讓 Telegram 自動壓縮即可。"
        )
    if msg.video or msg.video_note:
        return "🎥 我只看靜態截圖,不處理影片。"
    if msg.sticker or msg.animation:
        return "😄 貼圖很可愛,但我認不出地標 🙏"
    if msg.voice or msg.audio:
        return "🎵 聲音檔不算菇點截圖喔。"
    return "請傳一張菇點 *截圖*。輸入 /help 看說明。"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            _non_photo_hint(update), parse_mode="Markdown"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    status = await update.message.reply_text("🔍 識別中…")

    try:
        photos = update.message.photo
        if not photos:
            await status.edit_text(_non_photo_hint(update), parse_mode="Markdown")
            return
        photo = photos[-1]
        file = await photo.get_file()
        bio = BytesIO()
        await file.download_to_memory(bio)
        image_bytes = bio.getvalue()

        try:
            place = await identify_place(image_bytes)
        except VisionError as e:
            log.warning("vision error", user_id=user_id, error=str(e))
            await status.edit_text(format_vision_failed(), parse_mode="Markdown")
            return

        if not place.candidates:
            await status.edit_text(format_unknown(), parse_mode="Markdown")
            return

        await status.edit_text(
            f"🌍 解析座標…(候選:*{place.candidates[0]}*)",
            parse_mode="Markdown",
        )

        coords = await resolve(place)
        if not coords:
            name = place.candidates[0]
            await status.edit_text(
                format_no_coords(place),
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=google_search_keyboard(name, place.country or ""),
            )
            return

        await status.edit_text(
            format_success(place, coords),
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=google_maps_keyboard(coords.lat, coords.lng),
        )
        await context.bot.send_location(
            chat_id=chat_id,
            latitude=coords.lat,
            longitude=coords.lng,
        )
        log.info(
            "done",
            user_id=user_id,
            source=coords.source,
            candidate=place.candidates[0],
        )
    except Exception:
        log.exception("handle_photo failed", user_id=user_id)
        try:
            await status.edit_text("⚠️ 處理失敗,請稍後重試")
        except Exception:
            pass
