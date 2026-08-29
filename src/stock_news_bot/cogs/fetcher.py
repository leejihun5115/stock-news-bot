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
from urllib.parse import quote_plus

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




_YOUTUBE_ID_CACHE: dict[str, tuple[str, float]] = {}

def _resolve_youtube_channel_id(value: str, timeout_seconds: int = 10) -> str:
    """UC ID뿐 아니라 예전 버전에서 사용하던 @핸들/핸들명도 UC ID로 해석한다."""
    value = (value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", value):
        return value
    key = value.lstrip("@").strip()
    cached = _YOUTUBE_ID_CACHE.get(key)
    if cached and time.time() - cached[1] < 86400:
        return cached[0]
    urls = (
        f"https://www.youtube.com/@{key}",
        f"https://www.youtube.com/@{key}/videos",
        f"https://www.youtube.com/c/{key}",
        f"https://www.youtube.com/user/{key}",
    )
    patterns = (
        r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"browseId":"(UC[A-Za-z0-9_-]{20,})"',
        r'/channel/(UC[A-Za-z0-9_-]{20,})',
    )
    import requests
    headers = {"User-Agent": "Mozilla/5.0 stock-news-bot/1.0"}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=min(timeout_seconds, 10), allow_redirects=True)
            if not resp.ok:
                continue
            body = resp.text or ""
            for pattern in patterns:
                m = re.search(pattern, body, flags=re.I)
                if m:
                    cid = m.group(1)
                    _YOUTUBE_ID_CACHE[key] = (cid, time.time())
                    return cid
        except Exception:
            continue
    return ""

def _youtube_feed_urls(channel_ids: list[str], timeout_seconds: int = 10) -> list[tuple[str, str]]:
    """YouTube RSS URL을 만든다.

    채널 ID가 오래되어 RSS가 404가 되는 경우를 줄이기 위해 핸들/채널명도
    그대로 보존한다. 실제 RSS 요청은 이후 단계에서 404 시 페이지 방식으로
    재시도할 수 있도록 tuple에 원래 값과 URL을 함께 둔다.
    """
    urls: list[tuple[str, str]] = []
    for channel in channel_ids:
        channel = channel.strip()
        if not channel:
            continue
        cid = _resolve_youtube_channel_id(channel, timeout_seconds)
        if cid:
            urls.append((channel.lstrip("@"), f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
        else:
            # ID 해석이 실패해도 핸들 자체를 보존하여 HTML fallback이 시도되도록 한다.
            urls.append((channel.lstrip("@"), ""))
            logger.warning("YouTube 채널 ID 해석 실패: %s — 페이지 방식으로 재시도합니다.", channel)
    return urls


async def _fetch_youtube_page(
    session: aiohttp.ClientSession, channel: str, timeout_seconds: int = 10, max_items: int = 10
) -> list[NewsItem]:
    """YouTube RSS가 404/실패할 때 채널 /videos HTML에서 최신 영상을 복구한다."""
    name = channel.strip().lstrip("@")
    if not name:
        return []
    urls = [f"https://www.youtube.com/@{name}/videos", f"https://www.youtube.com/c/{name}/videos"]
    html = ""
    for url in urls:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                         "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"},
            ) as resp:
                if resp.status == 200:
                    html = await resp.text(errors="replace")
                    break
        except Exception:
            continue
    if not html:
        return []

    # ytInitialData/videoRenderer에 들어 있는 videoId와 title을 추출한다.
    pairs: list[tuple[str, str]] = []
    renderer_re = re.compile(
        r'"videoId":"([A-Za-z0-9_-]{11})".{0,1200}?"title":\{"runs":\[\{"text":"(.*?)"', re.S
    )
    seen: set[str] = set()
    for m in renderer_re.finditer(html):
        vid, raw_title = m.group(1), m.group(2)
        if vid in seen:
            continue
        seen.add(vid)
        title = bytes(raw_title, "utf-8").decode("unicode_escape", errors="ignore")
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            pairs.append((vid, title))
        if len(pairs) >= max_items:
            break

    now = datetime.now(timezone.utc)
    return [
        NewsItem(
            title=title[:500],
            url=f"https://www.youtube.com/watch?v={vid}",
            source=f"YouTube {name}",
            published_at=now,
            summary=title[:1000],
            source_kind="youtube",
        )
        for vid, title in pairs
    ]


