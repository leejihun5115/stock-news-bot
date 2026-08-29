from __future__ import annotations

import pytest

from stock_news_bot.cogs.fetcher import parse_entries
from stock_news_bot.utils.errors import FetchError

_VALID_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 뉴스 피드</title>
    <item>
      <title>삼성전자 3분기 실적 발표</title>
      <link>https://example.com/news/1</link>
      <description>삼성전자가 3분기 실적을 발표했다.</description>
      <pubDate>Mon, 01 Jan 2024 09:00:00 +0900</pubDate>
    </item>
    <item>
      <title>SK하이닉스 신제품 공개</title>
      <link>https://example.com/news/2</link>
      <description>SK하이닉스가 신제품을 공개했다.</description>
      <pubDate>Mon, 01 Jan 2024 10:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")

_MALFORMED_RSS = b"this is not xml at all <<<<"

_EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>빈 피드</title></channel></rss>
""".encode("utf-8")


def test_parse_entries_returns_news_items():
    items = parse_entries(_VALID_RSS, source_hint="test-feed")
    assert len(items) == 2
    assert items[0].title == "삼성전자 3분기 실적 발표"
    assert items[0].url == "https://example.com/news/1"
    assert items[0].source == "테스트 뉴스 피드"


def test_parse_entries_skips_items_missing_title_or_link():
    rss_missing_link = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item><title>링크 없는 기사</title></item>
    </channel></rss>""".encode("utf-8")
    items = parse_entries(rss_missing_link, source_hint="test-feed")
    assert items == []


def test_parse_entries_empty_feed_returns_empty_list():
    # entries가 없지만 정상 XML인 경우는 에러가 아니라 빈 리스트여야 한다.
    items = parse_entries(_EMPTY_RSS, source_hint="test-feed")
    assert items == []


def test_parse_entries_raises_fetch_error_on_malformed_feed():
    with pytest.raises(FetchError):
        parse_entries(_MALFORMED_RSS, source_hint="test-feed")


def test_dedup_key_ignores_query_string():
    from stock_news_bot.models import NewsItem
    from datetime import datetime, timezone

    a = NewsItem(
        title="t", url="https://x.com/a?utm_source=rss", source="s",
        published_at=datetime.now(timezone.utc),
    )
    b = NewsItem(
        title="t", url="https://x.com/a", source="s",
        published_at=datetime.now(timezone.utc),
    )
    assert a.dedup_key == b.dedup_key


def test_parse_published_uses_explicit_timezone_and_not_server_local():
    from datetime import timezone
    from stock_news_bot.cogs.fetcher import _parse_published

    dt = _parse_published({"published": "Fri, 28 Aug 2026 07:00:00 -0400"})
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 11


def test_parse_published_rejects_naive_timestamp():
    from stock_news_bot.cogs.fetcher import _parse_published
    assert _parse_published({"published": "2026-08-28 07:00:00"}) is None
