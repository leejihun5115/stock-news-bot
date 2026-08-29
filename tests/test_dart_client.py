from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from stock_news_bot.storage.dart_client import (
    CompanyFinancials,
    DartClient,
)


@pytest.fixture()
def client(tmp_path):
    c = DartClient(tmp_path / "dart_test.sqlite3")
    yield c
    c.close()


def _seed_corp_codes(client: DartClient, rows: list[tuple[str, str, str]]) -> None:
    """테스트용으로 refresh_corp_codes()를 거치지 않고 직접 캐시 테이블을 채운다.

    (실제 refresh_corp_codes()는 네트워크 호출이 필요해 이 샌드박스에서는
    검증할 수 없다 — 대신 아래 test_refresh_corp_codes_parses_zip_xml에서
    zip/xml 파싱 로직만 별도로 검증한다.)
    """
    with client._conn:
        client._conn.executemany(
            "INSERT INTO dart_corp_code (corp_code, corp_name, stock_code, modify_date) VALUES (?, ?, ?, ?)",
            [(code, name, stock, "20240101") for code, name, stock in rows],
        )
    client._name_cache = None


# ── match_company: 긴 이름 우선 매칭 (오탐 방지) ──────────────────────


def test_match_company_prefers_longer_name_over_substring(client):
    _seed_corp_codes(
        client,
        [
            ("00126380", "삼성전자", "005930"),
            ("00164779", "SK하이닉스", "000660"),
            ("00190845", "SK이노베이션", "096770"),
            ("00120180", "SK", "034730"),
        ],
    )
    match = client.match_company("SK하이닉스가 오늘 급등했다.")
    assert match is not None
    assert match.corp_name == "SK하이닉스"
    assert match.stock_code == "000660"


def test_match_company_does_not_confuse_sk_variants(client):
    _seed_corp_codes(
        client,
        [
            ("00190845", "SK이노베이션", "096770"),
            ("00120180", "SK", "034730"),
        ],
    )
    match = client.match_company("SK이노베이션 실적 발표")
    assert match is not None
    assert match.corp_name == "SK이노베이션"


def test_match_company_returns_none_when_cache_empty(client):
    assert client.match_company("삼성전자 급등") is None


def test_match_company_returns_none_when_no_match(client):
    _seed_corp_codes(client, [("00126380", "삼성전자", "005930")])
    assert client.match_company("어느 중소형주 급등") is None


def test_match_company_rejects_ambiguous_common_word_without_finance_context(client):
    """"남성"은 실제 코스닥 상장사명이지만 뉴스 대부분은 "20대 남성"처럼
    일반 명사로 쓴다. 금융 문맥 신호(주가/실적/공시 등)가 없으면 종목으로
    인정하지 않아야 한다 (스크린샷으로 제보된 오탐: 실종자 사망 기사가
    [남성] 종목 뉴스로 잘못 분류됨)."""
    _seed_corp_codes(client, [("00300001", "남성", "004270")])
    match = client.match_company("제주서 실종 20대 남성 숨진채 발견…신고 25시간만")
    assert match is None


def test_match_company_accepts_ambiguous_common_word_with_finance_context(client):
    """반대로, 진짜 "남성" 종목 뉴스(주가/실적 등 금융 문맥 동반)는
    정상적으로 매칭되어야 한다 — 오탐 방지가 과도한 차단으로 이어지면
    안 된다."""
    _seed_corp_codes(client, [("00300001", "남성", "004270")])
    match = client.match_company("남성 주가 오늘 상한가 기록")
    assert match is not None
    assert match.corp_name == "남성"


def test_find_by_name_exact_match(client):
    _seed_corp_codes(client, [("00126380", "삼성전자", "005930")])
    match = client.find_by_name("삼성전자")
    assert match is not None
    assert match.corp_code == "00126380"
    assert match.stock_code == "005930"


def test_find_by_name_returns_none_when_absent(client):
    assert client.find_by_name("존재하지않는회사") is None


# ── 관심종목 추적 ──────────────────────────────────────────────────────


def test_mark_watched_inserts_new_stock(client):
    _seed_corp_codes(client, [("00126380", "삼성전자", "005930")])
    match = client.match_company("삼성전자 급등")
    client.mark_watched(match)
    watched = client.list_watched_stocks()
    assert len(watched) == 1
    assert watched[0].corp_name == "삼성전자"
    assert watched[0].mention_count == 1


def test_mark_watched_increments_mention_count_on_repeat(client):
    _seed_corp_codes(client, [("00126380", "삼성전자", "005930")])
    match = client.match_company("삼성전자 급등")
    client.mark_watched(match)
    client.mark_watched(match)
    client.mark_watched(match)
    watched = client.list_watched_stocks()
    assert len(watched) == 1
    assert watched[0].mention_count == 3


def test_mark_watched_ignores_match_without_stock_code(client):
    from stock_news_bot.storage.dart_client import CompanyMatch

    client.mark_watched(CompanyMatch(corp_code="X", corp_name="비상장", stock_code=None))
    assert client.list_watched_stocks() == []


