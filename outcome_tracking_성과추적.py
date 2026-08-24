import sys
import time
import datetime
import threading
import traceback
import feedparser
import requests
import html
import json
import hashlib
import tempfile
import re
import os
import difflib
import zipfile
import io
import xml.etree.ElementTree as ET
import builtins as _builtins
import logging
from logging import FileHandler
from collections import defaultdict, Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ==== module: outcome_tracking (auto-split from original main.py) ====

from common_공용유틸 import _engine_atomic_append_jsonl, _engine_atomic_rewrite_jsonl, _engine_log, _engine_parse_datetime, _now_kst, log_error
from config_환경설정 import ENABLE_HISTORICAL_SURGE_DB, ENABLE_OUTCOME_TRACKING


# [성과 피드백 루프 1단계] 실제로 알림을 보낸 뉴스의 "관련주 판정 근거"를 별도 DB에 기록한다.
# 이 시점에는 아직 주가 반응을 모른다(checked=False) - 2단계(추후 시세 재조회)에서
# 이 DB를 읽어 실제 등락률을 채워 넣고, 3단계(집계)에서 키워드/재료별 적중률을 계산하는 데 쓴다.
# 지금은 "기록만" 한다 - 판정 로직/발송 로직에는 전혀 영향을 주지 않는 순수 부가 기능이다.
OUTCOME_TRACKING_DB = os.environ.get("NEWS_BOT_OUTCOME_TRACKING_DB", "news_bot_outcome_tracking.jsonl")
# [성과 피드백 루프 2단계-B] 발송 시점에는 시세를 조회하지 않으므로, 발송 직후
# 별도로 "기준가(baseline)"를 한 번 잡아야 한다. 기준가를 못 잡고 이 시간이
# 지나면 포기한다(그 종목은 코드 미확인/거래정지 등으로 추정).
OUTCOME_BASELINE_WINDOW_MIN = max(3, int(os.environ.get("NEWS_BOT_OUTCOME_BASELINE_WINDOW_MIN", "20")))
# 기준가 확보 후 이만큼 지나야 "결과"로 확정한다(단기 반응 확인용).
OUTCOME_CHECK_DELAY_MIN = max(5, int(os.environ.get("NEWS_BOT_OUTCOME_CHECK_DELAY_MIN", "60")))
# 이 루프 자체를 60초 주기 메인 사이클마다 돌리면 시세 API를 과도하게 두드리므로,
# 최소 이 간격(초)마다 한 번만 실행한다.
OUTCOME_CYCLE_INTERVAL_SEC = max(60, int(os.environ.get("NEWS_BOT_OUTCOME_CYCLE_INTERVAL_SEC", "300")))
# 한 번의 루프에서 처리할 최대 건수(시세 API 순간 폭주 방지).
OUTCOME_CYCLE_MAX_PER_RUN = max(5, int(os.environ.get("NEWS_BOT_OUTCOME_CYCLE_MAX_PER_RUN", "30")))


def _engine_record_outcome_tracking(item, master_result):
    """[성과 피드백 루프 1단계] 실제로 송출된 뉴스의 판정 근거를 기록만 한다.

    - 여기서는 주가 조회를 하지 않는다(발송 경로를 절대 느리게 하지 않기 위함).
    - MASTER가 관련주를 확정하지 못한 뉴스(related_none_reason만 있는 경우)도
      "관련주 無로 확정한 판단이 맞았는지" 나중에 검증할 수 있도록 함께 남긴다.
    - checked=False 레코드는 2단계 스크립트/함수가 나중에 시세를 채워 넣는다.
    """
    from domestic_국내수집 import _kr_yahoo_quote, _resolve_stock_code_for_name
    from news_engine_핵심엔진 import _engine_master_usable
    if not ENABLE_OUTCOME_TRACKING or not _engine_master_usable(master_result):
        return
    related = master_result.get("related") or []
    leader = master_result.get("leader") or {}
    row = {
        "ts": _now_kst().isoformat(),
        "source": str(item.get("source", ""))[:80],
        "title": str(master_result.get("title") or item.get("title", ""))[:300],
        "link": str(item.get("link", ""))[:1000],
        "market_state": str(item.get("market_state", ""))[:40],
        "stage": str(master_result.get("stage", ""))[:80],
        "leader": str(leader.get("name", ""))[:60],
        "leader_code": _resolve_stock_code_for_name(leader.get("name", "")) if ENABLE_OUTCOME_TRACKING else "",
        "related": [
            {
                "name": str(r.get("name", ""))[:60],
                "code": _resolve_stock_code_for_name(r.get("name", "")),
                "reason": str(r.get("reason", ""))[:200],
            }
            for r in related[:3]
        ],
        "related_none_reason": str(master_result.get("related_none_reason", ""))[:200],
        "evidence": [str(x)[:120] for x in (master_result.get("evidence") or [])[:8]],
        "baseline_price": None,
        "baseline_failed": False,
        "checked": False,
        "outcome": None,
    }
    if _engine_atomic_append_jsonl(OUTCOME_TRACKING_DB, row):
        # 재시작 없이도 이번 프로세스의 성과추적 사이클이 바로 이 기록을 처리할 수 있도록
        # 메모리 목록에도 함께 반영한다(파일에는 이미 append됐으므로 다음 로드 때도 정상 복원됨).
        _engine_load_outcome_tracking()
        _OUTCOME_TRACKING_ROWS.append(row)
        if len(_OUTCOME_TRACKING_ROWS) > 5000:
            del _OUTCOME_TRACKING_ROWS[:-5000]


