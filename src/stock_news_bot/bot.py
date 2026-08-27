"""봇 인스턴스 생성과 코그 로드를 담당하는 코어 모듈.

명령 체계를 여기서 일원화한다: 어떤 코그를 어떤 순서로 로드할지는
cogs/__init__.py의 LOAD_ORDER 하나만 보면 알 수 있게 한다.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from stock_news_bot.cogs import LOAD_ORDER
from stock_news_bot.config import Settings
from stock_news_bot.monitor.telegram_alert import TelegramAlerter
from stock_news_bot.status import status as bot_status

logger = logging.getLogger(__name__)

# 로그에 영어 모듈 경로 대신 한글로 표시하기 위한 이름표.
_COG_KOREAN_NAME = {
    "stock_news_bot.cogs.fetcher": "뉴스 수집기",
    "stock_news_bot.cogs.classifier": "뉴스 분류기",
    "stock_news_bot.cogs.notifier": "알림 전송기",
    "stock_news_bot.cogs.market_intel": "시세 연동(DART/pykrx)",
    "stock_news_bot.cogs.scheduler": "자동 스케줄러",
    "stock_news_bot.cogs.admin": "관리자 명령",
}


def _cog_label(extension: str) -> str:
    name = _COG_KOREAN_NAME.get(extension, extension)
    return f"{name} ({extension})"


class StockNewsBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        # 뉴스 알림 봇은 메시지 콘텐츠를 읽을 필요가 없으므로 최소 권한만 켠다
        # (Privileged Intent 신청 없이 바로 운영 가능하도록).
        super().__init__(command_prefix="!stocknews-unused-", intents=intents)
        self.settings = settings

    async def setup_hook(self) -> None:
        for extension in LOAD_ORDER:
            try:
                await self.load_extension(extension)
                logger.info("코그 로드 완료: %s", _cog_label(extension))
            except Exception:
                logger.exception("코그 로드 실패: %s", _cog_label(extension))
                raise

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("슬래시 명령을 길드(%s)에 동기화했습니다.", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("슬래시 명령을 전역으로 동기화했습니다 (반영까지 최대 1시간 소요될 수 있음).")

    async def on_ready(self) -> None:
        logger.info("로그인 완료: %s (id=%s)", self.user, self.user.id if self.user else "?")
        bot_status.mark_ready(str(self.user))

    async def on_error(self, event_method: str, /, *args, **kwargs) -> None:
        """이벤트 핸들러 내부에서 잡히지 않은 예외에 대한 최후 방어선.
        discord.py 기본 동작(스택트레이스만 stderr에 출력)에 더해
        텔레그램으로도 알린다."""
        logger.exception("처리되지 않은 이벤트 오류: %s", event_method)
        alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
        await alerter.send(f"❌ [stock-news-bot] 이벤트 '{event_method}' 처리 중 미처리 예외 발생")


def create_bot(settings: Settings) -> StockNewsBot:
    return StockNewsBot(settings)
