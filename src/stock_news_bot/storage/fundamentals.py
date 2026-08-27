"""기업 재무데이터(시가총액 / 매출액 / 영업이익) 조회 인터페이스.

【중요 — 현재 상태】
이 모듈은 아직 실제 데이터 소스에 연결되어 있지 않다. `get_fundamentals()`는
항상 None을 반환한다. 뉴스 속 금액("500억원" 등)을 시가총액/매출/영업이익
"대비 몇 %"로 계산해서 보여주려면, 아래 중 하나의 실제 데이터 소스를
연동해야 한다:

  1) DART(전자공시시스템) Open API — opendart.fss.or.kr, 무료지만 API 키
     발급 필요. 재무제표(매출액/영업이익) 조회에 적합.
  2) KRX 정보데이터시스템 — data.krx.co.kr, 시가총액/일별시세 조회에 적합.
  3) 증권사/포털 시세 API — 약관상 상업적 스크래핑 제약이 있는 경우가
     많아 별도 확인 필요.

연동 전까지는 절대로 숫자를 임의로 만들어내지 않는다 (거짓 재무정보를
보여주는 것은 잘못된 투자판단으로 이어질 수 있어 더 위험하다). 대신
notifier.py는 fundamentals가 None이면 "재무데이터 미연동" 안내만 붙인다.

【연동 방법】
실제 API를 붙일 때는 이 파일의 get_fundamentals() 본문만 교체하면 된다.
그 위/아래(CompanyFundamentals dataclass, notifier.py의 사용부)는 그대로
쓸 수 있도록 인터페이스를 고정해뒀다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CompanyFundamentals:
    name: str
    market_cap: int | None = None       # 시가총액 (원)
    revenue: int | None = None          # 매출액 (원, 최근 연간 또는 분기)
    operating_profit: int | None = None  # 영업이익 (원)


def get_fundamentals(company_name: str) -> CompanyFundamentals | None:
    """종목명으로 재무데이터를 조회한다.

    TODO: 실제 데이터 소스(DART Open API 등) 연동 필요. 연동 전까지는
    항상 None을 반환해서, 호출부가 "비교 불가"로 정직하게 처리하게 한다.
    """
    return None
