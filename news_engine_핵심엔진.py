# -*- coding: utf-8 -*-
"""
뉴스 판정의 중심 엔진.

[재작성 배경]
이 파일은 원래 클래스 기반(NewsAnalysisEngine)의 프로토타입이었으나, 나머지
코드베이스(main_메인, admin_관리자, domestic_국내수집, overseas_해외수집,
translation_번역, schedule_일정DB)는 전부 모듈 레벨 함수(_engine_xxx) 구조로
되어 있어 서로 맞지 않았다(ImportError로 봇이 아예 기동되지 않는 원인).
이번 재작성에서 기존 클래스의 로직(단독 프로세스 락, 시황/광고 키워드 필터,
관련주 직접언급 매칭)은 그대로 함수로 옮기고, 그 위에 나머지 모듈들이 실제로
요구하는 함수/상수(GLOBAL_AND_DOMESTIC_GIANTS, _engine_fetch_rss,
_engine_process_item 등)를 새로 구현했다.

뉴스 1건의 최종 판정(관련주 선정/상용화 단계/시장전망)은 MASTER 엔진
(master_condition_manager_MASTER엔진.analyze_news)에 위임한다. 이 파일은
수집→중복방지→최근성 게이트→번역 게이트→MASTER 판정→성과추적 기록→송출로
이어지는 파이프라인(_engine_process_item)을 담당한다.
"""

import os
import re
import json
import time
import datetime
import hashlib
import logging
import threading
from collections import deque
from urllib.parse import urlparse

import requests
import feedparser

from common_공용유틸 import (
    ENGINE_HTTP_TIMEOUT,
    _engine_clean,
    _engine_log,
    _engine_parse_datetime,
    _engine_send_telegram,
    _now_kst,
    log_error,
)
from config_환경설정 import USER_AGENT
from master_condition_manager_MASTER엔진 import analyze_news
from translation_번역 import _engine_translate_foreign_item, _engine_queue_translation_retry, _engine_clear_translation_retry

try:
    import psutil
except Exception:
    psutil = None

logger = logging.getLogger("NewsBotEngine")


# ============================================================
# 🔒 단독 프로세스 실행 보장 (기존 NewsAnalysisEngine 로직 이전)
# 재배포 시 이전 프로세스가 완전히 종료되지 않은 채 새 프로세스가 뜨면
# 같은 뉴스를 중복 송출하게 되므로, 부팅 시 이전 PID를 찾아 강제 종료한다.
# psutil이 없는 환경에서는 조용히 건너뛴다(필수 의존성으로 만들지 않는다).
# ============================================================
def enforce_single_instance(lock_file="bot_process.lock"):
    if psutil is None:
        _engine_log("warning", "[단독실행] psutil 미설치로 이전 프로세스 정리를 건너뜁니다.")
        return
    current_pid = os.getpid()

    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                old_process = psutil.Process(old_pid)
                _engine_log("warning", "[강제 종료] 이전 실행 중이던 프로세스 발견 (PID: %s). 강제 종료를 수행합니다.", old_pid)
                old_process.terminate()
                old_process.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
            _engine_log("info", "이전 프로세스 정리 중 예외 발생 (무시 가능): %s", str(e)[:160])
        try:
            os.remove(lock_file)
        except Exception:
            pass

    try:
        with open(lock_file, "w", encoding="utf-8") as f:
            f.write(str(current_pid))
        _engine_log("info", "[프로세스 락 획득] 현재 봇 프로세스가 단독 실행됩니다. (PID: %s)", current_pid)
    except Exception as e:
        _engine_log("error", "프로세스 락 파일 생성 실패: %s", str(e)[:160])


# ============================================================
# 감시 대상 기업/키워드
# ============================================================
GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성SDI", "삼성바이오로직스",
    "현대차", "기아", "한화에어로스페이스", "한화오션", "한화시스템",
    "NAVER", "카카오", "에코프로", "에코프로비엠", "SK이노베이션",
    "포스코퓨처엠", "포스코홀딩스", "두산에너빌리티", "HD현대중공업",
    "LG화학", "셀트리온", "SK바이오팜", "한미반도체", "HPSP", "두산로보틱스",
    "LIG넥스원", "KAI", "SK오션플랜트",
]

