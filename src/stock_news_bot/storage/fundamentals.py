"""기업 재무데이터(시가총액 / 매출액 / 영업이익) 조회 인터페이스.

【현재 상태】
DART Open API(매출액/영업이익) + pykrx(시가총액) 연동이 완료됐다. 다만
이 모듈은 그 두 데이터소스를 "직접" 호출하지 않는다 — DART/pykrx 호출은
cogs/market_intel.py가 백그라운드에서 미리 해두고, 그 결과를
storage/dart_client.py, storage/market_data.py의 SQLite 캐시에 채워
넣는다. 이 모듈은 그 캐시를 조회하기만 한다.

그래서 다음 두 경우 모두 get_fundamentals()는 None을 반환할 수 있다:
  1) 종목명이 DART 상장사 목록에서 아예 인식되지 않는 경우
     (dart_client.py의 corp_code 캐시가 아직 안 채워졌거나, 비상장/펀드 등)
  2) 종목은 인식됐지만, market_intel이 아직 그 종목의 재무데이터/
     시가총액을 캐싱하지 않은 경우 (해당 종목이 뉴스에 막 처음 등장해서
     아직 갱신 주기가 안 돌았을 때 — 관심종목으로 등록은 되지만 데이터는
     다음 주기에 채워진다)

두 경우 모두 값을 임의로 추정해서 채우지 않는다 (거짓 재무정보를 보여주는
것은 잘못된 투자판단으로 이어질 수 있어 더 위험하다). notifier.py는
fundamentals가 None이면 "재무데이터 미연동" 안내만 붙인다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from stock_news_bot.config import settings
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.market_data import MarketDataStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompanyFundamentals:
    name: str
    market_cap: int | None = None       # 시가총액 (원)
    revenue: int | None = None          # 매출액 (원, 최근 연간 또는 분기)
    operating_profit: int | None = None  # 영업이익 (원)


# 모듈 레벨 지연 초기화. notifier.py 등 호출부는 함수 인터페이스만 알면
# 되고, DB 커넥션 생명주기는 이 모듈이 알아서 관리한다 (dedup.py 등과
# 달리 이 모듈은 cog가 아니라서 명시적으로 close()를 호출할 지점이 없다 —
# 프로세스 종료 시 OS가 정리하는 것으로 충분하다).
_dart_client: DartClient | None = None
_market_store: MarketDataStore | None = None


def _get_dart_client() -> DartClient:
    global _dart_client
    if _dart_client is None:
        _dart_client = DartClient(settings.db_path)
    return _dart_client


def _get_market_store() -> MarketDataStore:
    global _market_store
    if _market_store is None:
        _market_store = MarketDataStore(settings.db_path)
    return _market_store


def get_fundamentals(company_name: str) -> CompanyFundamentals | None:
    """종목명으로 캐싱된 재무데이터를 조회한다.

    DART/pykrx 캐시에 아무것도 없으면 None을 반환해서, 호출부가 "비교
    불가"로 정직하게 처리하게 한다.
    """
    if not company_name:
        return None

    match = _get_dart_client().find_by_name(company_name)
    if match is None:
        return None

    financials = _get_dart_client().get_cached_financials(match.corp_code)
    market_cap = _get_market_store().get_market_cap(match.stock_code) if match.stock_code else None

    if financials is None and market_cap is None:
        return None

    return CompanyFundamentals(
        name=match.corp_name,
        market_cap=market_cap,
        revenue=financials.revenue if financials else None,
        operating_profit=financials.operating_profit if financials else None,
    )