def _engine_company_history_score(name):
    """[누적 데이터 연동 / 조건25·26 과거급등이력·과거주도이력]
    과거 누적 DB(HISTORICAL_SURGE_DB)에서 이 종목이 몇 번이나 등장했는지 세어
    보조 점수로 변환한다. [1원칙: 무조건 누적] 이후로는 강한 재료가 아닌 뉴스도
    전부 쌓이므로, 실제 급등 이력(is_surge_hit)에는 가중치를 더 주고 단순 언급은
    약하게 반영해 "많이 언급됐다"와 "실제로 급등했다"를 구분한다.
    MasterConditionManager._score()의 history_score는 이 값을 받아 최대 8점까지만
    반영한다(직접 근거를 넘어서지 않음).
    """
    from news_engine_핵심엔진 import _engine_historical_cache
    name = str(name or "").strip()
    if not name or not ENABLE_HISTORICAL_SURGE_DB or not _engine_historical_cache:
        return 0.0
    score = 0.0
    for row in _engine_historical_cache[-3000:]:
        companies = [str(c).strip() for c in (row.get("companies") or [])]
        matched = name in companies or (name and name in str(row.get("text", "")))
        if not matched:
            continue
        score += 1.5 if row.get("is_surge_hit") else 0.5
    return score


def _engine_company_history_detail(name):
    """[누적데이터 분석] 이 종목이 과거 급등 이력 DB에 몇 번, 언제, 어떤 시장상황에서
    등장했는지 요약한다. 메시지의 '📊 누적데이터' 섹션에서 과거-현재 시장상황 비교에 쓰인다.
    이력이 전혀 없으면 None을 반환해 해당 섹션 자체를 표시하지 않는다(있는 데이터만 보여줌).
    """
    from news_engine_핵심엔진 import _engine_historical_cache
    name = str(name or "").strip()
    if not name or not ENABLE_HISTORICAL_SURGE_DB or not _engine_historical_cache:
        return None
    matches = []
    for row in _engine_historical_cache[-3000:]:
        companies = [str(c).strip() for c in (row.get("companies") or [])]
        if name in companies or (name and name in str(row.get("text", ""))):
            matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda r: str(r.get("ts", "")))
    state_counts = Counter(str(r.get("market_state") or "").strip() for r in matches if r.get("market_state"))
    return {
        "count": len(matches),
        "first_ts": matches[0].get("ts", ""),
        "last_ts": matches[-1].get("ts", ""),
        "state_counts": state_counts,
    }


def _engine_company_outcome_stats(name):
    """[누적데이터 분석] 성과추적 DB(OUTCOME_TRACKING_DB)에서 이 종목이 과거에 대장주/관련주로
    송출됐던 건들의 실제 주가 등락률 평균을 계산한다. 아직 결과가 확정된 건이 없으면 None.
    """
    name = str(name or "").strip()
    if not name or not ENABLE_OUTCOME_TRACKING:
        return None
    _engine_load_outcome_tracking()
    changes = []
    for row in _OUTCOME_TRACKING_ROWS:
        names = set()
        leader = row.get("leader") or {}
        if leader.get("name"):
            names.add(str(leader["name"]).strip())
        for r in row.get("related") or []:
            if r.get("name"):
                names.add(str(r["name"]).strip())
        if name not in names:
            continue
        outcome = row.get("outcome") or {}
        cp = outcome.get("change_pct")
        if cp is not None:
            changes.append(float(cp))
    if not changes:
        return None
    wins = sum(1 for c in changes if c > 0)
    return {
        "count": len(changes),
        "avg": sum(changes) / len(changes),
        "success_rate": (wins / len(changes)) * 100.0,
    }