# 해외(미국) 뉴스 관련성 판단에 쓰이는 글로벌 기업 키워드
GLOBAL_COMPANY_KEYWORDS = {
    "Nvidia", "NVIDIA", "AMD", "Micron", "Broadcom", "TSMC", "Apple",
    "Microsoft", "Amazon", "Meta", "Alphabet", "Google", "Tesla",
    "Palantir", "ARM", "Intel", "OpenAI", "SoftBank", "Foxconn", "Qualcomm",
    "Samsung", "SK Hynix",
}

# 미국장 브리핑 핵심 감시 티커(overseas 모듈의 US_BRIEFING_WATCHLIST와 정합)
UNIQUE_TARGET = {
    "NVDA", "AMD", "AVGO", "MU", "TSM", "AAPL", "MSFT", "AMZN",
    "META", "GOOGL", "TSLA", "PLTR", "ARM", "INTC",
}

# 시황/광고성 제목 필터(기존 analyze_and_extract 로직 유지)
MACRO_AD_KEYWORDS = ["시황", "마감", "브리핑", "라이브", "순환매", "급락", "급등주 점검"]

# "과거 유사 사례" 매칭에 쓰이는 임계값 (overseas._us_close_briefing에서 사용)
HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))
_HISTORICAL_CACHE_MAX = int(os.environ.get("NEWS_BOT_HISTORICAL_CACHE_MAX", "5000"))
_engine_historical_cache = []  # [{"text","title","link","published_dt","source"}, ...]

RECENT_WINDOW_MIN = int(os.environ.get("NEWS_BOT_RECENT_WINDOW_MIN", "60"))

SEEN_DB_FILE = os.environ.get("NEWS_BOT_SEEN_DB", "news_bot_seen.txt")
EXTENDED_STATE_FILE = os.environ.get("NEWS_BOT_EXTENDED_STATE", "news_bot_extended_state.json")
SEEN_MAX_KEEP = int(os.environ.get("NEWS_BOT_SEEN_MAX_KEEP", "20000"))

_engine_seen_hashes = set()
_engine_seen_order = deque()

# ============================================================
# [콜드스타트 강제금지 — 재작성 배경]
# Render 같은 컨테이너 배포 환경은 로컬 디스크가 "임시(ephemeral)"인 경우가
# 많다. 재배포될 때마다 컨테이너가 통째로 새로 뜨면서 SEEN_DB_FILE(중복방지
# 이력)이 흔적도 없이 사라질 수 있고, 누가 실수로/의도로 파일을 직접 지워도
# 똑같은 상태가 된다. 예전 코드는 "이력 파일이 없으면 그냥 빈 이력으로
# 시작"했는데, 그러면 그 순간 RECENT_WINDOW_MIN(기본 60분) 안의 모든 뉴스를
# "처음 보는 뉴스"로 오판해서 이미 보냈던 걸 그대로 다시 쏟아낸다.
# "파일을 지워도(=재배포로 사라져도) 계속 메시지가 온다"는 증상의 실제 원인이
# 바로 이 "파일이 있어야만 정상 인식한다"는 설계였다.
#
# [수정] 이력 파일이 없는 상태로 부팅하면(콜드스타트) 일정 시간(기본 10분)
# 동안 "이력만 쌓고 송출은 강제로 금지"하는 워밍업 모드로 전환한다. 이 구간엔
# force_send(무조건 채널)도 예외 없이 막는다 — 목적 자체가 "파일이 깨졌을 때
# 예전 로직이 멋대로 실행되지 않게" 막는 것이므로 예외를 두지 않는다. 워밍업이
# 끝나면(또는 관리자가 _engine_force_end_cold_start()로 강제 해제하면) 완전히
# 정상 동작으로 복귀한다.
# ============================================================
COLD_START_GRACE_MIN = float(os.environ.get("NEWS_BOT_COLD_START_GRACE_MIN", "10"))

_engine_cold_start_active = False
_engine_cold_start_deadline = 0.0


