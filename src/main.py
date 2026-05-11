from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.bot import cmd_help, cmd_start, handle_non_photo, handle_photo
from src.config import settings
from src.logger import get_logger

log = get_logger(__name__)


def main() -> None:
    log.info("Bot starting", model=settings.LLM_MODEL)
    app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_non_photo))
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
