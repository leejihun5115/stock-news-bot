"""RSS 피드 수집(공통 코어) + 수집 파이프라인 진입점(FetcherCog).

핵심 설계 원칙:
1. 코어 로직(fetch_feed, parse_entries)은 discord.py에 대해 전혀 모르는
   순수 함수/코루틴으로 만든다 → 디스코드 없이도 단위 테스트 가능.
2. Cog 클래스는 그 순수 함수들을 얇게 감싸는 어댑터 역할만 한다.
3. 피드 하나가 실패해도 나머지 피드 수집은 계속되어야 한다
   (asyncio.gather(..., return_exceptions=True)).
4. 일시적 네트워크 오류는 tenacity로 지수 백오프 재시도.

유튜브/텔레그램/블로그 전용 설정·수집 코드는 관리하기 쉽도록
stock_news_bot/cogs/content_sources.py 한 파일에 모아뒀다. 이 파일에는
모든 소스가 공유하는 일반 RSS 수집 코드(parse_entries/fetch_feed/fetch_all)와
그걸 실제로 호출해서 조립하는 FetcherCog만 남아있다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from html import unescape
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

import aiohttp
import feedparser
from discord.ext import commands
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stock_news_bot.models import NewsItem
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.utils.errors import FetchError

logger = logging.getLogger(__name__)


def _source_timezone(source_hint: str) -> ZoneInfo:
    """Timezone used only when an RSS timestamp has NO timezone information.

    Explicit offsets (GMT/+0000/-0400/etc.) always win.  For timezone-less
    timestamps, infer from the feed URL instead of the Render machine clock.
    This avoids the common US-news bug where a naive EDT/EST timestamp is
    accidentally interpreted as UTC.
    """
    text = (source_hint or "").lower()
    us_markers = (
        "news.google.com", "reuters.com", "cnbc.com", "bloomberg.com",
        "wsj.com", "marketwatch.com", "finance.yahoo.com", "nytimes.com",
        "washingtonpost.com", "foxbusiness.com", "investing.com",
        "seekingalpha.com", "barrons.com", "fool.com", "businessinsider.com",
    )
    if any(marker in text for marker in us_markers):
        return ZoneInfo("America/New_York")
    return ZoneInfo("Asia/Seoul")


def _parse_published(entry: dict, source_hint: str = "") -> datetime | None:
    """Return publication time as an absolute UTC datetime.

    Never adds a fixed 13/14-hour offset.  Explicit timezone information from
    the feed wins; otherwise a source-aware timezone is used (US feeds ->
    America/New_York with automatic DST, Korean/other feeds -> Asia/Seoul).
    """
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        parsed_struct = entry.get(f"{key}_parsed")

        if raw:
            text = str(raw).strip()
            # First honor an explicit RFC822/ISO timezone offset.
            try:
                parsed = parsedate_to_datetime(text)
                if parsed.tzinfo is not None:
                    return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
            try:
                iso = text.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(iso)
                if parsed.tzinfo is not None:
                    return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass

            # No timezone in the raw text: interpret it using the feed's
            # source timezone, with America/New_York automatically switching
            # between EDT (UTC-4) and EST (UTC-5).
            try:
                parsed = parsedate_to_datetime(text)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=_source_timezone(source_hint)).astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
            try:
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=_source_timezone(source_hint)).astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass

        # feedparser's struct_time is a fallback. It is only trusted when the
        # raw value did not exist; then interpret it in the source timezone.
        if parsed_struct:
            try:
                naive = datetime(*parsed_struct[:6])
                return naive.replace(tzinfo=_source_timezone(source_hint)).astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                pass

    return None


def parse_entries(raw_bytes: bytes, source_hint: str) -> list[NewsItem]:
    """feedparser로 파싱하고 NewsItem 리스트로 변환하는 순수 함수.

    feedparser 자체는 잘못된 XML에도 예외를 던지지 않고 `bozo` 플래그만
    세우는 특이한 라이브러리라, entries가 비어있는데 bozo=1이면 명시적으로
    FetchError로 승격시켜서 상위 로직이 실패를 인지하게 한다.
    """
    try:
        parsed = feedparser.parse(raw_bytes)
    except Exception as exc:
        # 일부 RSS/프록시가 깨진 XML을 반환하면 Python 3.14의 SAX 파서가
        # 내부 traceback을 남기며 예외를 직접 전파할 수 있다.
        # 이 예외는 개별 피드 실패로만 처리하고 전체 스케줄러를 흔들지 않는다.
        detail = str(exc).replace("\n", " ").strip()[:300]
        raise FetchError(f"[{source_hint}] RSS 형식 오류: {detail}") from None

    if parsed.bozo and not parsed.entries:
        detail = str(getattr(parsed, "bozo_exception", "알 수 없는 XML 오류"))
        detail = detail.replace("\n", " ").strip()[:300]
        raise FetchError(f"[{source_hint}] RSS 형식 오류: {detail}")

    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = unescape(re.sub(r"<[^>]+>", " ", str(entry.get("title", "") or ""))).strip()
        url = str(entry.get("link", "") or "").strip()
        if not title or not url:
            continue
        raw_summary = str(entry.get("summary", "") or "")
        summary = unescape(re.sub(r"<[^>]+>", " ", raw_summary))
        summary = re.sub(r"https?://\S+", " ", summary)
        summary = re.sub(r"\s+", " ", summary).strip()
        source = parsed.feed.get("title", source_hint) or source_hint
        published_at = _parse_published(entry, source_hint)
        if published_at is None:
            logger.warning("[%s] 발행시각을 확정할 수 없어 뉴스 제외: %s", source_hint, title[:120])
            continue
        items.append(
            NewsItem(
                title=title,
                url=url,
                source=source,
                published_at=published_at,
                summary=summary,
            )
        )
    return items


async def _fetch_raw(
    session: aiohttp.ClientSession, url: str, timeout_seconds: int, max_retries: int
) -> bytes:
    """일시적 네트워크 오류에 대해 지수 백오프로 재시도한다.
    재시도 횟수는 FETCH_MAX_RETRIES 설정값을 그대로 따른다."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max(1, max_retries)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    ):
        with attempt:
            # RSS 제공자/프록시가 이전 XML을 캐시해서 같은 목록만 돌려주는 문제를
            # 피한다. 특히 Google News RSS는 짧은 주기의 폴링에서 캐시 영향을
            # 받을 수 있으므로 요청마다 cache-buster를 붙인다.
            request_url = url
            separator = "&" if "?" in url else "?"
            if "news.google.com/rss" in url:
                request_url = f"{url}{separator}_cb={time.time_ns()}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0 Safari/537.36 stock-news-bot/1.0",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            }
            async with session.get(request_url, timeout=timeout, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.read()
    raise FetchError(f"'{url}' 수집 재시도 로직이 비정상 종료되었습니다.")  # 방어 코드, 도달 불가


async def fetch_feed(
    session: aiohttp.ClientSession,
    url: str,
    timeout_seconds: int = 10,
    max_retries: int = 3,
) -> list[NewsItem]:
    """피드 하나를 수집해 NewsItem 리스트로 반환. 실패 시 FetchError를 던진다."""
    try:
        raw = await _fetch_raw(session, url, timeout_seconds, max_retries)
    except Exception as exc:  # aiohttp/timeout 등 재시도 소진 후 최종 실패
        raise FetchError(f"'{url}' 수집 실패: {exc}") from exc
    try:
        return parse_entries(raw, source_hint=url)
    except FetchError:
        raise
    except Exception as exc:
        detail = str(exc).replace("\n", " ").strip()[:300]
        raise FetchError(f"'{url}' RSS 처리 실패: {detail}") from None






async def fetch_all(
    urls: list[str], timeout_seconds: int = 10, max_retries: int = 3
) -> tuple[list[NewsItem], list[FetchError]]:
    """피드를 제한된 동시성으로 수집한다.

    Google News RSS처럼 키워드가 많아질수록 동시 요청이 폭증하는 공급원은
    세마포어로 압력을 낮춘다. 한 피드 실패는 다른 피드에 영향을 주지 않는다.
    """
    if not urls:
        return [], []
    semaphore = asyncio.Semaphore(6)

    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "Mozilla/5.0 stock-news-bot/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
    ) as session:
        async def one(url: str):
            async with semaphore:
                # 같은 시각에 197개 요청이 시작되지 않도록 짧게 분산한다.
                if "news.google.com/rss" in url:
                    await asyncio.sleep(0.05 + (hash(url) % 250) / 1000)
                return await fetch_feed(session, url, timeout_seconds, max_retries)

        results = await asyncio.gather(
            *(one(url) for url in urls),
            return_exceptions=True,
        )

    items: list[NewsItem] = []
    errors: list[FetchError] = []
    for url, result in zip(urls, results):
        if isinstance(result, FetchError):
            errors.append(result)
            logger.warning("RSS 개별 수집 실패(다른 피드는 계속 진행): %s", result)
        elif isinstance(result, Exception):
            err = FetchError(f"'{url}' 수집 실패: {type(result).__name__}: {result}")
            errors.append(err)
            logger.warning("RSS 개별 수집 실패(다른 피드는 계속 진행): %s", err)
        else:
            items.extend(result)
    return items, errors