# ============================================================
# [성과 피드백 루프 2단계-B] 사후 시세 조회
# ------------------------------------------------------------
# 1단계에서 "판정 근거만" 기록해둔 OUTCOME_TRACKING_DB를 메모리에 올려두고,
# 별도 주기(기본 5분)로:
#   1) baseline_price가 없는 최근 기록 -> 지금 시세를 "기준가"로 한 번 잡는다.
#   2) 기준가는 있는데 아직 checked=False이고 충분한 시간(기본 60분)이 지난
#      기록 -> 지금 시세를 다시 조회해서 기준가 대비 등락률을 outcome에 채운다.
# 값을 "갱신"해야 하므로 append가 아니라 전체 재작성(rewrite)을 쓴다.
# 이 루프가 실패하거나 꺼져 있어도(ENABLE_OUTCOME_TRACKING=false) 기존 뉴스
# 판정/발송 경로에는 전혀 영향을 주지 않는다.
# ============================================================
_OUTCOME_TRACKING_ROWS = []
_OUTCOME_TRACKING_LOADED = False
_OUTCOME_TRACKING_LAST_RUN = 0.0


def _engine_load_outcome_tracking():
    global _OUTCOME_TRACKING_ROWS, _OUTCOME_TRACKING_LOADED
    if _OUTCOME_TRACKING_LOADED:
        return
    _OUTCOME_TRACKING_LOADED = True
    if not os.path.exists(OUTCOME_TRACKING_DB):
        return
    try:
        with open(OUTCOME_TRACKING_DB, "r", encoding="utf-8") as f:
            _OUTCOME_TRACKING_ROWS = [json.loads(x) for x in f if x.strip()][-5000:]
        _engine_log("info", "[성과추적] 기존 기록 %d건 로드", len(_OUTCOME_TRACKING_ROWS))
    except Exception as e:
        log_error("성과추적 DB 읽기", e, file=OUTCOME_TRACKING_DB)
        _OUTCOME_TRACKING_ROWS = []


def _outcome_row_code(row):
    """기록된 대장주 코드를 우선 쓰고, 없으면 관련주 중 코드가 있는 첫 종목을 쓴다."""
    if row.get("leader_code"):
        return row["leader_code"]
    for r in row.get("related") or []:
        if r.get("code"):
            return r["code"]
    return ""


def _engine_outcome_tracking_cycle():
    """5분(기본)마다 한 번, 기준가 미확보 건 -> 기준가 확보 / 결과 미확정 건 -> 결과 확정을 처리한다."""
    from domestic_국내수집 import _kr_yahoo_quote
    global _OUTCOME_TRACKING_LAST_RUN
    if not ENABLE_OUTCOME_TRACKING:
        return
    now_epoch = time.time()
    if now_epoch - _OUTCOME_TRACKING_LAST_RUN < OUTCOME_CYCLE_INTERVAL_SEC:
        return
    _OUTCOME_TRACKING_LAST_RUN = now_epoch

    _engine_load_outcome_tracking()
    if not _OUTCOME_TRACKING_ROWS:
        return

    now = _now_kst()
    dirty = False
    processed = 0

    for row in _OUTCOME_TRACKING_ROWS:
        if processed >= OUTCOME_CYCLE_MAX_PER_RUN:
            break
        ts = _engine_parse_datetime(row.get("ts", ""))
        if ts is None:
            continue
        age_min = (now - ts).total_seconds() / 60.0

        # 1) 기준가 미확보
        if row.get("baseline_price") is None and not row.get("baseline_failed"):
            if age_min > OUTCOME_BASELINE_WINDOW_MIN:
                row["baseline_failed"] = True
                dirty = True
                continue
            code = _outcome_row_code(row)
            if not code:
                row["baseline_failed"] = True
                dirty = True
                continue
            q = _kr_yahoo_quote(code)
            processed += 1
            time.sleep(0.3)
            if q and q.get("price") is not None:
                row["baseline_price"] = q["price"]
                row["baseline_ts"] = now.isoformat()
                dirty = True
            continue

        # 2) 기준가는 있고 결과 미확정 -> 지연시간 경과 시 결과 확정
        if row.get("baseline_price") is not None and not row.get("checked"):
            if age_min < OUTCOME_CHECK_DELAY_MIN:
                continue
            code = _outcome_row_code(row)
            q = _kr_yahoo_quote(code) if code else None
            processed += 1
            time.sleep(0.3)
            if q and q.get("price") is not None:
                base = float(row["baseline_price"])
                change_pct = ((q["price"] - base) / base * 100.0) if base else None
                row["outcome"] = {
                    "price": q["price"],
                    "change_pct": round(change_pct, 2) if change_pct is not None else None,
                    "checked_ts": now.isoformat(),
                }
                row["checked"] = True
                dirty = True
            elif age_min > OUTCOME_CHECK_DELAY_MIN * 4:
                # 시세 조회가 계속 실패하면(거래정지/상장폐지 등) 무한 재시도하지 않는다.
                row["checked"] = True
                row["outcome"] = {"price": None, "change_pct": None, "checked_ts": now.isoformat(), "note": "조회실패"}
                dirty = True

    if dirty:
        if len(_OUTCOME_TRACKING_ROWS) > 5000:
            del _OUTCOME_TRACKING_ROWS[:-5000]
        _engine_atomic_rewrite_jsonl(OUTCOME_TRACKING_DB, _OUTCOME_TRACKING_ROWS)


