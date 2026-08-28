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


def test_title_is_bold_in_discord_and_telegram():
    item = _sample_item()
    discord = build_message(item)
    telegram = build_telegram_text(item)
    assert "📌 **테스트 제목**" in discord
    assert "📌 <b>테스트 제목</b>" in telegram


def test_company_name_has_no_quotes_in_header():
    item = _sample_item()
    discord = build_message(item)
    telegram = build_telegram_text(item)
    assert '["시장/테마"]' not in discord
    assert '["시장/테마"]' not in telegram
    assert "[시장/테마]" in discord
    assert "[시장/테마]" in telegram


def test_original_source_link_shown_at_bottom():
    item = _sample_item()
    discord = build_message(item)
    telegram = build_telegram_text(item)
    assert "🔗 [기사 원문 보기](https://example.com/a)" in discord
    assert '🔗 <a href="https://example.com/a">[기사 원문 보기]</a>' in telegram
