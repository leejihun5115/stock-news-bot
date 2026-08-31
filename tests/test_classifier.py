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


def test_classify_low_importance_for_executive_personal_event_without_business_signal():
    """임원 개인의 사고/인도적 활동 등 "동정" 기사는 "긴급" 같은 키워드가
    있어도 사업 재료가 없으면 종목 뉴스로 취급하면 안 된다 (제보: 회장의
    해외 재난 구조활동 기사가 [두산] 긴급 종목 뉴스로 잘못 분류됨)."""
    item = _make_item(
        '박정원 두산 회장 긴급 네팔行, 민간헬기 수색 시도 지속 "직원 구조 총력전"'
    )
    result = classify_item(item)
    assert result.importance == Importance.LOW
    assert result.score == 0


def test_classify_high_importance_when_urgent_business_signal_present():
    """"긴급"이 진짜 사업 재료(수주/계약 등)와 함께 있으면 정상적으로
    높은 중요도로 분류되어야 한다 — 동정 기사 필터가 과도하게 차단하면
    안 된다."""
    item = _make_item("두산에너빌리티, 원전 기자재 500억원 규모 긴급 수주 계약 체결")
    result = classify_item(item)
    assert result.importance == Importance.HIGH
