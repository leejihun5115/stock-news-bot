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
from stock_news_bot.cogs.llm_analyzer import analyze_market_briefing, analyze_news
from stock_news_bot.global_market import (
    THEME_ORDER,
    collect_global_market_prompt,
    collect_theme_leader_stocks,
)
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


_KR_MARKET_OPEN = time(9, 0, tzinfo=_KST)
_KR_MARKET_CLOSE = time(15, 30, tzinfo=_KST)
_US_EASTERN = ZoneInfo("America/New_York")
_US_MARKET_OPEN_ET = time(9, 30)
_US_MARKET_CLOSE_ET = time(16, 0)


def _is_kr_market_hours(now_kst: datetime) -> bool:
    """국내 정규장 시간(09:00~15:30 KST, 평일)인지 확인한다. 공휴일은 별도로
    반영하지 않는다(추후 필요 시 휴장일 목록을 추가하면 된다)."""
    if now_kst.weekday() >= 5:
        return False
    return _KR_MARKET_OPEN <= now_kst.timetz() <= _KR_MARKET_CLOSE


def _is_us_market_hours(now_utc: datetime) -> bool:
    """미국 정규장 시간(09:30~16:00 ET, 평일)인지 확인한다. America/New_York
    타임존을 그대로 써서 서머타임(DST) 전환을 자동으로 반영한다."""
    now_et = now_utc.astimezone(_US_EASTERN)
    if now_et.weekday() >= 5:
        return False
    return _US_MARKET_OPEN_ET <= now_et.time() <= _US_MARKET_CLOSE_ET