def test_list_watched_stocks_sorted_by_last_seen_desc(client):
    _seed_corp_codes(
        client,
        [("00126380", "삼성전자", "005930"), ("00164779", "SK하이닉스", "000660")],
    )
    m1 = client.match_company("삼성전자 급등")
    m2 = client.match_company("SK하이닉스 실적")
    client.mark_watched(m1)
    client.mark_watched(m2)
    watched = client.list_watched_stocks()
    # 나중에 mark_watched된 SK하이닉스가 먼저 나와야 한다 (last_seen_at 내림차순)
    assert watched[0].corp_name == "SK하이닉스"


# ── 재무데이터 캐시 ────────────────────────────────────────────────────


def test_get_cached_financials_returns_none_when_absent(client):
    assert client.get_cached_financials("00126380") is None


def test_set_and_get_cached_financials_roundtrip(client):
    financials = CompanyFinancials(
        corp_code="00126380", bsns_year="2024", reprt_code="11011",
        revenue=300_000_000_000_000, operating_profit=30_000_000_000_000,
    )
    client.set_financials(financials)
    cached = client.get_cached_financials("00126380")
    assert cached is not None
    assert cached.revenue == 300_000_000_000_000
    assert cached.operating_profit == 30_000_000_000_000


def test_set_financials_upserts_on_conflict(client):
    client.set_financials(
        CompanyFinancials(
            corp_code="00126380", bsns_year="2024", reprt_code="11011",
            revenue=100, operating_profit=10,
        )
    )
    client.set_financials(
        CompanyFinancials(
            corp_code="00126380", bsns_year="2024", reprt_code="11011",
            revenue=200, operating_profit=20,
        )
    )
    cached = client.get_cached_financials("00126380")
    assert cached.revenue == 200
    assert cached.operating_profit == 20


def test_get_cached_financials_prefers_latest_year(client):
    client.set_financials(
        CompanyFinancials(corp_code="00126380", bsns_year="2023", reprt_code="11011",
                           revenue=100, operating_profit=10)
    )
    client.set_financials(
        CompanyFinancials(corp_code="00126380", bsns_year="2024", reprt_code="11011",
                           revenue=200, operating_profit=20)
    )
    cached = client.get_cached_financials("00126380")
    assert cached.bsns_year == "2024"
    assert cached.revenue == 200


# ── _extract_account_amount: 계정과목 파싱 ────────────────────────────


def test_extract_account_amount_finds_matching_account():
    from stock_news_bot.storage.dart_client import _extract_account_amount

    items = [
        {"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "1,234,567"},
        {"fs_div": "CFS", "account_nm": "영업이익", "thstrm_amount": "123,456"},
    ]
    assert _extract_account_amount(items, ["매출액", "수익(매출액)"]) == 1234567
    assert _extract_account_amount(items, ["영업이익"]) == 123456


def test_extract_account_amount_tries_alternate_names():
    from stock_news_bot.storage.dart_client import _extract_account_amount

    items = [{"fs_div": "CFS", "account_nm": "수익(매출액)", "thstrm_amount": "999"}]
    assert _extract_account_amount(items, ["매출액", "수익(매출액)"]) == 999


def test_extract_account_amount_prefers_cfs_over_ofs():
    from stock_news_bot.storage.dart_client import _extract_account_amount

    items = [
        {"fs_div": "OFS", "account_nm": "매출액", "thstrm_amount": "111"},
        {"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "222"},
    ]
    assert _extract_account_amount(items, ["매출액"]) == 222


def test_extract_account_amount_returns_none_when_not_found():
    from stock_news_bot.storage.dart_client import _extract_account_amount

    items = [{"fs_div": "CFS", "account_nm": "당기순이익", "thstrm_amount": "1"}]
    assert _extract_account_amount(items, ["매출액"]) is None


def test_extract_account_amount_handles_empty_amount_string():
    from stock_news_bot.storage.dart_client import _extract_account_amount

    items = [{"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": ""}]
    assert _extract_account_amount(items, ["매출액"]) is None


# ── refresh_corp_codes: zip/xml 파싱 로직 (네트워크 없이 검증) ─────────


def test_refresh_corp_codes_parses_zip_and_filters_unlisted(client, monkeypatch):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<result>
    <list>
        <corp_code>00126380</corp_code>
        <corp_name>삼성전자</corp_name>
        <stock_code>005930</stock_code>
        <modify_date>20240101</modify_date>
    </list>
    <list>
        <corp_code>00999999</corp_code>
        <corp_name>어느비상장법인</corp_name>
        <stock_code></stock_code>
        <modify_date>20240101</modify_date>
    </list>
</result>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml_content)
    zip_bytes = buf.getvalue()

    class _FakeResponse:
        content = zip_bytes

        def raise_for_status(self):
            pass

    # dart_client.py는 requests를 함수 내부에서 지연 임포트하므로, 전역
    # sys.modules에 가짜 requests를 심어서 가로챈다.
    import sys
    import types

    fake_requests_module = types.ModuleType("requests")
    fake_requests_module.get = lambda *a, **k: _FakeResponse()

    class _FakeRequestException(Exception):
        pass

    fake_requests_module.RequestException = _FakeRequestException
    monkeypatch.setitem(sys.modules, "requests", fake_requests_module)

    count = client.refresh_corp_codes("fake-key")
    assert count == 1  # 비상장(stock_code 없음)은 제외되어야 함

    match = client.find_by_name("삼성전자")
    assert match is not None
    assert match.stock_code == "005930"
    assert client.find_by_name("어느비상장법인") is None
    assert client.last_refreshed_at() is not None
