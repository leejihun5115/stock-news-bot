from datetime import datetime, timezone

from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.models import NewsItem


def test_analysis_hides_related_when_no_company():
    item = NewsItem(
        title="시장 전망 업데이트",
        url="https://example.com/a",
        source="테스트",
        published_at=datetime.now(timezone.utc),
        summary="일반적인 시장 전망이다.",
        score=40,
    )
    result = analyze_item(item)
    assert result.related_stocks == []
    assert result.theme is None


def test_analysis_detects_direct_company_event():
    item = NewsItem(
        title="삼성전자, 반도체 공급 계약",
        url="https://example.com/b",
        source="테스트",
        published_at=datetime.now(timezone.utc),
        summary="삼성전자가 500억원 규모 공급 계약을 확정했다.",
        company="삼성전자",
        reason="500억원 규모 공급 계약",
        amounts=["500억원"],
        score=75,
    )
    result = analyze_item(item)
    assert result.related_stocks == ["삼성전자"]
    assert result.theme == "HBM·AI반도체" or result.theme is None
    assert result.strength == "🔥 강함"
