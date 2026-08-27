from __future__ import annotations

from datetime import datetime, timezone

from stock_news_bot.cogs.classifier import classify_item, is_noise
from stock_news_bot.models import Importance, NewsItem


def _make_item(title: str, summary: str = "") -> NewsItem:
    return NewsItem(
        title=title, url="https://example.com/x", source="s",
        published_at=datetime.now(timezone.utc), summary=summary,
    )


def test_classify_high_importance_on_urgent_keyword():
    item = _make_item("삼성전자 주가 급등, 반도체 훈풍")
    result = classify_item(item)
    assert result.importance == Importance.HIGH
    assert "반도체" in result.sectors


def test_classify_medium_importance_when_sector_matched_only():
    item = _make_item("SK하이닉스, 신규 라인 증설 계획 발표")
    result = classify_item(item)
    assert result.importance in (Importance.MEDIUM, Importance.HIGH)
    assert "반도체" in result.sectors


def test_classify_low_importance_when_no_keywords_match():
    item = _make_item("오늘의 날씨는 맑음")
    result = classify_item(item)
    assert result.importance == Importance.LOW
    assert result.sectors == []


def test_is_noise_filters_short_titles():
    assert is_noise(_make_item("단신"))
    assert not is_noise(_make_item("정상적인 길이의 뉴스 제목입니다"))


def test_is_noise_filters_photo_tag_titles():
    assert is_noise(_make_item("[포토] 여의도 증권가 풍경"))
