from datetime import datetime, timezone

from stock_news_bot.models import NewsItem, Importance
from stock_news_bot.cogs.notifier import build_message, build_telegram_text


def _sample_item(**overrides):
    defaults = dict(
        title="테스트 제목", url="https://example.com/a", source="한국경제",
        published_at=datetime.now(timezone.utc), summary="", sectors=[],
        score=50, importance=Importance.MEDIUM,
    )
    defaults.update(overrides)
    return NewsItem(**defaults)


def test_message_is_compact_and_hides_details_behind_header_link():
    """상세 내용(핵심/분석/테마/전망/일정/용어)은 노출하지 않고,
    헤더 / 관련주 / 매매 포인트 3블록만 보여준다. 헤더는 원문 링크로 감싼다."""
    item = _sample_item()
    discord = build_message(item)
    telegram = build_telegram_text(item)

    for text in (discord, telegram):
        assert "🔎 [핵심]" not in text
        assert "🧠 [분석]" not in text
        assert "🔮 [전망]" not in text
        assert "📅 [일정]" not in text
        assert "💡 [용어]" not in text
        assert "📊 [매매 포인트]" in text

    assert "[📰 [시장/테마]" in discord and "(https://example.com/a)" in discord
    assert '<a href="https://example.com/a">📰 [시장/테마]' in telegram


def test_company_name_has_no_quotes_in_header():
    item = _sample_item()
    discord = build_message(item)
    telegram = build_telegram_text(item)
    assert '["시장/테마"]' not in discord
    assert '["시장/테마"]' not in telegram
    assert "[시장/테마]" in discord
    assert "[시장/테마]" in telegram