_YOUTUBE_SEARCH_LAST_RUN = 0.0


def _youtube_search_relative_time(text: str, now: datetime | None = None) -> datetime:
    """YouTube 검색결과의 '3시간 전/1일 전' 표기를 UTC 시각으로 복원한다.

    정확한 시각이 응답에 없을 때는 검색 시각을 사용한다. 이 경우에도
    scheduler의 최근시간/중복 게이트가 최종 송출을 통제한다.
    """
    now = now or datetime.now(timezone.utc)
    raw = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not raw:
        return now
    m = re.search(r"(\d+)\s*(초|분|시간|일|주|개월|년)", raw)
    if not m:
        # 영어 YouTube UI가 내려오는 경우도 지원
        m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?", raw)
        if not m:
            return now
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ("초", "second"):
        from datetime import timedelta
        return now - timedelta(seconds=n)
    if unit in ("분", "minute"):
        from datetime import timedelta
        return now - timedelta(minutes=n)
    if unit in ("시간", "hour"):
        from datetime import timedelta
        return now - timedelta(hours=n)
    if unit in ("일", "day"):
        from datetime import timedelta
        return now - timedelta(days=n)
    if unit in ("주", "week"):
        from datetime import timedelta
        return now - timedelta(weeks=n)
    if unit in ("개월", "month"):
        from datetime import timedelta
        return now - timedelta(days=n * 30)
    if unit in ("년", "year"):
        from datetime import timedelta
        return now - timedelta(days=n * 365)
    return now


def _youtube_decode_json_text(value: str) -> str:
    """YouTube inline JSON 문자열을 안전하게 사람이 읽는 문자열로 복원한다."""
    value = unescape(value or "")
    try:
        # json.loads를 쓰면 \\uXXXX, escaped quote 등을 정상적으로 처리할 수 있다.
        import json
        return str(json.loads('"' + value + '"'))
    except Exception:
        try:
            return bytes(value, "utf-8").decode("unicode_escape", errors="ignore")
        except Exception:
            return value


