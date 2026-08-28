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


def _parse_published(entry: dict) -> datetime:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    # timezone 정보가 없는 RSS 날짜는 feedparser가 만든
                    # *_parsed(struct_time, UTC 기준) 값을 우선 사용한다.
                    parsed_struct = entry.get(f"{key}_parsed")
                    if parsed_struct:
                        return datetime.fromtimestamp(
                            calendar.timegm(parsed_struct), tz=timezone.utc
                        )
                    # 최후의 fallback: 서버(Render)의 로컬 타임존에 의존하지 않고 UTC로 취급.
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return datetime.now(timezone.utc)


def parse_entries(raw_bytes: bytes, source_hint: str) -> list[NewsItem]:
    """feedparser로 파싱하고 NewsItem 리스트로 변환하는 순수 함수.

    feedparser 자체는 잘못된 XML에도 예외를 던지지 않고 `bozo` 플래그만
    세우는 특이한 라이브러리라, entries가 비어있는데 bozo=1이면 명시적으로
    FetchError로 승격시켜서 상위 로직이 실패를 인지하게 한다.
    """
    parsed = feedparser.parse(raw_bytes)
    if parsed.bozo and not parsed.entries:
        raise FetchError(f"[{source_hint}] 피드 파싱 실패: {parsed.bozo_exception}")

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
        items.append(
            NewsItem(
                title=title,
                url=url,
                source=source,
                published_at=_parse_published(entry),
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
    return parse_entries(raw, source_hint=url)


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
