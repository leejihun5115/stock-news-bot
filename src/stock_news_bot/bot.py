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
        self._boot_notice_sent = False

    async def on_ready(self) -> None:
        logger.info("로그인 완료: %s (id=%s)", self.user, self.user.id if self.user else "?")
        bot_status.mark_ready(str(self.user))

        # 부팅 확인은 명령 동기화와 분리한다. READY 직후 직접 전송해서
        # 슬래시 명령 sync나 다른 무거운 작업 때문에 부팅 메시지가 늦어지지 않게 한다.
        if not self._boot_notice_sent:
            await self._send_boot_notice()

        if not self._commands_synced:
            self._commands_synced = True
            asyncio.create_task(self._sync_commands_after_ready(), name="discord-command-sync")

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
        """Discord READY 직후 부팅 확인을 즉시 전송한다.

        관리자 채널이 없거나 캐시에 없으면 뉴스 채널로 fallback하고,
        일시적인 Discord API 지연에도 최대 3회 재시도한다.
        """
        if self._boot_notice_sent:
            return

        channel_ids = []
        for channel_id in (self.settings.discord_admin_channel_id, self.settings.discord_news_channel_id):
            if channel_id and channel_id not in channel_ids:
                channel_ids.append(channel_id)

        if not channel_ids:
            logger.error("부팅 확인 채널이 없습니다: DISCORD_ADMIN_CHANNEL_ID / DISCORD_NEWS_CHANNEL_ID")
            return

        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        boot_time = datetime.now(timezone.utc).astimezone(kst).strftime("%Y-%m-%d %H:%M:%S")
        keywords = list(dict.fromkeys(self.settings.news_keywords))
        feeds = self.settings.effective_feed_urls()
        message = (
            "✅ **[통제소] 뉴스봇 부팅 완료**\n\n"
            f"↳ 상태: **정상 기동 · KST={boot_time}**\n"
            f"↳ 검색 키워드: **{len(keywords)}개**\n"
            f"↳ 검색 피드: **{len(feeds)}개**\n"
            f"↳ 최소 전송 점수: **{self.settings.news_value_mid}점**\n"
            f"↳ 수집 주기: **{self.settings.fetch_interval_seconds}초**\n\n"
            "✅ **뉴스 수집을 즉시 시작합니다.**\n"
            "`/status` · `/run-now` · `/pause` · `/resume` · `/search-status` · `/help`"
        )

        for attempt in range(1, 4):
            for channel_id in channel_ids:
                channel = self.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.fetch_channel(channel_id)
                    except Exception as exc:
                        logger.warning("부팅 확인 채널 조회 실패(%s회, id=%s): %s", attempt, channel_id, exc)
                        continue
                try:
                    await channel.send(message[:1900], allowed_mentions=discord.AllowedMentions.none())
                    self._boot_notice_sent = True
                    logger.info("✅ 통제소 부팅 완료 메시지 전송 성공: 채널=%s", channel_id)
                    return
                except Exception as exc:
                    logger.warning("부팅 확인 메시지 전송 실패(%s회, id=%s): %s", attempt, channel_id, exc)
            if attempt < 3:
                await asyncio.sleep(attempt * 2)

        logger.error("🚨 부팅 확인 메시지를 Discord로 전송하지 못했습니다. 채널 ID와 봇 권한을 확인하세요.")
        # 주의: StockNewsBot 인스턴스 자체에는 alerter가 없다(스케줄러 코그에만
        # 있음). 여기서 self.alerter를 쓰면 AttributeError로 이 예외 경로
        # 자체가 죽는다 — 그래서 이 실패 전용 알림에서만 별도 인스턴스를 만든다.
        alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
        await alerter.send("🚨 [stock-news-bot] 봇은 로그인했지만 부팅 확인 메시지를 Discord로 보내지 못했습니다. 관리자/뉴스 채널 ID와 봇의 메시지 전송 권한을 확인하세요.")

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
