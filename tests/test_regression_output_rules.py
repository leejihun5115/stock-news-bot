from datetime import datetime, timezone

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.cogs.classifier import classify_item
from stock_news_bot.cogs.notifier import build_telegram_text


def _item(title, summary, source="한국경제 | 뉴스 | 증권"):
    return NewsItem(
        title=title, url="https://example.com/article",
        source=source, published_at=datetime(2026, 8, 27, 6, 43, tzinfo=timezone.utc),
        summary=summary,
    )


def test_regression_key_points_are_not_amount_dump_or_title_fragment():
    item = classify_item(_item(
        '"땡큐, 엔비디아"…코스피, 백투백 금리인상에도 1%대 상승',
        "코스피는 6912.37로 1.53% 상승했다. 엔비디아 매출은 962.2억달러로 전년 대비 106% 증가했다.",
    ))
    text = build_telegram_text(item)
    assert '↳ "땡큐' not in text
    assert "금액 — 6912.37" not in text
    assert "금액 — 962.2억달러" not in text


def test_regression_source_is_publisher_only_and_url_is_hidden():
    item = _item("실적 개선", "영업이익이 전년 대비 20% 증가했다.")
    text = build_telegram_text(item)
    assert "📰 [한국경제] _신규_" in text
    assert "한국경제 | 뉴스 | 증권" not in text
    assert '🔗 <a href="https://example.com/article">원문 기사</a>' in text
    assert text.count("https://example.com/article") == 1


def test_regression_no_reason_means_no_related_stock():
    item = _item("삼성전자 주가 급등", "오늘 주가가 올랐다.")
    item.importance = Importance.HIGH
    item.score = 70
    item.key_points = []
    item.analysis = []
    item.related_companies = []
    text = build_telegram_text(item)
    assert "🎯 [관련주]" not in text