class FetcherCog(commands.Cog, name="Fetcher"):
    """다른 코그(scheduler)가 호출해서 쓰는 얇은 래퍼.
    자체적으로는 디스코드 명령을 등록하지 않는다."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self._last_dart_fetch_at: datetime | None = None

    async def collect_disclosures(self) -> tuple[list[NewsItem], list[FetchError]]:
        if not getattr(self.settings, "dart_disclosure_enabled", False) or not self.settings.dart_api_key:
            return [], []
        now = datetime.now(timezone.utc)
        interval = max(60, int(getattr(self.settings, "dart_disclosure_fetch_interval_seconds", 300)))
        if self._last_dart_fetch_at and (now - self._last_dart_fetch_at).total_seconds() < interval:
            return [], []
        self._last_dart_fetch_at = now
        client = None
        try:
            client = DartClient(self.settings.db_path)
            start = (now - timedelta(days=1)).astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
            end = now.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
            disclosures = await asyncio.to_thread(
                client.fetch_disclosures,
                self.settings.dart_api_key,
                start_date=start,
                end_date=end,
                max_pages=10,
            )
            items = [
                NewsItem(
                    title=f"{d.corp_name} | {d.report_name}",
                    url=d.url,
                    source="DART",
                    published_at=d.submitted_at,
                    summary=f"DART 공시: {d.report_name}" + (f" | 제출인: {d.flr_nm}" if d.flr_nm else ""),
                    source_kind="dart",
                    company=d.corp_name,
                    score=50,
                )
                for d in disclosures
            ]
            return items, []
        except Exception as exc:
            logger.exception("DART 공시 수집 실패")
            return [], [FetchError(f"DART 공시 수집 실패: {exc}")]
        finally:
            try:
                client.close()
            except Exception:
                pass

    async def collect(self) -> tuple[list[NewsItem], list[FetchError]]:
        urls = self.settings.effective_feed_urls()
        if self.settings.news_keywords:
            unique_count = len(list(dict.fromkeys(self.settings.news_keywords)))
            logger.info(
                "Render NEWS_KEYWORDS 적용: %d개 키워드 → %d개 RSS 검색 피드",
                unique_count, len(urls),
            )
        else:
            logger.info(
                "Render NEWS_KEYWORDS 미설정: RSS_FEEDS %d개를 사용합니다.",
                len(urls),
            )
        if (
            not urls
            and not (self.settings.enable_blog and self.settings.blog_feeds)
            and not (self.settings.enable_youtube and (self.settings.youtube_channel_ids or self.settings.youtube_search_queries))
            and not (self.settings.enable_telegram_channels and self.settings.telegram_source_channels)
        ):
            logger.warning("수집할 RSS/블로그/YouTube/YouTube전체검색/Telegram 소스가 설정되어 있지 않습니다.")
            return [], []
        # 유튜브/텔레그램/블로그 수집 로직은 content_sources.py로 옮겨졌다
        # (관리하기 쉽도록 한 파일에 모음). content_sources.py가 이 파일의
        # fetch_all/_fetch_raw/parse_entries를 가져다 쓰기 때문에 순환
        # 임포트를 피하려고 실제로 쓰는 시점(호출 시)에 임포트한다.
        from stock_news_bot.cogs.content_sources import fetch_source_feeds

        news_items, errors = await fetch_source_feeds(
            urls,
            self.settings.blog_feeds if self.settings.enable_blog else [],
            self.settings.youtube_channel_ids if self.settings.enable_youtube else [],
            self.settings.telegram_source_channels if self.settings.enable_telegram_channels else [],
            youtube_search_queries=self.settings.youtube_search_queries if self.settings.enable_youtube else [],
            youtube_search_max_results=self.settings.youtube_search_max_results,
            youtube_search_interval_seconds=self.settings.youtube_search_interval_seconds,
            blog_search_queries=self.settings.blog_search_queries if self.settings.enable_blog else [],
            telegram_search_queries=self.settings.telegram_search_queries if self.settings.enable_telegram_channels else [],
            blog_search_max_results=self.settings.blog_search_max_results,
            telegram_search_max_results=self.settings.telegram_search_max_results,
            source_search_interval_seconds=self.settings.source_search_interval_seconds,
            timeout_seconds=self.settings.fetch_timeout_seconds,
            max_retries=self.settings.fetch_max_retries,
        )
        dart_items, dart_errors = await self.collect_disclosures()
        return news_items + dart_items, errors + dart_errors


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FetcherCog(bot))


def __getattr__(name: str):
    """호환용: fetch_source_feeds의 실제 정의는 content_sources.py로
    옮겨졌지만, market_briefing.py 등 기존 코드가
    `from stock_news_bot.cogs.fetcher import fetch_source_feeds`로 바로
    가져다 쓰고 있어 그 코드는 건드리지 않고 여기서 그대로 이어준다.
    함수 안에서 지연 임포트하므로(모듈이 로드되는 시점이 아니라 실제로
    이 이름을 쓰는 시점에 resolve됨) content_sources.py와의 순환 임포트
    문제가 생기지 않는다."""
    if name == "fetch_source_feeds":
        from stock_news_bot.cogs.content_sources import fetch_source_feeds
        return fetch_source_feeds
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
