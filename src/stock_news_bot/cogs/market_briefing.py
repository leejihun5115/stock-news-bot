"""국내/미국장 마켓 브리핑 코그.

기존 파이프라인(classifier -> scheduler)은 "관련주가 없는 뉴스는 보내지
않는다"는 원칙으로 동작한다(scheduler.py의 "관련테마/관련주 없음으로 제외"
로그 참고). 그런데 "코스피 마감 시황", "뉴욕증시 마감" 같은 지수/거시 뉴스는
태생적으로 특정 종목명이 안 걸리기 때문에 그 필터에서 항상 걸러진다.

이 코그는 그 필터를 우회하려는 게 아니라, 애초에 종목 뉴스 파이프라인과는
별개의 성격(하루 몇 차례, 정해진 시각에 오는 "시황 요약")이라고 보고 완전히
독립된 스케줄/포맷으로 발송한다. 종목 점수 로직에는 관여하지 않는다.

동작 방식:
  1. discord.ext.tasks의 time= 파라미터로 KST 기준 정해진 시각에 실행한다
     (예: 국내 장마감 15:40, 미국장 마감 다음날 아침 07:00).
  2. 구글 뉴스 검색 RSS(fetcher.fetch_feed 재사용)로 지정된 검색어의 최신
     기사를 모아, lookback 시간 내의 것만 상위 N건 추린다.
  3. Discord 임베드 + 텔레그램 메시지로 헤드라인 목록을 요약 발송한다.

MARKET_BRIEFING_ENABLED=true로 켜야 동작한다(기본 꺼짐).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.fetcher import fetch_feed
from stock_news_bot.models import NewsItem
from stock_news_bot.monitor.telegram_alert import TelegramAlerter

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def _parse_hhmm_kst(value: str) -> time:
    """'08:40' 형식 문자열을 KST tzinfo가 붙은 datetime.time으로 변환한다.

    config.py의 load_settings()에서 이미 형식을 검증했으므로 여기서는
    파싱 실패를 걱정하지 않아도 된다(방어적으로 ValueError는 남겨둔다).
    """
    hh, mm = value.split(":")
    return time(hour=int(hh), minute=int(mm), tzinfo=_KST)


def _google_news_rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"


class MarketBriefingCog(commands.Cog, name="MarketBriefing"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )

        if not self.settings.market_briefing_enabled:
            logger.info("마켓 브리핑(국내/미국장): 비활성화 (MARKET_BRIEFING_ENABLED=true로 설정하면 켜집니다)")
            return

        kr_times = [_parse_hhmm_kst(t) for t in self.settings.market_briefing_kr_times]
        us_times = [_parse_hhmm_kst(t) for t in self.settings.market_briefing_us_times]

        # tasks.loop(time=...)는 클래스 데코레이터 시점에 고정되므로, 인스턴스별
        # 커스텀 시각을 쓰려면 이렇게 __init__에서 change_interval 대신
        # 태스크 자체를 다시 만들어 등록해야 한다.
        self.kr_briefing_loop = tasks.loop(time=kr_times)(self._run_kr_briefing)
        self.us_briefing_loop = tasks.loop(time=us_times)(self._run_us_briefing)
        self.kr_briefing_loop.before_loop(self._before_loop)
        self.us_briefing_loop.before_loop(self._before_loop)
        self.kr_briefing_loop.start()
        self.us_briefing_loop.start()
        logger.info(
            "마켓 브리핑(국내/미국장): 활성화 (국내=%s KST, 미국=%s KST)",
            ", ".join(self.settings.market_briefing_kr_times),
            ", ".join(self.settings.market_briefing_us_times),
        )

    def cog_unload(self) -> None:
        if getattr(self, "kr_briefing_loop", None):
            self.kr_briefing_loop.cancel()
        if getattr(self, "us_briefing_loop", None):
            self.us_briefing_loop.cancel()

    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_kr_briefing(self) -> None:
        await self._run_briefing(
            label="국내",
            emoji="🇰🇷",
            title="국내 증시 브리핑",
            query=self.settings.market_briefing_kr_query,
        )

    async def _run_us_briefing(self) -> None:
        await self._run_briefing(
            label="미국",
            emoji="🇺🇸",
            title="미국장 브리핑",
            query=self.settings.market_briefing_us_query,
        )

    async def _fetch_items(self, query: str) -> list[NewsItem]:
        url = _google_news_rss_url(query)
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0 stock-news-bot/1.0", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
        ) as session:
            items = await fetch_feed(
                session, url,
                timeout_seconds=self.settings.fetch_timeout_seconds,
                max_retries=self.settings.fetch_max_retries,
            )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.settings.market_briefing_lookback_hours)
        items = [i for i in items if i.published_at >= cutoff]
        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[: self.settings.market_briefing_max_items]

    async def _run_briefing(self, *, label: str, emoji: str, title: str, query: str) -> None:
        try:
            items = await self._fetch_items(query)
        except Exception:
            logger.exception("%s 브리핑 수집 실패 (검색어=%r)", label, query)
            return

        if not items:
            logger.info("%s 브리핑: 최근 %.0f시간 내 기사 없음 (검색어=%r) — 발송 생략", label, self.settings.market_briefing_lookback_hours, query)
            return

        now_kst = datetime.now(timezone.utc).astimezone(_KST)
        header = f"{emoji} {title} ({now_kst.strftime('%m/%d %H:%M')} KST)"

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                embed.add_field(
                    name=f"[{pub_kst}] {item.source}",
                    value=f"[{item.title[:100]}]({item.url})",
                    inline=False,
                )
            await channel.send(embed=embed)
        except Exception:
            logger.exception("%s 브리핑 디스코드 전송 실패", label)

        # Telegram (독립 채널 — 디스코드 실패와 무관하게 항상 별도 시도)
        try:
            lines = [f"<b>{header}</b>", ""]
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                lines.append(f"• [{pub_kst}] <a href=\"{item.url}\">{item.title[:100]}</a> ({item.source})")
            await self.alerter.send("\n".join(lines))
        except Exception:
            logger.exception("%s 브리핑 텔레그램 전송 실패", label)

        logger.info("%s 브리핑 발송 완료 | 기사 %d건 | 검색어=%r", label, len(items), query)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketBriefingCog(bot))
