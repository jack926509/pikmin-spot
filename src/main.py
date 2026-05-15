import asyncio

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from src.bot import create_app
from src.config import settings
from src.logger import get_logger

log = get_logger(__name__)


async def _preflight() -> None:
    """Verify both tokens before opening a WebSocket, so misconfiguration
    surfaces as one clear log line instead of an infinite reconnect loop."""
    bot = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    try:
        auth = await bot.auth_test()
        log.info(
            "Bot token OK",
            team=auth.get("team"),
            user=auth.get("user"),
            bot_id=auth.get("bot_id"),
        )
    except Exception as e:
        log.error(
            "SLACK_BOT_TOKEN 驗證失敗 — 請確認 token 正確且 App 已安裝到 workspace",
            error=str(e),
        )
        raise

    app = AsyncWebClient(token=settings.SLACK_APP_TOKEN)
    try:
        resp = await app.api_call("apps.connections.open")
        if not resp.get("ok"):
            raise RuntimeError(f"apps.connections.open ok=False: {resp.data}")
        log.info("App-Level token OK (Socket Mode 可連線)")
    except Exception as e:
        log.error(
            "SLACK_APP_TOKEN 驗證失敗 — 請確認:"
            " (1) Slack App 已啟用 Socket Mode;"
            " (2) App-Level Token scope 包含 connections:write;"
            " (3) 變數填的是 xapp- 而不是 xoxb-",
            error=str(e),
        )
        raise


async def _amain() -> None:
    log.info("Bot starting", model=settings.LLM_MODEL)
    await _preflight()
    app = create_app()
    handler = AsyncSocketModeHandler(app, settings.SLACK_APP_TOKEN)
    await handler.start_async()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
