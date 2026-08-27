from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stock_news_bot.cogs.notifier import build_cumulative_line
from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.storage.history import HistoryStore


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = HistoryStore(Path(tmp) / "history_test.sqlite3")
        yield s
        s.close()


def _item(title: str, sector: str, score: int, importance: Importance) -> NewsItem:
    item = NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        source="테스트",
        published_at=datetime.now(timezone.utc),
    )
    item.sectors = [sector]
    item.score = score
    item.importance = importance
    return item


def test_sector_stats_empty_returns_zero_count(store):
    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 0
    assert stats.avg_score == 0.0


def test_record_sent_accumulates_into_sector_stats(store):
    store.record_sent(_item("삼성전자 실적발표", "반도체", 70, Importance.HIGH))
    store.record_sent(_item("SK하이닉스 신제품", "반도체", 45, Importance.MEDIUM))
    store.record_sent(_item("LG에너지솔루션 공시", "2차전지", 40, Importance.MEDIUM))

    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 2
    assert stats.high == 1
    assert stats.medium == 1
    assert stats.low == 0
    assert stats.avg_score == pytest.approx((70 + 45) / 2)


def test_sector_stats_ignores_other_sectors(store):
    store.record_sent(_item("자동차 뉴스", "자동차", 50, Importance.MEDIUM))
    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 0


def test_sector_stats_respects_lookback_window(store):
    old_item = _item("옛날 뉴스", "바이오", 60, Importance.MEDIUM)
    store.record_sent(old_item)

    # 과거 시점으로 직접 밀어넣어 lookback 밖으로 보낸다.
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    store._conn.execute(
        "UPDATE sent_history SET sent_at = ? WHERE title = ?", (old_ts, "옛날 뉴스")
    )
    store._conn.commit()

    stats = store.sector_stats("바이오", lookback_days=30)
    assert stats.count == 0


def test_cleanup_old_removes_expired_rows(store):
    item = _item("정리 대상", "금융", 50, Importance.MEDIUM)
    store.record_sent(item)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    store._conn.execute(
        "UPDATE sent_history SET sent_at = ? WHERE title = ?", (old_ts, "정리 대상")
    )
    store._conn.commit()

    deleted = store.cleanup_old(retention_days=90)
    assert deleted == 1
    assert store.sector_stats("금융", lookback_days=365).count == 0


def test_build_cumulative_line_hides_insufficient_sample(store):
    store.record_sent(_item("A", "IT/플랫폼", 40, Importance.MEDIUM))
    stats = store.sector_stats("IT/플랫폼", lookback_days=30)
    assert build_cumulative_line(stats, min_sample=5) is None


def test_build_cumulative_line_reports_full_stats_when_enough_samples(store):
    for i in range(5):
        store.record_sent(_item(f"뉴스{i}", "IT/플랫폼", 50 + i, Importance.MEDIUM))
    stats = store.sector_stats("IT/플랫폼", lookback_days=30)
    line = build_cumulative_line(stats, min_sample=5)
    assert "표본 부족" not in line
    assert "5건" in line
    assert "IT/플랫폼" in line


def test_build_cumulative_line_none_when_no_sector():
    assert build_cumulative_line(None, min_sample=5) is None