def _minutes_since_us_close(now_utc: datetime) -> float | None:
    """지금이 미국 정규장 마감(16:00 ET) 이후 몇 분 지났는지 반환한다(장중/주말이면
    None). America/New_York 기준이라 서머타임과 무관하게 항상 정확하다."""
    now_et = now_utc.astimezone(_US_EASTERN)
    if now_et.weekday() >= 5:
        return None
    close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    delta = (now_et - close_et).total_seconds() / 60
    return delta if delta >= 0 else None


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

        # 국내: 장중(09:00~15:30 KST, 평일)에만 30분 간격으로 발송하고,
        # 장마감 이후 한 번 더 "마감" 브리핑을 별도로 보낸다.
        self.kr_briefing_loop = tasks.loop(minutes=30)(self._run_kr_briefing)
        self.kr_close_loop = tasks.loop(time=[time(15, 40, tzinfo=_KST)])(self._run_kr_close_briefing)

        # 미국: 정규장 시간(09:30~16:00 ET, 평일)에만 30분 간격으로 발송한다.
        # 마감 브리핑은 서머타임에 따라 KST 마감 시각이 05:00/06:00으로 바뀌므로,
        # 두 후보 시각에 다 걸어두고 실제로 마감 직후(40분 이내)인 쪽만 함수
        # 안에서 판별해 보낸다(중복 발송 방지).
        self.us_briefing_loop = tasks.loop(minutes=30)(self._run_us_briefing)
        self.us_close_loop = tasks.loop(time=[time(5, 5, tzinfo=_KST), time(6, 5, tzinfo=_KST)])(self._run_us_close_briefing)

        for loop in (self.kr_briefing_loop, self.kr_close_loop, self.us_briefing_loop, self.us_close_loop):
            loop.before_loop(self._before_loop)
        for loop in (self.kr_briefing_loop, self.kr_close_loop, self.us_briefing_loop, self.us_close_loop):
            loop.start()
        logger.info(
            "마켓 브리핑(국내/미국장): 활성화 (국내=장중 30분 간격+15:40 마감, 미국=장중 30분 간격+마감 자동감지)",
        )

    @commands.command(name="미국장브리핑", aliases=["usbriefing"])
    @commands.is_owner()
    async def manual_us_briefing(self, ctx: commands.Context) -> None:
        """봇 소유자만 수동으로 미국장 브리핑을 1회 실행한다."""
        await ctx.send("🇺🇸 미국장 브리핑 수동 실행을 시작합니다...")

        try:
            await self._run_briefing(
                label="미국",
                emoji="🇺🇸",
                title="미국장 브리핑",
                query=self.settings.market_briefing_us_query,
            )
            logger.info("🇺🇸 미국장 브리핑 수동 실행 완료")
        except Exception:
            logger.exception("🇺🇸 미국장 브리핑 수동 실행 실패")
            try:
                await ctx.send("❌ 미국장 브리핑 수동 실행 중 오류가 발생했습니다.")
            except Exception:
                pass

    def cog_unload(self) -> None:
        for attr in ("kr_briefing_loop", "kr_close_loop", "us_briefing_loop", "us_close_loop"):
            loop = getattr(self, attr, None)
            if loop:
                loop.cancel()

    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_kr_briefing(self) -> None:
        now_kst = datetime.now(timezone.utc).astimezone(_KST)
        if not _is_kr_market_hours(now_kst):
            logger.info("국내 브리핑: 장중 시간이 아니라 이번 30분 주기는 건너뜁니다 (%s)", now_kst.strftime("%H:%M"))
            return
        await self._run_briefing(
            label="국내",
            emoji="🇰🇷",
            title="국내 증시 브리핑",
            query=self.settings.market_briefing_kr_query,
        )

    async def _run_kr_close_briefing(self) -> None:
        await self._run_briefing(
            label="국내 마감",
            emoji="🇰🇷",
            title="국내 증시 마감 브리핑",
            query=self.settings.market_briefing_kr_query,
        )

    async def _run_us_briefing(self) -> None:
        now_utc = datetime.now(timezone.utc)
        if not _is_us_market_hours(now_utc):
            logger.info("미국장 브리핑: 장중 시간이 아니라 이번 30분 주기는 건너뜁니다")
            return
        await self._run_briefing(
            label="미국",
            emoji="🇺🇸",
            title="미국장 브리핑",
            query=self.settings.market_briefing_us_query,
        )

    async def _run_us_close_briefing(self) -> None:
        now_utc = datetime.now(timezone.utc)
        minutes_since_close = _minutes_since_us_close(now_utc)
        # 서머타임에 따라 마감 시각이 05:00 또는 06:00 KST로 달라지므로,
        # 두 후보 시각 다 걸어두고 실제 마감 직후(40분 이내)인 쪽만 보낸다.
        if minutes_since_close is None or minutes_since_close > 40:
            return
        await self._run_briefing(
            label="미국 마감",
            emoji="🇺🇸",
            title="미국장 마감 브리핑",
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
        if label.startswith(("국내", "미국")):
            try:
                global_market_context = await asyncio.to_thread(collect_global_market_prompt)
            except Exception:
                logger.exception("%s 브리핑용 글로벌 시장 데이터 수집 실패 — 글로벌 컨텍스트 없이 진행합니다", label)
                global_market_context = ""

        # 국내/미국 브리핑 공통으로, 누적 뉴스 데이터에서 실제로 등장한
        # 테마별 관련종목(유가/금리/환율/금/구리/천연가스/비트코인/반도체)을
        # 집계해 덧붙인다(AI가 종목명을 지어내지 않고, 원문에 실제로
        # 있었던 종목만 사용 — collect_theme_leader_stocks 참고). 미국장
        # 브리핑에서도 seen_news에 쌓인 국내 상장사 매칭 결과를 그대로
        # 재사용한다 — 미국발 테마 뉴스가 국내 어떤 종목과 함께 언급돼
        # 왔는지 보여주는 용도라, 새 매칭 로직을 따로 만들지 않는다.
        # 테마별로 데이터가 없으면 그 테마 섹션만 조용히 생략된다.
        theme_leaders_context = ""
        if label.startswith(("국내", "미국")):
            theme_sections: list[str] = []
            for theme_name in THEME_ORDER:
                try:
                    section = await asyncio.to_thread(
                        collect_theme_leader_stocks, self.settings.db_path, theme_name, 3
                    )
                except Exception:
                    logger.exception(
                        "%s 브리핑용 '%s' 테마 관련종목 집계 실패 — 이 테마만 생략하고 진행합니다",
                        label, theme_name,
                    )
                    section = ""
                if section:
                    theme_sections.append(section)
            theme_leaders_context = "\n\n".join(theme_sections)
            if theme_leaders_context:
                global_market_context = (
                    f"{global_market_context}\n\n{theme_leaders_context}"
                    if global_market_context
                    else theme_leaders_context
                )

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

        # 개별 기사 제목 + 핵심 분석을 모아 "브리핑 종합" AI 요약을 만든다.
        # (원본 global_market_context 숫자 뭉치를 그대로 노출하던 걸 대체함)
        briefing_summary_text = ""
        if global_market_context:
            items_text = "\n".join(
                item.title
                + (
                    " - " + " / ".join(ai_results[item.url or item.title].core[:2])
                    if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).core
                    else ""
                )
                for item in items
            )
            try:
                briefing = await asyncio.to_thread(
                    analyze_market_briefing,
                    gemini_api_key=self.settings.gemini_api_key,
                    openrouter_api_key=self.settings.openrouter_api_key,
                    openrouter_model=self.settings.openrouter_model,
                    label=label,
                    items_text=items_text,
                    global_market_context=global_market_context,
                    timeout_seconds=self.settings.fetch_timeout_seconds,
                )
            except Exception:
                logger.exception("%s 브리핑 종합(글로벌 시장 영향 요약) 실패 — 이 섹션 없이 진행합니다", label)
                briefing = None

            if briefing and (briefing.core or briefing.themes or briefing.stocks):
                parts = []
                if briefing.core:
                    parts.append(" / ".join(briefing.core))
                if briefing.themes:
                    parts.append("🏷 테마: " + ", ".join(briefing.themes))
                if briefing.stocks:
                    parts.append("🎯 관련주: " + ", ".join(briefing.stocks))
                briefing_summary_text = "\n".join(parts)

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if briefing_summary_text:
                embed.description = f"🌎 글로벌 시장 영향\n{briefing_summary_text[:600]}"
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
            if briefing_summary_text:
                lines.append("🌎 <b>글로벌 시장 영향</b>")
                lines.append(briefing_summary_text[:1500])
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
