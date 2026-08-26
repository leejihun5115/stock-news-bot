"""단일 진입점.

    python -m stock_news_bot

이 명령 하나만으로 봇이 실행되어야 한다. 다른 진입 경로(예: 개별
스크립트에서 discord.Client를 새로 만드는 것)는 만들지 않는다 —
"명령 체계를 하나로 통일"한다는 아키텍처 원칙을 지키기 위함이다.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from stock_news_bot.bot import create_bot
from stock_news_bot.config import settings
from stock_news_bot.utils.errors import ConfigError
from stock_news_bot.utils.logger import setup_logging

logger = logging.getLogger(__name__)


async def _run() -> None:
    bot = create_bot(settings)
    async with bot:
        await bot.start(settings.discord_token)


def main() -> None:
    setup_logging(settings.log_dir, settings.log_level)
    logger.info("stock-news-bot 시작")
    try:
        asyncio.run(_run())
    except ConfigError as exc:
        logger.error("설정 오류로 시작할 수 없습니다: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("종료 신호를 받아 정상 종료합니다.")


if __name__ == "__main__":
    main()