def _youtube_search_extract(html: str, query: str, max_items: int) -> list[NewsItem]:
    """YouTube 검색 HTML의 ytInitialData/videoRenderer에서 결과를 추출한다.

    YouTube가 HTML 구조를 바꾸더라도 videoRenderer 단위의 핵심 필드만 찾도록
    범위를 제한한다. 검색결과는 특정 채널 목록과 무관한 '전체 YouTube 검색'이다.
    """
    results: list[NewsItem] = []
    seen: set[str] = set()
    if not html:
        return results

    # videoRenderer 하나를 통째로 JSON으로 파싱하는 방식은 YouTube의 큰 inline
    # JSON 때문에 취약할 수 있어, 핵심 필드 사이의 거리만 제한한 정규식으로 복구한다.
    # 각 videoId를 경계로 잘라내면 YouTube가 renderer 사이에 다른 객체를 끼워도
    # 특정 영상의 title/채널/게시시각을 같은 블록에서 안전하게 찾을 수 있다.
    id_matches = list(re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', html))
    blocks = []
    for idx, match in enumerate(id_matches):
        end = id_matches[idx + 1].start() if idx + 1 < len(id_matches) else min(len(html), match.start() + 12000)
        blocks.append(html[match.start():end])

    for block in blocks:
        m_id = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', block)
        if not m_id:
            continue
        vid = m_id.group(1)
        if vid in seen:
            continue

        m_title = re.search(r'"title":\{"runs":\[\{"text":"((?:\\.|[^"\\])*)"', block)
        if not m_title:
            m_title = re.search(r'"title":\{"simpleText":"((?:\\.|[^"\\])*)"', block)
        title = _youtube_decode_json_text(m_title.group(1)) if m_title else ""
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        m_channel = re.search(r'"ownerText":\{"runs":\[\{"text":"((?:\\.|[^"\\])*)"', block)
        channel_name = _youtube_decode_json_text(m_channel.group(1)) if m_channel else ""
        m_published = re.search(r'"publishedTimeText":\{"simpleText":"((?:\\.|[^"\\])*)"', block)
        published_text = _youtube_decode_json_text(m_published.group(1)) if m_published else ""
        published = _youtube_search_relative_time(published_text)

        seen.add(vid)
        summary = f"채널: {channel_name} | 검색어: {query}" if channel_name else f"검색어: {query}"
        results.append(
            NewsItem(
                title=title[:500],
                url=f"https://www.youtube.com/watch?v={vid}",
                source=f"YouTube 검색 | {query}",
                published_at=published,
                summary=summary,
                source_kind="youtube",
            )
        )
        if len(results) >= max_items:
            break
    return results


async def _fetch_youtube_search(
    session: aiohttp.ClientSession,
    query: str,
    timeout_seconds: int = 10,
    max_items: int = 10,
) -> list[NewsItem]:
    """등록된 검색어로 YouTube 전체를 검색한다. 채널 제한은 적용하지 않는다."""
    query = str(query or "").strip()
    if not query:
        return []
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&hl=ko&gl=KR"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36 stock-news-bot/1.0",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_seconds), headers=headers) as resp:
            if resp.status != 200:
                raise FetchError(f"YouTube 전체검색 HTTP {resp.status}: {query}")
            html = await resp.text(errors="replace")
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"YouTube 전체검색 실패 '{query}': {exc}") from exc

    items = _youtube_search_extract(html, query, max_items)
    if not items:
        logger.warning("YouTube 전체검색 결과 없음: %s", query)
    else:
        logger.info("🔎 YouTube 전체검색: %s → %d건", query, len(items))
    return items


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

    # Telegram HTML은 중첩 div 구조가 자주 바뀌므로 특정 닫힘 태그 수에
    # 의존하지 않고 게시물 링크(data-post / tgme_widget_message_date)를
    # 기준으로 주변 블록을 잘라낸다.
    import html as html_module
    from urllib.parse import urljoin
    marker_re = re.compile(r'<div[^>]+class="[^"]*tgme_widget_message_wrap[^"]*"[^>]*>', re.I)
    markers = list(marker_re.finditer(html))
    if not markers:
        # 일부 응답은 wrapper class가 축약되어 있으므로 post 링크 자체를 기준으로
        # 전체 HTML에서 직접 복구한다.
        markers = [m for m in re.finditer(r'data-post="([^"]+/\d+)"', html, re.I)]

    items: list[NewsItem] = []
    for i, marker in enumerate(markers):
        if marker_re.pattern and marker_re.search(html, marker.start()):
            block_end = markers[i + 1].start() if i + 1 < len(markers) else min(len(html), marker.start() + 50000)
            block = html[marker.start():block_end]
        else:
            block = html[max(0, marker.start()-10000):min(len(html), marker.start()+20000)]

        mpost = re.search(r'(?:data-post="|href="https://t\.me/)([A-Za-z0-9_]+/\d+)', block, re.I)
        if not mpost:
            continue
        link = "https://t.me/" + mpost.group(1)
        mtime = re.search(r'<time[^>]+datetime="([^"]+)"[^>]*>', block, re.I)
        raw_time = html_module.unescape(mtime.group(1)).strip() if mtime else ""
        try:
            published = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(timezone.utc) if raw_time else datetime.now(timezone.utc)
        except ValueError:
            published = datetime.now(timezone.utc)
        title_re = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S | re.I)
        mtitle = title_re.search(block)
        title_html = mtitle.group(1) if mtitle else ""
        title = unescape(re.sub(r"<[^>]+>", " ", title_html))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            title = f"Telegram @{name} 게시물"
        items.append(NewsItem(title=title[:500], url=urljoin("https://t.me/", link), source=f"Telegram @{name}", published_at=published, summary=title[:1000], source_kind="telegram"))

    # 같은 게시물이 두 패턴에 잡힐 수 있으므로 URL 기준 중복 제거
    dedup: dict[str, NewsItem] = {}
    for item in items:
        dedup[item.url] = item
    items = list(dedup.values())[-20:]
    if not items:
        logger.warning("Telegram 공개 채널에서 게시물을 찾지 못했습니다: @%s", name)
    return items



_SOURCE_SEARCH_LAST_RUN = 0.0


