from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stock_news_bot.cogs.classifier import (
    ClassifierCog,
    classify_item,
    extract_amounts,
    extract_company_name,
    extract_reason,
)
from stock_news_bot.models import NewsItem
from types import SimpleNamespace


def _make_item(title: str, summary: str = "") -> NewsItem:
    return NewsItem(
        title=title, url="https://example.com/x", source="s",
        published_at=datetime.now(timezone.utc), summary=summary,
    )


# ── extract_reason ────────────────────────────────────────────────────

def test_extract_reason_finds_percent_context():
    reason = extract_reason("영업이익이 전년 동기 대비 42% 증가했다는 소식에 급등했다.")
    assert "42%" in reason


def test_extract_reason_finds_material_keyword_context():
    reason = extract_reason("대규모 수주 소식에 강세를 보였다.")
    assert "수주" in reason


def test_extract_reason_empty_when_nothing_found():
    assert extract_reason("주가 급등, 투자자 관심 집중") == ""


# ── extract_amounts ───────────────────────────────────────────────────

def test_extract_amounts_finds_multiple_won_values():
    amounts = extract_amounts("영업이익 500억원, 매출액 1조 2000억원 기록")
    assert "500억원" in amounts
    assert any("억원" in a for a in amounts)


def test_extract_amounts_empty_when_no_amount():
    assert extract_amounts("주가가 급등했다") == []


# ── extract_company_name ────────────────────────────────────────────

def test_extract_company_name_found():
    assert extract_company_name("삼성전자 영업이익 급증") == "삼성전자"


def test_extract_company_name_not_found():
    assert extract_company_name("어느 중소형주 급등") == ""


# ── classify_item: 절대 제외하지 않고, 필드만 채운다 ────────────────────

def test_classify_item_never_drops_news_even_without_reason():
    item = classify_item(_make_item("삼성전자 주가 급등", "오늘 주가가 크게 올랐다."))
    # 제외되지 않고 그대로 반환됨. 대신 reason이 비어있어야 한다.
    assert item.title == "삼성전자 주가 급등"
    assert item.reason == ""


def test_classify_item_fills_reason_when_present():
    item = classify_item(
        _make_item("삼성전자 주가 급등", "영업이익이 전년 동기 대비 42% 증가했다는 소식에 급등했다.")
    )
    assert "42%" in item.reason


def test_classify_item_fills_amounts_and_company():
    item = classify_item(
        _make_item("삼성전자 영업이익 500억원 증가", "삼성전자가 영업이익 500억원 증가를 발표했다.")
    )
    assert "500억원" in item.amounts
    assert item.company == "삼성전자"


def test_classifier_cog_does_not_filter_evidence_lacking_items():
    """예전엔 근거 없으면 제외했지만, 지금은 절대 제외하면 안 된다."""
    settings = SimpleNamespace(news_value_mid=40, news_value_high=70)
    cog = ClassifierCog(SimpleNamespace(settings=settings))
    items = [
        _make_item("삼성전자 주가 급등", "오늘 주가가 크게 올랐다."),  # 근거 없음이지만 통과해야 함
    ]
    result = cog.classify(items)
    assert len(result) == 1
    assert result[0].reason == ""
