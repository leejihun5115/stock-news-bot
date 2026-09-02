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
import asyncio

import logging
from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.fetcher import fetch_feed, fetch_source_feeds
from stock_news_bot.cogs.llm_analyzer import analyze_news
from stock_news_bot.global_market import collect_global_market_prompt
from stock_news_bot.models import NewsItem
from stock_news_bot.monitor.telegram_alert import TelegramAlerter

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")

_NO_CONTENT_MARKERS = (
    "구체적인 내용이 없",
    "본문이 없",
    "본문 부재",
    "분석할 수 없",
    "분석을 수행할 수 없",
    "확인할 수 없습니다",
    "추출 사실 없음",
    "추출된 사실이 없",
    "재무 수치나 사업 근거를 제시하지 않",
)


def _meaningful_lines(items: list[str]) -> list[str]:
    """AI가 '내용 없음/분석 불가' 류로 답한 무의미한 문장은 표시에서 제외한다."""
    return [t for t in items if t and not any(marker in t for marker in _NO_CONTENT_MARKERS)]


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

        # 국내 브리핑은 기존 설정 시각을 그대로 사용한다.
        self.kr_briefing_loop = tasks.loop(time=kr_times)(self._run_kr_briefing)

        # 미국장 브리핑은 설정된 특정 시각이 아니라 30분 간격으로 실행한다.
        # 봇 기동 후 1회 실행되고 이후 30분마다 반복된다.
        self.us_briefing_loop = tasks.loop(minutes=30)(self._run_us_briefing)
        self.kr_briefing_loop.before_loop(self._before_loop)
        self.us_briefing_loop.before_loop(self._before_loop)
        self.kr_briefing_loop.start()
        self.us_briefing_loop.start()
        logger.info(
            "마켓 브리핑(국내/미국장): 활성화 (국내=%s KST, 미국=30분 간격)",
            ", ".join(self.settings.market_briefing_kr_times),
        )

    @commands.command(name="미국장브리핑", aliases=["usbriefing"])
    @commands.is_owner()
    async def manual_us_briefing(self, ctx: commands.Context) -> None:
        """봇 소유자만 수동으로 미국장 브리핑을 1회 실행한다."""
        await ctx.send("🇺🇸 미국장 브리핑 수동 실행을 시작합니다...")

        try:
            await self._run_us_briefing()
            logger.info("🇺🇸 미국장 브리핑 수동 실행 완료")
        except Exception:
            logger.exception("🇺🇸 미국장 브리핑 수동 실행 실패")
            try:
                await ctx.send("❌ 미국장 브리핑 수동 실행 중 오류가 발생했습니다.")
            except Exception:
                pass

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
        """미국장 브리핑용 뉴스 수집.

        기존 RSS_FEEDS/BLOG_FEEDS와 미국장 Google News 검색 RSS를 함께 수집한다.
        개별 피드가 실패해도 다른 피드는 계속 수집한다.
        """
        google_url = _google_news_rss_url(query)

        urls = list(dict.fromkeys(
            list(self.settings.rss_feeds)
            + [google_url]
        ))
        blog_feeds = (
            list(self.settings.blog_feeds)
            if self.settings.enable_blog
            else []
        )

        items, errors = await fetch_source_feeds(
            urls=urls,
            blog_feeds=blog_feeds,
            youtube_channel_ids=[],
            telegram_channels=[],
            timeout_seconds=self.settings.fetch_timeout_seconds,
            max_retries=self.settings.fetch_max_retries,
        )

        if errors:
            logger.warning(
                "미국장 브리핑 RSS 일부 수집 실패: %d건",
                len(errors),
            )

        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.settings.market_briefing_lookback_hours
        )
        items = [i for i in items if i.published_at >= cutoff]

        # URL/제목 기준 기본 중복 제거
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in items:
            key = (item.url or item.title).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)

        unique.sort(key=lambda i: i.published_at, reverse=True)

        return unique[: self.settings.market_briefing_max_items]

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

        # 기존 LLM 분석 엔진으로 뉴스 분석 (국내/미국 공용)
        ai_results = {}

        # 국내 브리핑일 때만 글로벌 지표(환율/금리/유가/미국지수/반도체/야간선물/ADR 등)를
        # 수집해서, 국내 종목 개별 분석 시 AI가 참고할 컨텍스트로 함께 넘긴다.
        # 수집 실패해도 브리핑 발송 자체는 막지 않는다(빈 컨텍스트로 계속 진행).
        global_market_context = ""
        if label in ("국내", "미국"):
            try:
                global_market_context = await asyncio.to_thread(collect_global_market_prompt)
            except Exception:
                logger.exception("%s 브리핑용 글로벌 시장 데이터 수집 실패 — 글로벌 컨텍스트 없이 진행합니다", label)
                global_market_context = ""

        for item in items:
            try:
                ai = await asyncio.to_thread(
                    analyze_news,
                    gemini_api_key=self.settings.gemini_api_key,
                    openrouter_api_key=self.settings.openrouter_api_key,
                    openrouter_model=self.settings.openrouter_model,
                    title=item.title,
                    summary=item.summary or "",
                    company=item.company or "",
                    reason=item.reason or "",
                    amounts=item.amounts or [],
                    progress_stage=item.progress_stage or "",
                    theme=label,
                    score=item.score or 0,
                    history_hint=global_market_context,
                    article_body="",
                    timeout_seconds=self.settings.fetch_timeout_seconds,
                    max_chars=9000,
                    study_mode=False,
                )

                if ai:
                    if ai.title and any(marker in ai.title for marker in _NO_CONTENT_MARKERS):
                        ai.title = ""
                    ai.core = _meaningful_lines(ai.core)
                    ai.analysis = _meaningful_lines(ai.analysis)
                    ai_results[item.url or item.title] = ai
                    logger.info(
                        "🇺🇸 미국장 AI 분석 완료 | %s",
                        item.title[:80],
                    )
            except Exception as exc:
                logger.warning(
                    "🇺🇸 미국장 AI 분석 실패 | %s | %s",
                    item.title[:80],
                    str(exc)[:300],
                )

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if global_market_context:
                embed.description = f"🌎 글로벌 시장 영향\n{global_market_context[:600]}"
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                embed.add_field(
                    name=f"[{pub_kst}] {item.source}",
                    value=(
                        f"[{(ai_results.get(item.url or item.title).title if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).title else item.title)[:100]}]({item.url})"
                        + (
                            "\\n🧠 **핵심:** "
                            + " / ".join(ai_results.get(item.url or item.title).core[:2])
                            if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).core
                            else ""
                        )
                        + (
                            "\\n📊 **분석:** "
                            + " / ".join(ai_results.get(item.url or item.title).analysis[:1])
                            if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).analysis
                            else ""
                        )
                        + (
                            f"\\n🎯 **AI 점수:** {ai_results.get(item.url or item.title).score}"
                            if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).score
                            else ""
                        )
                        + (
                            f"\\n🔎 **신뢰도:** {ai_results.get(item.url or item.title).confidence}%"
                            if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).confidence
                            else ""
                        )
                    ),
                    inline=False,
                )
            try:
                await channel.send(embed=embed)
            except discord.errors.HTTPException as http_exc:
                if embed.description:
                    logger.warning(
                        "%s 브리핑 디스코드 임베드 크기 초과 — 글로벌 시장 요약 없이 재전송 시도 | %s",
                        label, str(http_exc)[:200],
                    )
                    embed.description = None
                    await channel.send(embed=embed)
                else:
                    raise
        except Exception:
            logger.exception("%s 브리핑 디스코드 전송 실패", label)

        # Telegram (독립 채널 — 디스코드 실패와 무관하게 항상 별도 시도)
        try:
            lines = [f"<b>{header}</b>", ""]
            if global_market_context:
                lines.append("🌎 <b>글로벌 시장 영향</b>")
                lines.append(global_market_context[:1500])
                lines.append("")
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                ai = ai_results.get(item.url or item.title)
                if ai:
                    title = ai.title or item.title
                    lines.append(
                        f"• [{pub_kst}] <a href=\"{item.url}\"><b>{title[:100]}</b></a> ({item.source})"
                    )
                    if ai.core:
                        lines.append("  🧠 " + " / ".join(ai.core[:2]))
                    if ai.analysis:
                        lines.append("  📊 " + " / ".join(ai.analysis[:1]))
                    if ai.score:
                        lines.append(f"  🎯 AI 점수 {ai.score}")
                    if ai.confidence:
                        lines.append(f"  🔎 신뢰도 {ai.confidence}%")
                else:
                    lines.append(
                        f"• [{pub_kst}] <a href=\"{item.url}\">{item.title[:100]}</a> ({item.source})"
                    )
            await self.alerter.send("\n".join(lines))
        except Exception:
            logger.exception("%s 브리핑 텔레그램 전송 실패", label)

        logger.info("%s 브리핑 발송 완료 | 기사 %d건 | 검색어=%r", label, len(items), query)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketBriefingCog(bot))
