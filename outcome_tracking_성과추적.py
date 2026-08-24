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

# ==== module: outcome_tracking (restored from original main.py) ====

from common_공용유틸 import _engine_atomic_append_jsonl, _engine_atomic_rewrite_jsonl, _engine_log, _engine_parse_datetime, _now_kst, log_error
from config_환경설정 import ENABLE_HISTORICAL_SURGE_DB, ENABLE_OUTCOME_TRACKING
from news_engine_핵심엔진 import _engine_historical_cache, _engine_master_usable
from domestic_국내수집 import _kr_yahoo_quote, _resolve_stock_code_for_name


OUTCOME_TRACKING_DB = os.environ.get("NEWS_BOT_OUTCOME_TRACKING_DB", "news_bot_outcome_tracking.jsonl")


OUTCOME_BASELINE_WINDOW_MIN = max(3, int(os.environ.get("NEWS_BOT_OUTCOME_BASELINE_WINDOW_MIN", "20")))


OUTCOME_CHECK_DELAY_MIN = max(5, int(os.environ.get("NEWS_BOT_OUTCOME_CHECK_DELAY_MIN", "60")))


OUTCOME_CYCLE_INTERVAL_SEC = max(60, int(os.environ.get("NEWS_BOT_OUTCOME_CYCLE_INTERVAL_SEC", "300")))


OUTCOME_CYCLE_MAX_PER_RUN = max(5, int(os.environ.get("NEWS_BOT_OUTCOME_CYCLE_MAX_PER_RUN", "30")))


def _engine_record_outcome_tracking(item, master_result):
    """[성과 피드백 루프 1단계] 실제로 송출된 뉴스의 판정 근거를 기록만 한다.

    - 여기서는 주가 조회를 하지 않는다(발송 경로를 절대 느리게 하지 않기 위함).
    - MASTER가 관련주를 확정하지 못한 뉴스(related_none_reason만 있는 경우)도
      "관련주 無로 확정한 판단이 맞았는지" 나중에 검증할 수 있도록 함께 남긴다.
    - checked=False 레코드는 2단계 스크립트/함수가 나중에 시세를 채워 넣는다.
    """
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
    # [강화] 단순 등장 횟수만으로는 투자판단에 쓸모가 적다. '끼/탄력'의 확인
    # 근거(핵심원칙: 과거 상한가/급등 이력)로 실제 얼마나 자주 상한가/급등까지
    # 갔었는지를 별도로 세어, 데이터 값 섹션에서 바로 보여줄 수 있게 한다.
    surge_count = sum(1 for r in matches if r.get("is_surge_hit"))
    last_date = ""
    last_ts = matches[-1].get("ts", "")
    if last_ts:
        try:
            last_date = datetime.datetime.fromisoformat(str(last_ts)).strftime("%Y-%m-%d")
        except Exception:
            last_date = str(last_ts)[:10]
    return {
        "count": len(matches),
        "surge_count": surge_count,
        "first_ts": matches[0].get("ts", ""),
        "last_ts": last_ts,
        "last_date": last_date,
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
        if not isinstance(row, dict):
            continue
        names = set()
        # [버그 수정] 기록 시점(_engine_record_outcome_tracking)에는 leader를
        # 문자열(회사명)로 저장하는데, 여기서는 dict로 착각해 leader.get("name")을
        # 호출하고 있었다 -> 'str' object has no attribute 'get' 로 해당 종목이
        # 처음 매칭되는 순간 즉시 실패(운영 로그에서 실제 발생 확인).
        # 실제 저장 포맷(문자열)을 우선 처리하고, 혹시 다른 경로로 dict가 들어온
        # 경우까지 방어적으로 함께 처리한다.
        leader = row.get("leader")
        if isinstance(leader, str) and leader.strip():
            names.add(leader.strip())
        elif isinstance(leader, dict) and leader.get("name"):
            names.add(str(leader["name"]).strip())
        for r in row.get("related") or []:
            if isinstance(r, dict) and r.get("name"):
                names.add(str(r["name"]).strip())
            elif isinstance(r, str) and r.strip():
                names.add(r.strip())
        if name not in names:
            continue
        outcome = row.get("outcome") or {}
        if not isinstance(outcome, dict):
            continue
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
        # [강화] 평균만 보여주면 변동폭(리스크)이 감춰진다. 실제 투자판단에는
        # "최고 얼마까지 갔었고 최악은 얼마였는지" 범위가 평균보다 더 중요하다.
        "best": max(changes),
        "worst": min(changes),
    }


def _engine_rank_companies_by_track_record(names):
    """[강화: 관련주도 데이터 값에 근거해 도출] 후보 종목들을 실제 성과
    데이터(OUTCOME_TRACKING_DB에 쌓인 과거 등락률)로 재정렬한다.
    - 표본이 2건 이상 쌓여 실제 상승비율/평균 등락률을 계산할 수 있는 종목을
      데이터가 없는 종목보다 우선 앞으로 배치한다.
    - 데이터가 있는 종목끼리는 상승비율 → 평균 등락률 순으로 좋은 쪽을 먼저 보여준다.
    - 데이터가 아예 없는 종목들끼리는 원래 추출 순서를 그대로 유지한다
      (근거 없이 임의로 순서를 뒤섞지 않는다).
    """
    scored = []
    for idx, name in enumerate(names):
        stats = _engine_company_outcome_stats(name)
        if stats and stats.get("count", 0) >= 2:
            score = (1, stats["success_rate"], stats["avg"])
        else:
            score = (0, 0.0, 0.0)
        scored.append((score, idx, name))
    scored.sort(key=lambda x: (-x[0][0], -x[0][1], -x[0][2], x[1]))
    return [name for _, _, name in scored]


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