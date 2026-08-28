from datetime import datetime, timezone

from stock_news_bot.models import NewsItem, Importance
from stock_news_bot.cogs.notifier import build_message, build_telegram_text

def test_title_is_bold_in_discord_and_telegram():
    item = NewsItem(
        title="테스트 제목", url="https://example.com/a", source="한국경제",
        published_at=datetime.now(timezone.utc), summary="", sectors=[],
        score=50, importance=Importance.MEDIUM, dedup_key="x"
    )
    discord = build_message(item)
    telegram = build_telegram_text(item)
    assert "📌 **테스트 제목**" in discord
    assert "📌 <b>테스트 제목</b>" in telegram
