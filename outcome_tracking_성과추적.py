# -*- coding: utf-8 -*-
"""
성과 피드백 루프 (Outcome Tracking).

[재작성 배경]
이 파일은 원래 OutcomeTracker 클래스였으나, main_메인.py / admin_관리자.py는
이 파일에서 _engine_load_outcome_tracking, _engine_outcome_tracking_cycle,
_outcome_aggregate_report를 모듈 함수로 직접 import하고 있어(클래스 메서드로는
import 자체가 실패) 그대로는 기동이 되지 않았다. 이번 재작성에서 클래스 로직을
모듈 함수로 옮기고, 실제로 동작하지 않던 _get_current_price(항상 0.0을 반환하는
미구현 스텁)를 DART corpCode 매핑 + Yahoo 시세 조회로 실제 구현했다.

설계는 요청하신 그대로 2단계 구조를 유지한다:
  1단계 (_engine_record_outcome_tracking): 뉴스 송출 시점에 판정 근거만 기록.
         발송 지연을 막기 위해 이 시점에는 주가 조회를 하지 않는다.
  2단계 (_engine_outcome_tracking_cycle): 주기적으로 기준가 확보 → 지연 후
         체크가 확보 → 등락률 계산까지 진행한다.
  3단계 (_outcome_aggregate_report): 결과가 확정된 데이터로 종목별 평균
         등락률/적중률을 집계해 관리자에게 보낼 리포트 문자열을 만든다.
"""

import os
import json
import logging
from datetime import datetime

from common_공용유틸 import (
    _engine_atomic_append_jsonl,
    _engine_atomic_rewrite_jsonl,
    _engine_log,
    _now_kst,
    log_error,
)
from sources_external_외부연동 import _dart_stock_code_for_name
from overseas_해외수집 import _yahoo_chart_quote
from ml_learning_기계학습 import _ml_generate_analysis, _ml_learn_macro_label, _ml_learn_from_completed_record

logger = logging.getLogger("NewsBotOutcomeTracking")

OUTCOME_DB_FILE = os.environ.get("NEWS_BOT_OUTCOME_DB", "outcome_tracking.jsonl")
OUTCOME_BASELINE_WINDOW_MIN = int(os.environ.get("OUTCOME_BASELINE_WINDOW_MIN", "5"))
OUTCOME_CHECK_DELAY_MIN = int(os.environ.get("OUTCOME_CHECK_DELAY_MIN", "60"))
OUTCOME_MIN_SAMPLES_FOR_LEARNING = int(os.environ.get("OUTCOME_MIN_SAMPLES_FOR_LEARNING", "3"))

MACRO_KEYWORDS = ["시황", "마감", "브리핑", "라이브", "순환매", "급락", "급등주 점검"]