# ============================================================
# 부팅 시 1회 호출되는 상태 로드 함수 (main_메인._engine_main_loop에서 호출)
# ============================================================
def _engine_load_seen():
    """이전에 이미 송출/처리한 뉴스의 해시 이력을 불러온다. 재시작해도 같은
    뉴스를 중복 송출하지 않기 위함이다. 동시에 좀비 프로세스 정리도 수행한다.
    이력 파일 자체가 없으면(콜드스타트) 워밍업 강제금지 모드를 켠다."""
    global _engine_seen_hashes, _engine_seen_order, _engine_cold_start_active, _engine_cold_start_deadline
    enforce_single_instance()
    had_history_file = os.path.exists(SEEN_DB_FILE)
    if had_history_file:
        try:
            with open(SEEN_DB_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    h = line.strip()
                    if h:
                        _engine_seen_hashes.add(h)
                        _engine_seen_order.append(h)
            _engine_log("info", "[중복방지] 과거 처리이력 로드 완료 | %d건", len(_engine_seen_hashes))
        except Exception as e:
            log_error("중복방지 DB 로드", e)
    while len(_engine_seen_order) > SEEN_MAX_KEEP:
        old = _engine_seen_order.popleft()
        _engine_seen_hashes.discard(old)

    if not had_history_file:
        # [콜드스타트 감지] 이력 파일이 없다 = 재배포로 로컬 디스크가 초기화됐거나
        # 누군가 파일을 직접 지운 상태. 예전처럼 "빈 이력 = 전부 신규"로 취급하지
        # 않고, 강제로 송출 금지 워밍업 구간을 연다.
        _engine_cold_start_active = True
        _engine_cold_start_deadline = time.time() + COLD_START_GRACE_MIN * 60
        _engine_log(
            "warning",
            "[콜드스타트 감지] 중복방지 이력 파일이 없어 %d분간 송출을 강제 금지합니다 "
            "(이력만 쌓고 대기 — 과거 뉴스 재송출 방지). 필요시 관리자가 강제 해제할 수 있습니다.",
            int(COLD_START_GRACE_MIN),
        )
    else:
        _engine_cold_start_active = False


def _engine_cold_start_check():
    """현재 워밍업(콜드스타트) 강제금지 구간인지 확인한다. 시간이 지났으면
    자동으로 해제하고 정상 송출로 돌아간다."""
    global _engine_cold_start_active
    if not _engine_cold_start_active:
        return False
    if time.time() >= _engine_cold_start_deadline:
        _engine_cold_start_active = False
        _engine_log("info", "[콜드스타트 해제] 워밍업 시간 종료 | 정상 송출 재개")
        return False
    return True


def _engine_force_end_cold_start():
    """[강제종료 명령] 관리자가 상황을 확인한 뒤 워밍업을 즉시 끝내고 정상
    송출로 강제 전환한다. admin_관리자.py의 /워밍업해제 명령이 이 함수를 호출한다."""
    global _engine_cold_start_active
    was_active = _engine_cold_start_active
    _engine_cold_start_active = False
    if was_active:
        _engine_log("warning", "[콜드스타트 강제해제] 관리자 명령으로 예정 시간 전에 워밍업을 종료했습니다.")
    return was_active


def _engine_load_extended_state():
    """확장 상태(과거 유사사례 캐시 등)를 디스크에서 복원한다.
    파일이 없거나 손상돼도 조용히 빈 상태로 시작한다.
    [버그 수정] published_dt는 저장 시 ISO 문자열로 바꿔 기록되므로, 불러올 때
    다시 datetime 객체로 되돌린다(변환 실패 시 None으로 안전하게 대체)."""
    if not os.path.exists(EXTENDED_STATE_FILE):
        return
    try:
        with open(EXTENDED_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f) or {}
        cached = state.get("historical_cache", []) or []
        restored = []
        for row in cached[-_HISTORICAL_CACHE_MAX:]:
            row = dict(row)
            pd = row.get("published_dt")
            if isinstance(pd, str):
                try:
                    row["published_dt"] = datetime.datetime.fromisoformat(pd)
                except Exception:
                    row["published_dt"] = None
            restored.append(row)
        _engine_historical_cache.clear()
        _engine_historical_cache.extend(restored)
        _engine_log("info", "[확장상태] 로드 완료 | 과거사례=%d건", len(_engine_historical_cache))
    except Exception as e:
        log_error("확장상태 로드", e)


def _engine_save_extended_state():
    """[버그 수정] 이 함수는 정의만 되어 있고 아무 데서도 호출되지 않아 과거사례
    캐시가 재시작하면 전부 사라졌다. 게다가 호출해도 캐시 안의 published_dt가
    datetime 객체 그대로라 json.dump()가 'Object of type datetime is not JSON
    serializable'로 매번 조용히(try/except에 먹혀서) 실패했다. ISO 문자열로
    바꿔서 저장하도록 고치고, main_메인._engine_cycle()에서 주기마다 호출하도록
    연결했다(그래야 재배포/재시작에도 과거사례 캐시가 유지된다)."""
    try:
        serializable_cache = []
        for item in _engine_historical_cache[-_HISTORICAL_CACHE_MAX:]:
            row = dict(item)
            pd = row.get("published_dt")
            row["published_dt"] = pd.isoformat() if isinstance(pd, datetime.datetime) else pd
            serializable_cache.append(row)
        with open(EXTENDED_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"historical_cache": serializable_cache}, f, ensure_ascii=False)
    except Exception as e:
        log_error("확장상태 저장", e)


