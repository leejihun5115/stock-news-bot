from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stock_news_bot.storage.market_data import MarketDataStore


@pytest.fixture()
def store(tmp_path):
    s = MarketDataStore(tmp_path / "market_data_test.sqlite3")
    yield s
    s.close()


# ── 시가총액 캐시 ──────────────────────────────────────────────────────


def test_get_market_cap_returns_none_when_absent(store):
    assert store.get_market_cap("005930") is None


def test_set_and_get_market_cap_roundtrip(store):
    store.set_market_cap("005930", 400_000_000_000_000, "20260827")
    assert store.get_market_cap("005930") == 400_000_000_000_000


def test_set_market_cap_upserts_on_conflict(store):
    store.set_market_cap("005930", 100, "20260101")
    store.set_market_cap("005930", 200, "20260102")
    assert store.get_market_cap("005930") == 200


# ── 발송 후 주가 반응: 등록 / 기준가 ────────────────────────────────────


def _register(store, dedup_key="k1", stock_code="005930", corp_name="삼성전자",
              sector="반도체", sent_at=None):
    store.register_reaction(
        dedup_key=dedup_key, stock_code=stock_code, corp_name=corp_name,
        sector=sector, sent_at=sent_at or datetime.now(timezone.utc),
    )


def test_register_reaction_is_idempotent(store):
    _register(store, dedup_key="dup")
    _register(store, dedup_key="dup")
    pending = store.pending_base(limit=10)
    assert len(pending) == 1


def test_pending_base_lists_unresolved_records(store):
    _register(store, dedup_key="a")
    _register(store, dedup_key="b")
    pending = store.pending_base(limit=10)
    assert {p.dedup_key for p in pending} == {"a", "b"}


def test_set_base_removes_from_pending_base(store):
    _register(store, dedup_key="a")
    store.set_base("a", base_date="20260827", base_close=70000)
    assert store.pending_base(limit=10) == []


# ── +1 / +3 거래일 반응 ──────────────────────────────────────────────


def test_pending_plus1_only_after_base_set_and_sent_before_threshold(store):
    old_sent = datetime.now(timezone.utc) - timedelta(days=5)
    _register(store, dedup_key="a", sent_at=old_sent)

    # base가 없으면 아직 plus1 대상이 아니다.
    assert store.pending_plus1(min_sent_before=datetime.now(timezone.utc)) == []

    store.set_base("a", base_date="20260820", base_close=70000)
    pending = store.pending_plus1(min_sent_before=datetime.now(timezone.utc))
    assert len(pending) == 1
    assert pending[0].dedup_key == "a"
    assert pending[0].base_close == 70000


def test_pending_plus1_excludes_records_sent_too_recently(store):
    recent_sent = datetime.now(timezone.utc)
    _register(store, dedup_key="a", sent_at=recent_sent)
    store.set_base("a", base_date="20260827", base_close=70000)

    # 기준 시각(threshold)이 발송 시각보다 이전이면 아직 대상이 아니다.
    threshold = datetime.now(timezone.utc) - timedelta(days=3)
    assert store.pending_plus1(min_sent_before=threshold) == []


def test_set_plus1_computes_positive_percentage(store):
    _register(store, dedup_key="a")
    store.set_base("a", base_date="20260820", base_close=70000)
    store.set_plus1("a", date="20260821", close=71400)  # +2%
    row = store._conn.execute(
        "SELECT plus1_pct FROM price_reaction WHERE dedup_key = ?", ("a",)
    ).fetchone()
    assert row[0] == pytest.approx(2.0)


def test_set_plus1_computes_negative_percentage(store):
    _register(store, dedup_key="a")
    store.set_base("a", base_date="20260820", base_close=70000)
    store.set_plus1("a", date="20260821", close=68600)  # -2%
    row = store._conn.execute(
        "SELECT plus1_pct FROM price_reaction WHERE dedup_key = ?", ("a",)
    ).fetchone()
    assert row[0] == pytest.approx(-2.0)


def test_pending_plus3_only_after_plus1_set(store):
    old_sent = datetime.now(timezone.utc) - timedelta(days=10)
    _register(store, dedup_key="a", sent_at=old_sent)
    store.set_base("a", base_date="20260810", base_close=70000)
    assert store.pending_plus3(min_sent_before=datetime.now(timezone.utc)) == []

    store.set_plus1("a", date="20260811", close=70700)
    pending = store.pending_plus3(min_sent_before=datetime.now(timezone.utc))
    assert len(pending) == 1
    assert pending[0].dedup_key == "a"


def test_set_plus3_computes_percentage_relative_to_base(store):
    _register(store, dedup_key="a")
    store.set_base("a", base_date="20260810", base_close=70000)
    store.set_plus1("a", date="20260811", close=70700)
    store.set_plus3("a", date="20260813", close=73500)  # +5% from base
    row = store._conn.execute(
        "SELECT plus3_pct FROM price_reaction WHERE dedup_key = ?", ("a",)
    ).fetchone()
    assert row[0] == pytest.approx(5.0)


# ── 섹터별 통계 ────────────────────────────────────────────────────────


def test_sector_stats_empty_when_no_resolved_records(store):
    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 0
    assert stats.plus1_avg_pct is None
    assert stats.plus3_avg_pct is None


def test_sector_stats_ignores_unresolved_records(store):
    _register(store, dedup_key="a", sector="반도체")
    # base/plus1/plus3 전부 미확정 상태
    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 0


def test_sector_stats_averages_resolved_plus1_values(store):
    _register(store, dedup_key="a", sector="반도체")
    store.set_base("a", base_date="20260820", base_close=100)
    store.set_plus1("a", date="20260821", close=102)  # +2%

    _register(store, dedup_key="b", sector="반도체")
    store.set_base("b", base_date="20260820", base_close=100)
    store.set_plus1("b", date="20260821", close=98)  # -2%

    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 2
    assert stats.plus1_avg_pct == pytest.approx(0.0)
    assert stats.plus1_up_ratio == pytest.approx(50.0)


def test_sector_stats_ignores_other_sectors(store):
    _register(store, dedup_key="a", sector="자동차")
    store.set_base("a", base_date="20260820", base_close=100)
    store.set_plus1("a", date="20260821", close=105)

    stats = store.sector_stats("반도체", lookback_days=30)
    assert stats.count == 0


def test_sector_stats_respects_lookback_window(store):
    old_sent = datetime.now(timezone.utc) - timedelta(days=100)
    _register(store, dedup_key="a", sector="바이오", sent_at=old_sent)
    store.set_base("a", base_date="20260101", base_close=100)
    store.set_plus1("a", date="20260102", close=110)

    stats = store.sector_stats("바이오", lookback_days=30)
    assert stats.count == 0


def test_cleanup_old_removes_expired_rows(store):
    old_sent = datetime.now(timezone.utc) - timedelta(days=200)
    _register(store, dedup_key="a", sector="금융", sent_at=old_sent)

    deleted = store.cleanup_old(retention_days=90)
    assert deleted == 1
    assert store.pending_base(limit=10) == []