# ============================================================
# [성과 피드백 루프 3단계] 집계 - 키워드/재료별 적중률
# ------------------------------------------------------------
# 여기서는 어떤 값도 자동으로 바꾸지 않는다(MARKET_IMPACT_KEYWORDS 등 판정용
# 상수를 이 함수가 직접 수정하지 않음). 결과를 사람이 읽고 "이 키워드는 계속
# 강한 재료로 쓸지, 빼거나 순위를 낮출지" 판단하는 데 쓰는 리포트만 만든다.
# (조건64 문제국소수정: 이상 신호가 보이면 해당 키워드만 사람이 손으로 수정)
# ============================================================
def _outcome_aggregate_report(min_samples=3, top_n=8):
    """checked=True인 기록만 모아 키워드별 평균 등락률/상승비율을 계산해 텍스트로 반환한다."""
    _engine_load_outcome_tracking()
    rows = [
        r for r in _OUTCOME_TRACKING_ROWS
        if r.get("checked") and (r.get("outcome") or {}).get("change_pct") is not None
    ]
    if not rows:
        return "📊 [성과리포트] 아직 결과가 확정된 기록이 없습니다. (checked=True 0건)"

    total = len(rows)
    changes = [r["outcome"]["change_pct"] for r in rows]
    overall_avg = sum(changes) / total
    overall_pos = sum(1 for c in changes if c > 0) / total * 100.0

    kw_stats = defaultdict(list)
    for r in rows:
        for kw in (r.get("evidence") or []):
            kw_stats[kw].append(r["outcome"]["change_pct"])

    ranked = []
    for kw, vals in kw_stats.items():
        if len(vals) < min_samples:
            continue
        avg = sum(vals) / len(vals)
        pos_rate = sum(1 for v in vals if v > 0) / len(vals) * 100.0
        ranked.append((avg, kw, len(vals), pos_rate))
    ranked.sort(reverse=True)

    lines = [
        f"📊 [성과리포트] 결과 확정 {total}건 | 전체 평균 등락률 {overall_avg:+.2f}% | 상승비율 {overall_pos:.0f}%",
    ]
    if not ranked:
        lines.append(f"(표본 {min_samples}건 이상인 키워드가 아직 없습니다 - 더 쌓이면 표시됩니다)")
    else:
        lines.append("")
        lines.append(f"🟢 반응 좋은 재료 키워드 (표본 {min_samples}건↑, 평균 등락률 상위)")
        for avg, kw, n, pos in ranked[:top_n]:
            lines.append(f"  • {kw} : 평균 {avg:+.2f}% | 상승비율 {pos:.0f}% | 표본 {n}건")
        lines.append("")
        lines.append("🔴 반응 약한 재료 키워드 (평균 등락률 하위)")
        for avg, kw, n, pos in list(reversed(ranked))[:top_n]:
            lines.append(f"  • {kw} : 평균 {avg:+.2f}% | 상승비율 {pos:.0f}% | 표본 {n}건")
    lines.append("")
    lines.append("※ 이 리포트는 참고용 통계일 뿐, 키워드 목록을 자동으로 바꾸지 않습니다.")
    return "\n".join(lines)