def _engine_load_outcome_tracking():
    """부팅 시 1회 호출. 레코드는 파일 기반이라 별도 메모리 프리로드는
    필요 없고, 존재 여부/건수만 확인해 로그로 남긴다."""
    count = 0
    if os.path.exists(OUTCOME_DB_FILE):
        try:
            with open(OUTCOME_DB_FILE, "r", encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
        except Exception as e:
            log_error("성과추적 DB 로드", e)
    _engine_log("info", "[성과추적] 초기화 완료 | 누적 레코드=%d건", count)


def _get_current_price(stock_name):
    """[버그 수정] 기존에는 항상 0.0을 반환하는 미구현 스텁이라 baseline_price
    확보 조건(p > 0)을 절대 통과하지 못해 모든 레코드가 'Baseline price
    acquisition timeout'으로 끝나고 실제 등락률 추적이 전혀 되지 않았다.
    종목명 → DART corpCode → 6자리 종목코드 → Yahoo 시세 순으로 실제 현재가를
    조회한다. 실패하면 추정하지 않고 None을 반환하며, 호출부는 다음 주기로
    재시도를 미룬다."""
    name = str(stock_name or "").strip()
    if not name:
        return None
    try:
        code = _dart_stock_code_for_name(name)
        if not code:
            return None
        for suffix in (".KS", ".KQ"):
            q = _yahoo_chart_quote(f"{code}{suffix}")
            if q and q.get("price") is not None and float(q["price"]) > 0:
                return float(q["price"])
        return None
    except Exception as e:
        logger.error(f"주가 조회 중 에러 발생 ({stock_name}): {e}")
        return None


def _load_historical_records():
    try:
        with open(OUTCOME_DB_FILE, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
    except Exception as e:
        log_error("성과추적 과거 데이터 로드", e)
        return []


def _analyze_historical_pattern(category, title, related_stocks):
    """데이터 누적 기반 학습 및 분석(기존 로직 유지):
    과거에 유사한 카테고리·키워드로 처리된 데이터를 분석해 이번 뉴스가
    실효성 있는 개별 호재인지, 단순 시황/광고성 언급인지 자동 판정한다."""
    history_stats = {
        "total_records": 0, "category_match_count": 0, "category_macro_ratio": 0.0,
        "keyword_matched_count": 0, "avg_historical_change": 0.0,
        "learning_status": "Insufficient data",
    }
    records = _load_historical_records()
    history_stats["total_records"] = len(records)
    if len(records) < OUTCOME_MIN_SAMPLES_FOR_LEARNING:
        history_stats["learning_status"] = f"Building history ({len(records)}/{OUTCOME_MIN_SAMPLES_FOR_LEARNING})"
        return False, "Insufficient sample size for auto-learning", history_stats

    category_matches = [r for r in records if r.get("category") == category]
    history_stats["category_match_count"] = len(category_matches)
    macro_count = sum(1 for r in category_matches if r.get("is_macro_or_ad", False))
    if category_matches:
        history_stats["category_macro_ratio"] = round((macro_count / len(category_matches)) * 100, 1)

    is_auto_macro = False
    learning_reason = "Passed historical validation (Active stock news)"
    if len(category_matches) >= 5 and (macro_count / len(category_matches) >= 0.7):
        is_auto_macro = True
        learning_reason = f"Auto-classified as Macro/Ad (Category history ratio: {history_stats['category_macro_ratio']}%)"

    matched_kw = [kw for kw in MACRO_KEYWORDS if kw in title]
    if matched_kw:
        similar_kw_records = [r for r in records if any(kw in r.get("title", "") for kw in MACRO_KEYWORDS)]
        history_stats["keyword_matched_count"] = len(similar_kw_records)
        if len(similar_kw_records) >= 3:
            avg_changes = []
            for r in similar_kw_records:
                if r.get("change_pct"):
                    avg_changes.extend(list(r["change_pct"].values()))
            if avg_changes:
                history_stats["avg_historical_change"] = round(sum(avg_changes) / len(avg_changes), 2)
            if history_stats["avg_historical_change"] < 0.3 and len(similar_kw_records) >= 3:
                is_auto_macro = True
                learning_reason = f"Auto-classified as Macro/Ad (Keyword '{matched_kw[0]}' avg change: {history_stats['avg_historical_change']}%)"

    history_stats["learning_status"] = "Macro/Ad Filtered" if is_auto_macro else "Active Tracking"
    return is_auto_macro, learning_reason, history_stats


def _engine_record_outcome_tracking(title, category, related_stocks, reason, evidence):
    """1단계: 뉴스 송출 시점에 판정 근거를 기록한다.
    발송 지연을 막기 위해 이 시점에는 주가 조회를 전혀 하지 않는다(checked=False)."""
    is_auto_macro, learning_reason, history_stats = _analyze_historical_pattern(category, title, related_stocks)

    accumulated_summary_msg = (
        f"📊 [누적 데이터 분석 요약]\n"
        f"• 누적 총 데이터: {history_stats['total_records']}건\n"
        f"• 동일 카테고리 매칭: {history_stats['category_match_count']}건 (시황/광고 비중: {history_stats['category_macro_ratio']}%)\n"
        f"• 유사 키워드 이력: {history_stats['keyword_matched_count']}건 (평균 변동성: {history_stats['avg_historical_change']}%)\n"
        f"• 최종 판정 상태: {history_stats['learning_status']}"
    )

    # [학습형 AI] 시황/광고 여부는 위에서 이미 확정됐으므로 지연 없이 바로 온라인
    # 학습에 반영한다. 등락률(실제 상승/하락)은 아직 모르므로 여기서는 학습하지
    # 않고, _engine_outcome_tracking_cycle에서 결과가 확정될 때 별도로 학습한다.
    _ml_learn_macro_label(title, category, related_stocks, reason, evidence, is_auto_macro)
    ml_summary_msg, ml_prediction_snapshot = _ml_generate_analysis(title, category, related_stocks, reason, evidence)
    if ml_summary_msg:
        accumulated_summary_msg = f"{accumulated_summary_msg}\n\n{ml_summary_msg}"

    record = {
        "timestamp": _now_kst().isoformat(),
        "category": category,
        "title": title,
        "related_stocks": related_stocks if not is_auto_macro else [],
        "raw_stocks": related_stocks,
        "reason": f"{reason} | [Learning Log: {learning_reason}]",
        "evidence": evidence,
        "is_macro_or_ad": is_auto_macro,
        "accumulated_analysis": history_stats,
        "accumulated_summary_msg": accumulated_summary_msg,
        "ml_analysis": ml_prediction_snapshot,
        "baseline_price": None,
        "checked_price": None,
        "change_pct": None,
        "checked": is_auto_macro,
        "error_message": "Auto-skipped by historical learning model" if is_auto_macro else None,
    }

    if not _engine_atomic_append_jsonl(OUTCOME_DB_FILE, record):
        logger.error(f"성과 추적 레코드 기록 실패: {title}")
    else:
        logger.info(f"성과 추적 레코드 기록 완료 (누적 분석 포함): {title}")

    return accumulated_summary_msg


def _engine_outcome_tracking_cycle():
    """2단계: 주기적으로 호출되어 기준가 확보 → 지연 후 체크가 확보 →
    등락률 계산까지 진행한다."""
    try:
        with open(OUTCOME_DB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    except Exception as e:
        log_error("성과추적 데이터 파일 읽기", e)
        return

    updated_records = []
    now = _now_kst()
    changed = False

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue

        if record.get("checked"):
            updated_records.append(record)
            continue

        try:
            record_time = datetime.fromisoformat(record["timestamp"])
        except Exception:
            record["checked"] = True
            record["error_message"] = "Invalid timestamp"
            updated_records.append(record)
            changed = True
            continue

        elapsed_min = (now - record_time).total_seconds() / 60

        if record.get("baseline_price") is None:
            stocks = record.get("related_stocks") or []
            if not stocks:
                record["checked"] = True
                record["error_message"] = "No related stocks to track"
                changed = True
            elif elapsed_min <= OUTCOME_BASELINE_WINDOW_MIN:
                prices = {stock: _get_current_price(stock) for stock in stocks}
                if all(p is not None and p > 0 for p in prices.values()):
                    record["baseline_price"] = prices
                    changed = True
            else:
                record["error_message"] = "Baseline price acquisition timeout"
                record["checked"] = True
                changed = True

        elif not record.get("checked"):
            if elapsed_min >= OUTCOME_CHECK_DELAY_MIN:
                stocks = list(record["baseline_price"].keys())
                current_prices = {stock: _get_current_price(stock) for stock in stocks}
                if all(p is not None and p > 0 for p in current_prices.values()):
                    change_results = {}
                    for stock, base_p in record["baseline_price"].items():
                        curr_p = current_prices[stock]
                        change_results[stock] = round(((curr_p - base_p) / base_p) * 100, 2)
                    record["checked_price"] = current_prices
                    record["change_pct"] = change_results
                    record["checked"] = True
                    # [학습형 AI] 결과가 실제로 확정된 이 시점에만 학습한다(가짜/추정
                    # 데이터로 학습하지 않는다는 원칙). 학습 실패는 성과추적 흐름을
                    # 막지 않도록 함수 내부에서 자체적으로 예외를 흡수한다.
                    _ml_learn_from_completed_record(record)
                else:
                    record["error_message"] = "Checked price acquisition failed"
                    record["checked"] = True
                changed = True

        updated_records.append(record)

    if changed:
        _engine_atomic_rewrite_jsonl(OUTCOME_DB_FILE, updated_records)


def _outcome_aggregate_report(min_samples=3):
    """3단계: /성과리포트 [최소표본수] 명령에 대한 응답 문자열을 만든다.
    결과가 확정된(등락률이 산출된) 레코드만으로 종목별 평균 등락률과
    적중률(상승 비율)을 표본이 min_samples건 이상인 종목만 집계한다."""
    records = _load_historical_records()
    completed = [r for r in records if r.get("checked") and r.get("change_pct") and not r.get("is_macro_or_ad", False)]

    per_stock = {}
    for r in completed:
        for stock, pct in (r.get("change_pct") or {}).items():
            per_stock.setdefault(stock, []).append(pct)

    lines = [
        "📊 <b>[성과 추적 리포트]</b>",
        f"🕐 {_now_kst().strftime('%Y-%m-%d %H:%M')} KST",
        "",
        f"• 누적 총 레코드: {len(records)}건",
        f"• 결과 확정(등락률 산출) 레코드: {len(completed)}건",
        "",
    ]

    qualified = {s: v for s, v in per_stock.items() if len(v) >= min_samples}
    if not qualified:
        lines.append(f"• 표본이 {min_samples}건 이상인 종목이 아직 없습니다.")
        return "\n".join(lines)

    lines.append(f"<b>종목별 성과 (표본 {min_samples}건 이상)</b>")
    ranked = sorted(qualified.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)
    for stock, changes in ranked[:20]:
        avg = sum(changes) / len(changes)
        hit_rate = round(sum(1 for c in changes if c > 0) / len(changes) * 100, 1)
        lines.append(f"• {stock} · 평균 {avg:+.2f}% · 상승비율 {hit_rate}% · 표본 {len(changes)}건")

    return "\n".join(lines)
