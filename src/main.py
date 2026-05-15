import asyncio

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.bot import create_app
from src.config import settings
from src.logger import get_logger

log = get_logger(__name__)


async def _amain() -> None:
    log.info("Bot starting", model=settings.LLM_MODEL)
    app = create_app()
    handler = AsyncSocketModeHandler(app, settings.SLACK_APP_TOKEN)
    await handler.start_async()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