def _engine_mark_seen(item_hash):
    if item_hash in _engine_seen_hashes:
        return
    _engine_seen_hashes.add(item_hash)
    _engine_seen_order.append(item_hash)
    try:
        with open(SEEN_DB_FILE, "a", encoding="utf-8") as f:
            f.write(item_hash + "\n")
    except Exception as e:
        log_error("중복방지 DB 저장", e)
    while len(_engine_seen_order) > SEEN_MAX_KEEP:
        old = _engine_seen_order.popleft()
        _engine_seen_hashes.discard(old)


def _engine_item_hash(source, title, link):
    key = f"{source}|{_engine_clean(title)}|{str(link or '').strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ============================================================
# RSS 공용 수집기
# ============================================================
def _engine_fetch_rss(url, source):
    # [403 완화] User-Agent만 보내는 요청은 일부 매체(예: 한국경제)에서 스크래핑
    # 봇으로 간주해 차단하는 경우가 있다. Accept/Accept-Language/Referer까지
    # 갖춘 일반 브라우저에 가까운 헤더로 보내 오탐 차단을 줄인다. 그래도 IP나
    # 요청 패턴 자체를 영구 차단 중이라면 이 수정만으로는 해결되지 않을 수 있다.
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("warning", "[RSS] %s | status=%s", source, r.status_code)
            return []
        parsed = feedparser.parse(r.content)
        out = []
        for entry in parsed.entries:
            out.append({
                "title": entry.get("title", "") or "",
                "link": entry.get("link", "") or "",
                "summary": entry.get("summary", "") or entry.get("description", "") or "",
                "published": entry.get("published", "") or entry.get("updated", "") or "",
            })
        return out
    except Exception as e:
        log_error("RSS 수집", e, source=source, url=url)
        return []


def _engine_entry_published(entry):
    return entry.get("published", "") or entry.get("updated", "") or ""


# ============================================================
# 메시지 포맷터
# [형식 통일] 실제 운영 포맷(📌 제목 : 한줄설명 / 🏷 관련종목 / 🔎 요약(✔️)
# + 데이터 누적 기반 분석/전망)에 맞춰 재작성. 필드는 전부 MASTER 결과
# (result)와 성과추적/AI분석(accumulated_summary_msg)에서만 가져오며,
# 근거 없는 값(예: 계열사/그룹 소속 같은 미보유 데이터)은 지어내지 않고
# 실제로 있는 데이터(관련종목·근거)로만 채운다.
# ============================================================
def _accumulated_block_to_bullets(accumulated_summary_msg):
    """outcome_tracking/ml_learning이 만든 '•' 불릿 블록을 동일한 ✔️ 불릿
    스타일로 통일해, 요약 섹션과 시각적으로 한 흐름처럼 이어지게 한다."""
    if not accumulated_summary_msg:
        return []
    out = []
    for raw in accumulated_summary_msg.split("\n"):
        if not raw.strip():
            continue
        is_sub_bullet = bool(re.match(r"^\s{2,}-\s*", raw))  # 들여쓰기 판별은 strip 전에 해야 한다
        line = raw.strip()
        if line.startswith(("🤖", "📊")):
            out.append(f"\n{line}")
            continue
        if is_sub_bullet:
            line = re.sub(r"^-\s*", "", line)
            out.append(f"    ↳ {line}")
        else:
            line = re.sub(r"^[•\-]\s*", "", line)
            out.append(f"✔️ {line}")
    return out


