from datetime import datetime, timezone

from stock_news_bot.models import NewsItem, Importance
from stock_news_bot.cogs.notifier import build_message, build_telegram_text, build_telegram_summary_text


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


def test_telegram_summary_is_compact_and_full_text_has_detail():
    """텔레그램 최초 발송(summary)은 헤더/제목/관련주/판정만 담고, 상세 내용은
    안 보인다. 버튼을 눌렀을 때 오는 build_telegram_text()에는 그 상세가 있다."""
    item = _sample_item()
    summary = build_telegram_summary_text(item)
    full = build_telegram_text(item)

    for detail_marker in ("🔎 [핵심]", "🧠 [분석]", "🔮 [전망]", "이유/근거", "판단 조건", "기사 원문 보기"):
        assert detail_marker not in summary

    assert "📊 [매매 포인트]" in summary
    assert "📌 <b>테스트 제목</b>" in summary
    # 상세 메시지에는 매매 포인트의 이유/근거·판단 조건이 들어있어야 한다.
    assert "이유/근거" in full
    assert "판단 조건" in full
