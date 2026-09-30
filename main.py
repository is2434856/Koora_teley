"""نقطة التشغيل الرئيسية."""

from __future__ import annotations

import asyncio
import logging
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import API_HASH, API_ID, BOT_TOKEN, SESSION_STRING
from relay import run_once
from state_manager import StateManager


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


async def main() -> int:
    user_client = TelegramClient(
        StringSession(SESSION_STRING),
        API_ID,
        API_HASH,
        sequential_updates=True,
    )
    bot_client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        sequential_updates=True,
    )

    state = StateManager()

    try:
        logging.info("Connecting personal Telegram session...")
        await user_client.start()
        if not await user_client.is_user_authorized():
            raise RuntimeError("Telegram personal session is not authorized")

        logging.info("Connecting bot...")
        await bot_client.start(bot_token=BOT_TOKEN)

        me = await user_client.get_me()
        bot_me = await bot_client.get_me()
        logging.info(
            "Connected: user=%s | bot=@%s",
            getattr(me, "username", None) or getattr(me, "id", "unknown"),
            getattr(bot_me, "username", None) or getattr(bot_me, "id", "unknown"),
        )

        stats = await run_once(user_client, bot_client, state)
        logging.info("Run finished: %s", stats)
        return 0
    except Exception:
        logging.exception("Fatal error")
        return 1
    finally:
        await bot_client.disconnect()
        await user_client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
