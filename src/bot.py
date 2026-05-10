from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from src.formatter import format_no_coords, format_success, format_unknown
from src.logger import get_logger
from src.resolver import resolve
from src.vision import VisionError, identify_place

log = get_logger(__name__)

WELCOME = (
    "👋 嗨!我是 Pikmin Bloom 菇點座標識別 Bot。\n\n"
    "把菇點截圖傳給我,我會回傳:\n"
    "・🎯 GPS 座標\n"
    "・🗺️ Google Maps 連結\n"
    "・📍 互動式地圖位置\n\n"
    "直接傳圖即可開始!"
)

NON_PHOTO_HINT = "請傳送 Pikmin Bloom 菇點截圖(圖片格式)。輸入 /help 看說明。"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(WELCOME)


async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(NON_PHOTO_HINT)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    status = await update.message.reply_text("🔍 識別中…")

    try:
        photos = update.message.photo
        if not photos:
            await status.edit_text(NON_PHOTO_HINT)
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
            await status.edit_text("⚠️ 識別失敗,請稍後再試或換一張圖。")
            return

        if not place.candidates:
            await status.edit_text(format_unknown())
            return

        await status.edit_text(
            f"🔎 識別到「{place.candidates[0]}」,查詢座標中…"
        )

        coords = await resolve(place)
        if not coords:
            await status.edit_text(
                format_no_coords(place),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            return

        await status.edit_text(
            format_success(place, coords),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await context.bot.send_location(
            chat_id=chat_id,
            latitude=coords.lat,
            longitude=coords.lng,
        )
        log.info("done", user_id=user_id, source=coords.source,
                 candidate=place.candidates[0])
    except Exception:
        log.exception("handle_photo failed", user_id=user_id)
        try:
            await status.edit_text("⚠️ 處理失敗,請稍後重試")
        except Exception:
            pass
