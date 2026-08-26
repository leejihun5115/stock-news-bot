# -*- coding: utf-8 -*-
"""
fill_case_outcomes.py
==============================================================================
[외부 스케줄러 전용] MASTER(master_condition_manager.py)와는 완전히 분리된
스크립트다. MASTER는 주가 데이터를 스스로 만들어내지 않는다 — 이 스크립트가
매일 장 마감 후 별도로 실행되어, CaseHistoryStore에 쌓인 사례 중 아직
outcome_pct(등락률)가 없는 것만 채워 넣는다.

[데이터 출처] 네이버 화면을 직접 크롤링하지 않는다. FinanceDataReader가
KRX/네이버 시세를 안정적으로 가져오도록 만들어진 표준 라이브러리이므로 이걸
쓴다 — 네이버 HTML 구조가 바뀌어도 이 스크립트가 깨지지 않는다.

설치:
    pip install finance-datareader

사용법 (매일 장 마감 후 cron/스케줄러로 실행):
    python fill_case_outcomes.py --store data/case_history.json --days-after 1

--days-after 1  = 사건 발생일 종가 대비 "다음 거래일" 종가 등락률을 기록한다.
                  (아직 그 거래일 시세가 안 나왔으면 이번엔 건너뛰고, 다음
                  실행 때 자동으로 다시 시도한다 — 별도 처리 불필요)
==============================================================================
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta

try:
    import FinanceDataReader as fdr
except ImportError:
    fdr = None  # 테스트 환경 등 라이브러리 미설치 시에도 이 파일은 import 가능해야 함

from master_condition_manager import CaseHistoryStore


def _load_krx_listing():
    """[노하우] 종목명→코드 매핑을 매번 새로 구하지 않고 한 번만 불러와 재사용한다.
    KRX 상장 종목 목록은 FinanceDataReader가 KRX/네이버 데이터를 조합해 제공한다."""
    listing = fdr.StockListing("KRX")
    return dict(zip(listing["Name"], listing["Code"]))


def _resolve_code(name_to_code, company_name):
    if company_name in name_to_code:
        return name_to_code[company_name]
    stripped = company_name.replace(" ", "")
    for name, code in name_to_code.items():
        if name.replace(" ", "") == stripped:
            return code
    return None


def compute_pct_change(price_df, base_date: date, days_after: int):
    """[순수 계산 — 네트워크 없이도 테스트 가능] price_df는
    fdr.DataReader(code, start, end)가 반환하는 DataFrame과 동일한 형태
    (index: 날짜, 'Close' 컬럼)여야 한다.

    반환값:
      - float: 등락률(%)
      - None: 아직 목표 거래일 시세가 없음(=다음 실행에 재시도) 또는 데이터 없음
    """
    if price_df is None or price_df.empty:
        return None
    trading_days = [d.date() if hasattr(d, "date") else d for d in price_df.index]

    if base_date not in trading_days:
        future = [d for d in trading_days if d >= base_date]
        if not future:
            return None
        base_date = future[0]

    base_idx = trading_days.index(base_date)
    target_idx = base_idx + days_after
    if target_idx >= len(trading_days):
        return None  # 아직 그날 거래가 끝나지 않음 — 다음 실행에서 자동 재시도

    base_close = float(price_df.iloc[base_idx]["Close"])
    target_close = float(price_df.iloc[target_idx]["Close"])
    if base_close == 0:
        return None
    return round((target_close - base_close) / base_close * 100, 2)


def _fetch_price(code: str, base_date: date, days_after: int):
    start = base_date - timedelta(days=5)
    end = base_date + timedelta(days=days_after + 7)
    return fdr.DataReader(code, start.isoformat(), end.isoformat())


def fill_outcomes(store_path: str, days_after: int = 1):
    if fdr is None:
        raise RuntimeError("FinanceDataReader가 설치되어 있지 않습니다: pip install finance-datareader")

    store = CaseHistoryStore(store_path)
    records = store.all_records()
    name_to_code = _load_krx_listing()

    filled = skipped = failed = 0
    for r in records:
        if r.get("outcome_pct") is not None:
            continue
        related = r.get("related") or []
        if not related:
            skipped += 1
            continue

        company_name = related[0]  # 대장주(첫 관련종목) 기준으로 기록
        code = _resolve_code(name_to_code, company_name)
        if not code:
            print(f"[건너뜀] 종목코드 못 찾음: {company_name}")
            skipped += 1
            continue

        base_date = datetime.fromisoformat(r["created_at"]).date()
        try:
            price_df = _fetch_price(code, base_date, days_after)
            pct = compute_pct_change(price_df, base_date, days_after)
        except Exception as e:
            print(f"[실패] {company_name}({code}): {e}")
            failed += 1
            continue

        if pct is None:
            skipped += 1  # 아직 거래일이 안 지남 — 다음 실행에 자동 재시도
            continue

        store.record_outcome(
            r["case_id"], pct,
            note=f"{company_name}({code}) 종가 기준 {days_after}거래일 후",
        )
        filled += 1
        print(f"[기록] {company_name}({code}) {days_after}거래일 후 {pct:+.2f}%")

    print(f"완료: {filled}건 기록 / {skipped}건 보류(재시도 예정) / {failed}건 실패")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CaseHistoryStore에 실제 등락률을 채워 넣는다.")
    parser.add_argument("--store", required=True, help="case_history.json 경로")
    parser.add_argument("--days-after", type=int, default=1, help="사건일 대비 며칠 뒤 종가를 볼지")
    args = parser.parse_args()
    fill_outcomes(args.store, args.days_after)
