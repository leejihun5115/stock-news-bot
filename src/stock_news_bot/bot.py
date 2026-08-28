"""봇 인스턴스 생성과 코그 로드를 담당하는 코어 모듈.

명령 체계를 여기서 일원화한다: 어떤 코그를 어떤 순서로 로드할지는
cogs/__init__.py의 LOAD_ORDER 하나만 보면 알 수 있게 한다.
"""
from __future__ import annotations

import asyncio
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

        # 명령 동기화는 로그인/READY를 막지 않도록 백그라운드에서 처리한다.
        # Discord 전역 sync를 setup_hook에서 기다리면 콜드스타트 때
        # "부팅은 됐는데 뉴스가 시작되지 않는" 것처럼 보이는 시간을 만든다.
        self._commands_synced = False

    async def on_ready(self) -> None:
        logger.info("로그인 완료: %s (id=%s)", self.user, self.user.id if self.user else "?")
        bot_status.mark_ready(str(self.user))

        # 재연결 때마다 명령 동기화/부팅 알림이 중복되지 않도록 1회만 실행한다.
        if not self._commands_synced:
            self._commands_synced = True
            asyncio.create_task(self._sync_commands_after_ready(), name="discord-command-sync")
            asyncio.create_task(self._send_boot_notice(), name="boot-notice")

    async def _sync_commands_after_ready(self) -> None:
        try:
            if self.settings.discord_guild_id:
                guild = discord.Object(id=self.settings.discord_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("슬래시 명령을 길드(%s)에 동기화했습니다.", self.settings.discord_guild_id)
            else:
                await self.tree.sync()
                logger.info("슬래시 명령 전역 동기화 완료")
        except Exception:
            logger.exception("슬래시 명령 동기화 실패 — 봇/뉴스 수집은 계속 실행합니다.")
            alerter = TelegramAlerter(
                bot_token=self.settings.telegram_bot_token,
                chat_id=self.settings.telegram_chat_id,
                enabled=self.settings.telegram_alert_enabled,
            )
            await alerter.send("🚨 [stock-news-bot] 슬래시 명령 동기화에 실패했습니다. 뉴스 수집은 계속 실행합니다.")

    async def _send_boot_notice(self) -> None:
        channel_id = self.settings.discord_admin_channel_id or self.settings.discord_news_channel_id
        channel = self.get_channel(channel_id)
        if channel is None:
            logger.warning("부팅 확인 채널(id=%s)을 찾을 수 없습니다.", channel_id)
            return
        keywords = list(dict.fromkeys(self.settings.news_keywords))
        feeds = self.settings.effective_feed_urls()
        extensions = ", ".join(self.cogs.keys()) or "없음"
        message = (
            "🚀 **[뉴스봇 부팅 확인]**\n\n"
            "↳ 상태: **정상 기동**\n"
            f"↳ 실행 버전: **BOOT-DIAGNOSTIC-V21**\n"
            f"↳ 검색 키워드: **{len(keywords)}개**\n"
            f"↳ 검색 피드: **{len(feeds)}개**\n"
            f"↳ 최소 전송 점수: **{self.settings.news_value_mid}점**\n"
            f"↳ 수집 주기: **{self.settings.fetch_interval_seconds}초**\n"
            f"↳ 로드 코그: **{extensions}**\n\n"
            "✅ 부팅 완료 후 뉴스 수집을 즉시 시작합니다.\n"
            "`/search-status`로 실제 검색 상태를 확인할 수 있습니다."
        )
        try:
            await channel.send(message[:1900], allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            logger.exception("부팅 확인 메시지 전송 실패")

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
