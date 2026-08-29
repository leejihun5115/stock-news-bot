from __future__ import annotations

from datetime import datetime, timezone

from stock_news_bot.cogs import notifier as notifier_mod
from stock_news_bot.cogs.notifier import build_amount_context
from stock_news_bot.models import NewsItem
from stock_news_bot.storage.fundamentals import CompanyFundamentals


def _make_item(**overrides) -> NewsItem:
    item = NewsItem(
        title="삼성전자 영업이익 500억원 증가",
        url="https://example.com/x",
        source="s",
        published_at=datetime.now(timezone.utc),
    )
    item.amounts = ["500억원"]
    item.company = "삼성전자"
    for k, v in overrides.items():
        setattr(item, k, v)
    return item


def test_no_amount_returns_none():
    item = _make_item(amounts=[])
    assert build_amount_context(item) is None


def test_amount_without_fundamentals_states_not_connected(monkeypatch):
    monkeypatch.setattr(notifier_mod, "get_fundamentals", lambda name: None)
    item = _make_item()
    text = build_amount_context(item)
    assert "500억원" in text
    assert "미연동" in text


def test_amount_with_fundamentals_computes_ratio(monkeypatch):
    fundamentals = CompanyFundamentals(
        name="삼성전자",
        market_cap=500_000_000_000_000,  # 500조원
        revenue=300_000_000_000_000,     # 300조원
        operating_profit=50_000_000_000_000,  # 50조원
    )
    monkeypatch.setattr(notifier_mod, "get_fundamentals", lambda name: fundamentals)
    item = _make_item()  # 500억원 = 50,000,000,000원
    text = build_amount_context(item)
    assert "시가총액 대비" in text
    assert "매출액 대비" in text
    assert "영업이익 대비" in text
    # 500억 / 50조 = 0.1%
    assert "0.10%" in text