async def _fetch_google_news_site_search(
    session: aiohttp.ClientSession,
    query: str,
    site: str,
    source_kind: str,
    source_label: str,
    timeout_seconds: int = 10,
    max_items: int = 10,
) -> list[NewsItem]:
    """등록 채널과 별개로 특정 공개 소스 영역을 검색한다.

    검색어가 비어 있을 때는 호출하지 않는다. 실제 검색은 Google News RSS의
    site: 연산자를 사용해 구현하므로 별도 API 키가 필요 없다. 나중에
    BLOG_SEARCH_QUERIES / TELEGRAM_SEARCH_QUERIES에 종목명·재료를 넣으면
    등록된 피드와 독립적으로 검색 결과가 파이프라인에 들어온다.
    """
    query = str(query or "").strip()
    if not query:
        return []
    from urllib.parse import quote
    search_query = f"site:{site} {query}"
    url = f"https://news.google.com/rss/search?q={quote(search_query)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        raw = await _fetch_raw(session, url, timeout_seconds, 1)
        items = parse_entries(raw, source_hint=url)
    except Exception as exc:
        raise FetchError(f"{source_label} 전체검색 실패 '{query}': {exc}") from exc

    results: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        if item.dedup_key in seen:
            continue
        seen.add(item.dedup_key)
        item.source_kind = source_kind
        item.source = f"{source_label} 검색 | {query}"
        results.append(item)
        if len(results) >= max_items:
            break
    if results:
        logger.info("🔎 %s 전체검색: %s → %d건", source_label, query, len(results))
    else:
        logger.info("🔎 %s 전체검색 결과 없음: %s", source_label, query)
    return results