def _format_news_message(source, title, result, related_names, accumulated_summary_msg, link=""):
    key_points = result.get("key_points") or []
    outlook = result.get("outlook") or []
    schedule = result.get("schedule") or ""
    evidence = result.get("evidence") or []
    related_str = ", ".join(related_names) if related_names else "관련 종목 확인 필요"

    # 📌 제목 뒤에 붙는 한줄 설명: MASTER가 뽑은 핵심포인트/근거문장 중 첫 문장을
    # 그대로 쓴다(제목 재진술 방지 로직은 MASTER가 이미 처리했으므로 신뢰).
    lead_sentence = (key_points[0] if key_points else (evidence[0] if evidence else "")).strip()

    lines = [
        f"📰 [{source}] 신규 🕐 {_now_kst().strftime('%H:%M')}",
        "",
        f"📌 {title}" + (f" : {lead_sentence}" if lead_sentence else ""),
        "",
        f"🏷 관련종목 : {related_str}",
    ]

    # [버그 수정] link 인자가 아예 없어 원문 링크가 어떤 메시지에도 붙지 못했다.
    # 이제 실제 기사 링크가 있을 때만 노출한다(없으면 줄 자체를 생략).
    link = str(link or "").strip()
    if link:
        lines.append("")
        lines.append(f"🔗 원문 : {link}")

    # [버그 수정] key_points가 1개뿐이면 그 1개는 이미 위 lead_sentence로 다 써버려서
    # key_points[1:]가 빈 리스트가 되는데, 그래도 "🔎 요약" 헤더는 무조건 찍혀서
    # 내용 없는 요약란이 노출됐다. 실제로 보여줄 불릿이 있을 때만 헤더를 붙인다.
    summary_points = key_points[1:] if lead_sentence == (key_points[0] if key_points else None) else key_points
    if summary_points:
        lines.append("")
        lines.append("🔎 요약")
        lines.append("")
        for kp in summary_points:
            lines.append(f"✔️ {kp}")

    if schedule:
        lines.append("")
        lines.append(f"📅 일정 : {schedule}")

    if outlook:
        lines.append("")
        lines.append("🧠 시장 전망")
        for o in outlook:
            lines.append(f"✔️ {o}")

    bullet_block = _accumulated_block_to_bullets(accumulated_summary_msg)
    if bullet_block:
        lines.append("")
        lines.extend(bullet_block)

    return "\n".join(lines)


# ============================================================
# 📊 [사이클 통계 복원] main_메인._engine_cycle()이 매 주기 끝에
# "확인=.. | 이미본뉴스=.. | 콜드스타트=.. | 시간초과=.. | 번역실패=.. |
# MASTER오류=.. | MASTER미확정=.. | 필터링=.. | 전송성공=.. | 전송실패=.."
# 형식으로 그 주기 동안 _engine_process_item이 각 분기에서 몇 건씩
# 처리했는지 요약해 로그로 남긴다. 이 통계 자체는 판정에 영향을 주지
# 않는 순수 관측용 카운터이며, main_메인.py가 매 주기 시작 시
# _engine_reset_cycle_stats()로 0으로 초기화하고, 주기 끝에
# _engine_cycle_stats_summary()로 문자열을 얻어 로그에 붙인다.
# ============================================================
_CYCLE_STATS_FIELDS = [
    "checked", "already_seen", "cold_start", "timeout", "translate_fail",
    "master_error", "master_unconfirmed", "filtered", "sent_success", "sent_fail",
]
_CYCLE_STATS_LABELS = {
    "checked": "확인", "already_seen": "이미본뉴스", "cold_start": "콜드스타트",
    "timeout": "시간초과", "translate_fail": "번역실패", "master_error": "MASTER오류",
    "master_unconfirmed": "MASTER미확정", "filtered": "필터링",
    "sent_success": "전송성공", "sent_fail": "전송실패",
}
_engine_cycle_stats = {k: 0 for k in _CYCLE_STATS_FIELDS}
_CYCLE_STATS_LOCK = threading.Lock()


