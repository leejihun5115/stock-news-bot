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




def _youtube_feed_urls(channel_ids: list[str]) -> list[str]:
    urls = []
    for channel_id in channel_ids:
        channel_id = channel_id.strip()
        if not channel_id:
            continue
        if channel_id.startswith("UC"):
            urls.append(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        else:
            logger.warning("YouTube 채널 ID가 UC로 시작하지 않아 제외합니다: %s", channel_id)
    return urls


async def _fetch_telegram_channel(
    session: aiohttp.ClientSession, channel: str, timeout_seconds: int = 10
) -> list[NewsItem]:
    """공개 Telegram 채널(t.me/s/<channel>)의 최신 게시물을 수집한다.

    Telegram Bot API의 getUpdates는 '봇에게 들어오는 업데이트' 용도라 채널
    원문 수집에 사용할 수 없다. 공개 채널은 웹 미리보기 페이지에서 게시물
    링크와 datetime을 읽는다. 비공개 채널은 이 방식으로 접근할 수 없으므로
    명시적으로 오류를 반환하고 전체 수집기는 계속 진행한다.
    """
    name = channel.strip().lstrip("@").strip("/")
    if name.startswith("https://t.me/"):
        name = name.split("https://t.me/", 1)[1].split("/", 1)[0]
    elif name.startswith("http://t.me/"):
        name = name.split("http://t.me/", 1)[1].split("/", 1)[0]
    if not name or name.startswith("+"):
        raise FetchError(f"Telegram 공개 채널 형식이 아닙니다: {channel}")

    url = f"https://t.me/s/{name}"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            headers={"Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0 stock-news-bot/1.0"},
        ) as resp:
            if resp.status != 200:
                raise FetchError(f"Telegram 채널 HTTP {resp.status}: @{name}")
            html = await resp.text(errors="replace")
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"Telegram 채널 수집 실패 @{name}: {exc}") from exc

    # 게시물 블록에서 post 링크와 time datetime을 함께 찾는다. Telegram의
    # 공개 웹페이지는 이 구조를 장기간 유지해왔으며, 구조가 바뀌면 해당
    # 채널만 실패하고 RSS/YouTube/블로그는 계속 수집된다.
    import html as html_module
    from urllib.parse import urljoin
    block_re = re.compile(
        r'<div[^>]+class="[^"]*tgme_widget_message_wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        re.S | re.I,
    )
    time_re = re.compile(r'<time[^>]+datetime="([^"]+)"[^>]*>', re.I)
    post_re = re.compile(r'href="(https://t\.me/[^"/?]+/(\d+))"[^>]*class="[^"]*tgme_widget_message_date', re.I)
    title_re = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S | re.I)
    items: list[NewsItem] = []
    for block in block_re.findall(html):
        mpost = post_re.search(block)
        if not mpost:
            continue
        mtime = time_re.search(block)
        if not mtime:
            continue
        raw_time = html_module.unescape(mtime.group(1)).strip()
        try:
            published = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        mtitle = title_re.search(block)
        title_html = mtitle.group(1) if mtitle else ""
        title = unescape(re.sub(r"<[^>]+>", " ", title_html))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            title = f"Telegram @{name} 게시물"
        link = mpost.group(1)
        items.append(NewsItem(title=title[:500], url=urljoin("https://t.me/", link), source=f"Telegram @{name}", published_at=published, summary=title[:1000]))
    if not items:
        logger.warning("Telegram 공개 채널에서 게시물을 찾지 못했습니다: @%s", name)
    return items