async def fetch_source_feeds(
    urls: list[str], blog_feeds: list[str], youtube_channel_ids: list[str], telegram_channels: list[str],
    youtube_search_queries: list[str] | None = None,
    youtube_search_max_results: int = 10,
    youtube_search_interval_seconds: int = 60,
    blog_search_queries: list[str] | None = None,
    telegram_search_queries: list[str] | None = None,
    blog_search_max_results: int = 10,
    telegram_search_max_results: int = 10,
    source_search_interval_seconds: int = 60,
    timeout_seconds: int = 10, max_retries: int = 3,
) -> tuple[list[NewsItem], list[FetchError]]:
    """RSS/블로그/YouTube/공개 Telegram을 한 번에 수집한다."""
    youtube_urls = _youtube_feed_urls(youtube_channel_ids, timeout_seconds)
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
        for item in blog_items:
            item.source_kind = "blog"
        items.extend(blog_items)
        errors.extend(blog_errors)
        logger.info("📝 블로그 RSS 수집: %d개 피드 URL → %d건 수집(오류 %d건)", len(blog_urls), len(blog_items), len(blog_errors))

    if youtube_urls:
        yt_items: list[NewsItem] = []
        yt_errors: list[FetchError] = []
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 stock-news-bot/1.0", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}) as session:
            for channel_name, feed_url in youtube_urls:
                channel_items: list[NewsItem] = []
                if feed_url:
                    channel_items, channel_errors = await fetch_all([feed_url], timeout_seconds, max_retries)
                    yt_errors.extend(channel_errors)
                if not channel_items:
                    channel_items = await _fetch_youtube_page(session, channel_name, timeout_seconds)
                    if channel_items:
                        logger.info("📺 YouTube 페이지 fallback 성공: %s → %d건", channel_name, len(channel_items))
                for item in channel_items:
                    item.source_kind = "youtube"
                    item.source = f"YouTube {channel_name}"
                yt_items.extend(channel_items)
        items.extend(yt_items)
        errors.extend(yt_errors)
        logger.info("📺 YouTube 수집: %d개 채널 → %d건 수집(오류 %d건)", len(youtube_urls), len(yt_items), len(yt_errors))

    # 전체 YouTube 검색은 별도 주기로 실행한다. 검색어가 비어 있으면 아무 요청도
    # 보내지 않으므로, 사용자는 프로그램을 먼저 안정적으로 띄운 뒤 나중에
    # Render의 YOUTUBE_SEARCH_QUERIES만 추가하면 된다.
    global _YOUTUBE_SEARCH_LAST_RUN, _SOURCE_SEARCH_LAST_RUN
    search_queries = [str(q).strip() for q in (youtube_search_queries or []) if str(q).strip()]
    blog_searches = [str(q).strip() for q in (blog_search_queries or []) if str(q).strip()]
    telegram_searches = [str(q).strip() for q in (telegram_search_queries or []) if str(q).strip()]
    now_ts = time.time()
    yt_due = bool(search_queries) and (now_ts - _YOUTUBE_SEARCH_LAST_RUN >= max(60, int(youtube_search_interval_seconds)))
    source_due = bool(blog_searches or telegram_searches) and (now_ts - _SOURCE_SEARCH_LAST_RUN >= max(60, int(source_search_interval_seconds)))
    if yt_due:
        _YOUTUBE_SEARCH_LAST_RUN = now_ts
        search_items: list[NewsItem] = []
        search_errors: list[FetchError] = []
        async with aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 stock-news-bot/1.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        }) as session:
            results = await asyncio.gather(
                *(_fetch_youtube_search(session, q, timeout_seconds, youtube_search_max_results) for q in search_queries),
                return_exceptions=True,
            )
        for q, result in zip(search_queries, results):
            if isinstance(result, FetchError):
                search_errors.append(result)
                logger.warning("🔎 YouTube 전체검색 실패: %s — %s", q, result)
            elif isinstance(result, Exception):
                err = FetchError(str(result))
                search_errors.append(err)
                logger.warning("🔎 YouTube 전체검색 실패: %s — %s", q, err)
            else:
                search_items.extend(result)
        items.extend(search_items)
        errors.extend(search_errors)
        logger.info("🔎 YouTube 전체검색 완료: 검색어=%d개 → %d건 수집(오류 %d건)", len(search_queries), len(search_items), len(search_errors))
    elif search_queries:
        remaining = max(0, int(youtube_search_interval_seconds - (now_ts - _YOUTUBE_SEARCH_LAST_RUN)))
        logger.debug("🔎 YouTube 전체검색 대기중: 다음 검색까지 약 %ss", remaining)

    # 블로그/텔레그램 전체 검색은 검색어가 생기기 전까지 완전히 비활성화한다.
    # 검색어를 나중에 Render 환경변수에 넣으면 1분 주기로 자동 실행된다.
    if source_due:
        _SOURCE_SEARCH_LAST_RUN = now_ts
        search_errors: list[FetchError] = []
        search_items: list[NewsItem] = []
        async with aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 stock-news-bot/1.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }) as session:
            tasks = []
            labels = []
            for q in blog_searches:
                tasks.append(_fetch_google_news_site_search(session, q, "blog.naver.com", "blog", "블로그", timeout_seconds, blog_search_max_results))
                labels.append(("블로그", q))
            for q in telegram_searches:
                tasks.append(_fetch_google_news_site_search(session, q, "t.me", "telegram", "Telegram", timeout_seconds, telegram_search_max_results))
                labels.append(("Telegram", q))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for (label, q), result in zip(labels, results):
            if isinstance(result, Exception):
                err = result if isinstance(result, FetchError) else FetchError(str(result))
                search_errors.append(err)
                logger.warning("🔎 %s 전체검색 실패: %s — %s", label, q, err)
            else:
                search_items.extend(result)
        items.extend(search_items)
        errors.extend(search_errors)
        logger.info("🔎 소스 전체검색 완료: 블로그=%d개 검색어 / Telegram=%d개 검색어 → %d건", len(blog_searches), len(telegram_searches), len(search_items))
    elif blog_searches or telegram_searches:
        remaining = max(0, int(source_search_interval_seconds - (now_ts - _SOURCE_SEARCH_LAST_RUN)))
        logger.debug("🔎 블로그/Telegram 전체검색 대기중: 다음 검색까지 약 %ss", remaining)

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
        if (
            not urls
            and not (self.settings.enable_blog and self.settings.blog_feeds)
            and not (self.settings.enable_youtube and (self.settings.youtube_channel_ids or self.settings.youtube_search_queries))
            and not (self.settings.enable_telegram_channels and self.settings.telegram_source_channels)
        ):
            logger.warning("수집할 RSS/블로그/YouTube/YouTube전체검색/Telegram 소스가 설정되어 있지 않습니다.")
            return [], []
        return await fetch_source_feeds(
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FetcherCog(bot))