def _engine_reset_cycle_stats():
    """매 주기 시작 시 호출. 이전 주기의 누적치를 0으로 되돌린다."""
    global _engine_cycle_stats
    with _CYCLE_STATS_LOCK:
        _engine_cycle_stats = {k: 0 for k in _CYCLE_STATS_FIELDS}


def _engine_bump_cycle_stat(key):
    with _CYCLE_STATS_LOCK:
        _engine_cycle_stats[key] = _engine_cycle_stats.get(key, 0) + 1


def _engine_cycle_stats_summary():
    """[주기 완료] 로그 한 줄에 그대로 붙일 수 있는 요약 문자열을 만든다."""
    with _CYCLE_STATS_LOCK:
        snapshot = dict(_engine_cycle_stats)
    return " | ".join(f"{_CYCLE_STATS_LABELS[k]}={snapshot.get(k, 0)}" for k in _CYCLE_STATS_FIELDS)


# ============================================================
# 핵심 파이프라인: 뉴스/공시/채널/영상 후보 1건을 판정하고 확정되면 송출한다.
# 반환값 True = 이번 호출로 신규 송출/기록을 했음.
# ============================================================
def _engine_process_item(source, title, link, published, extra, force_send=False):
    _engine_bump_cycle_stat("checked")
    try:
        title = _engine_clean(title)
        extra = _engine_clean(extra)
        link = str(link or "").strip()
        if not title:
            return False

        item_hash = _engine_item_hash(source, title, link)
        if item_hash in _engine_seen_hashes:
            _engine_bump_cycle_stat("already_seen")
            return False

        if _engine_cold_start_check():
            # [강제금지] 콜드스타트 워밍업 구간에는 force_send(무조건) 채널이라도
            # 예외 없이 막는다. 이력만 쌓아서, 워밍업이 끝난 뒤에는 이 항목을
            # "이미 처리한 뉴스"로 정상 인식하게 만든다(재송출 방지).
            _engine_mark_seen(item_hash)
            _engine_bump_cycle_stat("cold_start")
            _engine_log("debug", "[콜드스타트 워밍업] 송출 보류·이력만 기록 | %s", title[:60])
            return False

        # 최근성 게이트: 발행시각을 알 수 없는 소스(DART 등)는 게이트를 건너뛰고
        # 수집 단계의 날짜 범위 제한 + 중복방지에 의존한다.
        pub_dt = _engine_parse_datetime(published) if published else None
        now = _now_kst()
        if pub_dt is not None:
            age_min = (now - pub_dt).total_seconds() / 60.0
            if age_min > RECENT_WINDOW_MIN or age_min < -10:
                _engine_mark_seen(item_hash)
                _engine_bump_cycle_stat("timeout")
                return False

        # 외신 번역 게이트: 실패하면 원문을 절대 송출하지 않는다(translation_번역.py 원칙).
        ko_title, ko_extra, translate_ok = _engine_translate_foreign_item(source, title, extra)
        if not translate_ok:
            # [버그 수정] 여기서 곧바로 _engine_mark_seen()으로 영구 처리완료 처리를
            # 해버리면 번역 재시도 큐(translation_번역._engine_retry_translation_queue)가
            # 영원히 이 항목을 다시 볼 수 없어, 429 등 일시적 번역 실패가 전부
            # 영구 유실로 이어졌다. 대신 재시도 큐에 등록하고, item_hash는 아직
            # seen 처리하지 않아 다음 주기 재시도가 정상적으로 이 함수를 다시 탈 수 있게 한다.
            _engine_queue_translation_retry(source, title, link, published, extra)
            _engine_bump_cycle_stat("translate_fail")
            return False
        _engine_clear_translation_retry(link, title, source)

        body_text = ko_extra or ko_title
        full_text = f"{ko_title} {body_text}"

        # [필터 확장] 기존엔 GLOBAL_AND_DOMESTIC_GIANTS(하드코딩 27개 대형주)에 이름이
        # 있어야만 후보로 잡혀서, 중소형주 위주 소스(CS타임즈/더구루/폴리트폴 등) 기사는
        # 관련종목이 거의 안 잡히고 그대로 필터링됐다. DART 상장사 전체 명단
        # (sources_external_외부연동._dart_corp_code_map, 약 2천여 개)을 후보 추출에
        # 사용해 코스피/코스닥 상장사 전체로 커버리지를 넓힌다. 27개 리스트 자체는
        # 다른 곳(네이버 검색 쿼리 등)에서 계속 쓰이므로 상수는 남겨두되, 후보 판정에는
        # 더 이상 그 27개로 제한하지 않는다.
        # 순환 임포트 회피를 위해 모듈째 지연 임포트하고, 매번 모듈 속성으로 접근한다
        # (from ... import _dart_corp_code_map 형태는 딕셔너리가 나중에 재할당되면
        # 이 시점의 옛 빈 딕셔너리를 계속 참조하게 되어 최신 매핑을 못 본다).
        candidates = []
        matched_names = set()
        for company in GLOBAL_AND_DOMESTIC_GIANTS:
            if company in full_text:
                candidates.append({
                    "name": company,
                    "reason": f"기사 본문에 '{company}'가 직접 언급됨",
                    "direct": True,
                    "domestic_listed": True,
                })
                matched_names.add(company)
        try:
            import sources_external_외부연동
            sources_external_외부연동._dart_load_corp_code_map()
            for corp_name in sources_external_외부연동._dart_corp_code_map:
                # 한두 글자짜리 이름은 본문 다른 단어 속에 우연히 포함돼 오탐을 낼
                # 위험이 커서 제외한다.
                if len(corp_name) < 2 or corp_name in matched_names:
                    continue
                if corp_name in full_text:
                    candidates.append({
                        "name": corp_name,
                        "reason": f"기사 본문에 '{corp_name}'가 직접 언급됨",
                        "direct": True,
                        "domestic_listed": True,
                    })
                    matched_names.add(corp_name)
        except Exception as e:
            log_error("DART 상장사 후보 확장", e)

        evidence = [ln.strip() for ln in re.split(r"(?<=[.!?])\s+|\n", body_text) if ln.strip()][:5]

        try:
            result = analyze_news(
                title=ko_title, body=body_text, source=str(source), link=link,
                candidates=candidates, schedule="", evidence=evidence,
            )
        except Exception as e:
            log_error("MASTER 분석 실패", e, source=source, title=ko_title[:80])
            _engine_mark_seen(item_hash)
            _engine_bump_cycle_stat("master_error")
            return False

        if not result.get("locked") and not force_send:
            _engine_log("debug", "[MASTER 검증 미통과] %s | %s", ko_title[:60], result.get("validation_errors"))
            _engine_mark_seen(item_hash)
            _engine_bump_cycle_stat("master_unconfirmed")
            return False

        leader = result.get("leader") or {}
        observe = result.get("observe") or []
        related = result.get("related") or []

        related_names = []
        if leader.get("name"):
            related_names.append(leader["name"])
        for o in observe:
            nm = o.get("name")
            if nm and nm not in related_names:
                related_names.append(nm)
        if not related_names and related:
            related_names = [r.get("name") for r in related if r.get("name")]

        macro_kw_hit = any(kw in ko_title for kw in MACRO_AD_KEYWORDS)
        news_value_low = result.get("news_value") == "낮음"
        category = str(source)
        reason = result.get("analysis") or " ".join(result.get("outlook") or [])[:300] or "MASTER 분석 결과"

        # 과거사례 캐시 누적 (macro/ad 여부와 무관하게 브리핑 근거자료로 계속 쌓는다)
        cache_row = {
            "text": full_text[:600], "title": ko_title, "link": link,
            "published_dt": pub_dt or now, "source": str(source),
        }
        _engine_historical_cache.append(cache_row)
        if len(_engine_historical_cache) > _HISTORICAL_CACHE_MAX:
            del _engine_historical_cache[: len(_engine_historical_cache) - _HISTORICAL_CACHE_MAX]

        # [버그 수정] overseas_해외수집.py의 미장 개장/장중/마감 브리핑은
        # "원인: ○○" · MSCI 재료 · 강한 재료 섹션을 전부 _US_BRIEFING_NEWS_MEMORY에서
        # 찾는데, 그 리스트가 선언만 되어 있고 어디서도 채워지지 않아 브리핑에는
        # 항상 "확인된 뉴스 없음"만 나왔다. overseas가 news_engine을 top-level에서
        # import하므로 순환 임포트를 피하려면 여기서는 지연 import로 접근해야 한다.
        try:
            from overseas_해외수집 import _US_BRIEFING_NEWS_MEMORY, _US_BRIEFING_LOCK
            with _US_BRIEFING_LOCK:
                _US_BRIEFING_NEWS_MEMORY.append(dict(cache_row))
                if len(_US_BRIEFING_NEWS_MEMORY) > _HISTORICAL_CACHE_MAX:
                    del _US_BRIEFING_NEWS_MEMORY[: len(_US_BRIEFING_NEWS_MEMORY) - _HISTORICAL_CACHE_MAX]
        except Exception as e:
            log_error("미장 브리핑 뉴스메모리 갱신 실패", e)

        # [필터 완화] 기존엔 related_names(관련종목)가 하나도 없으면 뉴스가치와 무관하게
        # 무조건 필터링했다. 이제 관련종목이 없어도 MASTER가 뉴스가치를 "높음"으로
        # 판정했다면(정책/산업 이슈 등 종목 콕 집기 어려운 굵직한 소재) 통과시킨다.
        news_value_high = result.get("news_value") == "높음"
        # [강한재료무조건통과 / 특징주단독속보무조건통과] MASTER._force_pass가 True면
        # (수주·계약·특허·M&A 등 강한 재료 키워드, 또는 특징주/단독속보 + 주식시장 문맥)
        # 관련종목 매칭 여부·뉴스가치 점수·macro_kw_hit(시황/마감 등)과 무관하게
        # 무조건 통과시킨다.
        force_pass = bool(result.get("force_pass"))
        is_macro_or_ad = (not force_pass) and (
            macro_kw_hit or news_value_low or (not related_names and not news_value_high)
        )
        if force_pass and (macro_kw_hit or news_value_low or not related_names):
            _engine_log("info", "[강제통과] %s | %s", ko_title[:60], result.get("force_pass_reason", ""))
        if is_macro_or_ad and not force_send:
            # 필터링되더라도 성과추적 DB에는 "필터링됨" 이력으로 남겨 학습 데이터로 쓴다.
            try:
                from outcome_tracking_성과추적 import _engine_record_outcome_tracking
                _engine_record_outcome_tracking(
                    title=ko_title, category=category, related_stocks=related_names,
                    reason=reason, evidence=result.get("evidence") or [],
                )
            except Exception as e:
                log_error("성과추적 기록 실패(필터링)", e, title=ko_title[:80])
            _engine_mark_seen(item_hash)
            _engine_bump_cycle_stat("filtered")
            _engine_log("debug", "[필터링] Macro/Ad 또는 관련주 없음 | %s", ko_title[:60])
            return False

        accumulated_summary_msg = ""
        try:
            from outcome_tracking_성과추적 import _engine_record_outcome_tracking
            accumulated_summary_msg = _engine_record_outcome_tracking(
                title=ko_title, category=category, related_stocks=related_names,
                reason=reason, evidence=result.get("evidence") or [],
            )
        except Exception as e:
            log_error("성과추적 기록 실패", e, title=ko_title[:80])

        message = _format_news_message(source, ko_title, result, related_names, accumulated_summary_msg, link=link)
        sent = _engine_send_telegram(message)
        _engine_mark_seen(item_hash)
        if sent:
            _engine_bump_cycle_stat("sent_success")
            _engine_log("info", "[송출] %s | %s", source, ko_title[:80])
            # [버그 수정] 일정DB(schedule_일정DB.py)가 어디서도 호출되지 않아
            # 죽은 코드였다. 실시간 확정 송출 시점에 미래 일정 후보를 추출해 누적한다.
            # 일정 추출 실패가 뉴스 송출 자체를 막지 않도록 예외를 흡수한다.
            try:
                from schedule_일정DB import _schedule_add_news_item
                _schedule_add_news_item(source, ko_title, body_text, link, published, companies=related_names)
            except Exception as e:
                log_error("일정DB 누적 실패", e, title=ko_title[:80])
            return True
        _engine_bump_cycle_stat("sent_fail")
        return False
    except Exception as e:
        log_error("뉴스 항목 처리 중 미확인 오류", e, source=source, title=str(title)[:80])
        _engine_bump_cycle_stat("master_error")
        return False