async def fetch_source_feeds(
    urls: list[str], blog_feeds: list[str], youtube_channel_ids: list[str], telegram_channels: list[str],
    timeout_seconds: int = 10, max_retries: int = 3,
) -> tuple[list[NewsItem], list[FetchError]]:
    """RSS/블로그/YouTube/공개 Telegram을 한 번에 수집한다."""
    youtube_urls = _youtube_feed_urls(youtube_channel_ids)
    # 키워드/RSS_FEEDS와 블로그/유튜브를 하나로 합쳐서 fetch_all에 넘기면 실제
    # 수집이 되는지는 알 수 있어도 "블로그만 몇 건, 유튜브만 몇 건"인지는 알
    # 수 없다. 진단을 위해 블로그/유튜브는 따로 fetch해서 소스별 건수를
    # 남긴다(요청 URL 목록 자체는 그대로 세마포어로 제한된 fetch_all을 쓰므로
    # 동시성 동작은 이전과 동일하다).
    other_urls = list(dict.fromkeys(urls))
    other_items, other_errors = await fetch_all(other_urls, timeout_seconds, max_retries) if other_urls else ([], [])

    items = list(other_items)
    errors = list(other_errors)

    if blog_feeds:
        blog_urls = list(dict.fromkeys(blog_feeds))
        blog_items, blog_errors = await fetch_all(blog_urls, timeout_seconds, max_retries)
        items.extend(blog_items)
        errors.extend(blog_errors)
        logger.info("📝 블로그 RSS 수집: %d개 피드 URL → %d건 수집(오류 %d건)", len(blog_urls), len(blog_items), len(blog_errors))

    if youtube_channel_ids:
        if len(youtube_urls) < len(youtube_channel_ids):
            logger.warning(
                "⚠️ YOUTUBE_CHANNEL_IDS 중 %d개가 'UC'로 시작하지 않아 제외되었습니다. "
                "채널 URL이 아니라 반드시 채널 ID(UC로 시작)를 넣어야 합니다.",
                len(youtube_channel_ids) - len(youtube_urls),
            )
        if youtube_urls:
            yt_items, yt_errors = await fetch_all(youtube_urls, timeout_seconds, max_retries)
            items.extend(yt_items)
            errors.extend(yt_errors)
            logger.info("📺 YouTube 수집: %d개 채널 → %d건 수집(오류 %d건)", len(youtube_urls), len(yt_items), len(yt_errors))

    if telegram_channels:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 stock-news-bot/1.0"}) as session:
            results = await asyncio.gather(
                *(_fetch_telegram_channel(session, ch, timeout_seconds) for ch in telegram_channels),
                return_exceptions=True,
            )
        telegram_item_count = 0
        for ch, result in zip(telegram_channels, results):
            if isinstance(result, FetchError):
                errors.append(result)
                logger.warning("✈️ Telegram 채널 수집 실패: %s — %s", ch, result)
            elif isinstance(result, Exception):
                err = FetchError(str(result))
                errors.append(err)
                logger.warning("✈️ Telegram 채널 수집 실패: %s — %s", ch, err)
            else:
                items.extend(result)
                telegram_item_count += len(result)
                logger.info("✈️ Telegram 채널 수집: @%s → %d건", ch.strip().lstrip('@'), len(result))
        logger.info("✈️ Telegram 전체 수집: %d개 채널에서 %d건", len(telegram_channels), telegram_item_count)

    # URL dedup: 여러 키워드/피드에서 같은 기사·영상이 반복되는 것을 수집 단계에서 줄인다.
    unique: dict[str, NewsItem] = {}
    for item in items:
        unique.setdefault(item.dedup_key, item)
    return list(unique.values()), errors


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
        if not urls and not self.settings.blog_feeds and not self.settings.youtube_channel_ids and not self.settings.telegram_source_channels:
            logger.warning("수집할 RSS/블로그/YouTube/Telegram 소스가 설정되어 있지 않습니다.")
            return [], []
        return await fetch_source_feeds(
            urls,
            self.settings.blog_feeds,
            self.settings.youtube_channel_ids,
            self.settings.telegram_source_channels,
            timeout_seconds=self.settings.fetch_timeout_seconds,
            max_retries=self.settings.fetch_max_retries,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FetcherCog(bot))
