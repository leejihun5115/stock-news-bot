"""RSS 피드 수집.

핵심 설계 원칙:
1. 코어 로직(fetch_feed, parse_entries)은 discord.py에 대해 전혀 모르는
   순수 함수/코루틴으로 만든다 → 디스코드 없이도 단위 테스트 가능.
2. Cog 클래스는 그 순수 함수들을 얇게 감싸는 어댑터 역할만 한다.
3. 피드 하나가 실패해도 나머지 피드 수집은 계속되어야 한다
   (asyncio.gather(..., return_exceptions=True)).
4. 일시적 네트워크 오류는 tenacity로 지수 백오프 재시도.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time
from html import unescape
from datetime import datetime, timezone
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
    """모든 피드를 병렬로 수집한다. 개별 실패는 errors 리스트에 모아서
    반환하고, 성공한 피드의 결과는 items로 합쳐서 반환한다."""
    async with aiohttp.ClientSession(
        headers={"User-Agent": "stock-news-bot/1.0 (+github.com)"}
    ) as session:
        results = await asyncio.gather(
            *(fetch_feed(session, url, timeout_seconds, max_retries) for url in urls),
            return_exceptions=True,
        )

    items: list[NewsItem] = []
    errors: list[FetchError] = []
    for result in results:
        if isinstance(result, FetchError):
            errors.append(result)
        elif isinstance(result, Exception):
            errors.append(FetchError(str(result)))
        else:
            items.extend(result)
    return items, errors


class FetcherCog(commands.Cog, name="Fetcher"):
    """다른 코그(scheduler)가 호출해서 쓰는 얇은 래퍼.
    자체적으로는 디스코드 명령을 등록하지 않는다."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

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
        if not urls:
            logger.warning("수집할 RSS 피드/키워드가 설정되어 있지 않습니다.")
            return [], []
        return await fetch_all(
            urls,
            timeout_seconds=self.settings.fetch_timeout_seconds,
            max_retries=self.settings.fetch_max_retries,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FetcherCog(bot))
