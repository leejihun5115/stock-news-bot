# -*- coding: utf-8 -*-
"""
뉴스 판정의 중심 엔진.

[뉴스우선 테스트 모드]
- 기존 seen DB 704건을 일시적으로 무시한다.
- 콜드스타트 송출 금지를 일시 우회한다.
- 최근성 기본 범위를 24시간으로 넓힌다.
- MASTER는 삭제하지 않고 분석만 수행한다. locked=False여도 송출한다.
- 관련주 없음/시황/낮은 뉴스가치 필터를 일시 우회한다.
- 목적: "RSS 수집은 되는데 Telegram 신규전송=0" 문제를 먼저 분리 진단한다.

[수정본]
- seen 등록은 실제 Telegram 전송 성공 후에만 수행한다.
- 콜드스타트/시간초과/MASTER 오류/MASTER 미확정/필터링/번역 실패는
  영구 seen 처리하지 않는다.
- Telegram 전송 실패도 seen 처리하지 않는다.
- 번역 실패는 기존 재시도 큐를 그대로 사용한다.
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


GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성SDI", "삼성바이오로직스",
    "현대차", "기아", "한화에어로스페이스", "한화오션", "한화시스템",
    "NAVER", "카카오", "에코프로", "에코프로비엠", "SK이노베이션",
    "포스코퓨처엠", "포스코홀딩스", "두산에너빌리티", "HD현대중공업",
    "LG화학", "셀트리온", "SK바이오팜", "한미반도체", "HPSP", "두산로보틱스",
    "LIG넥스원", "KAI", "SK오션플랜트",
]

GLOBAL_COMPANY_KEYWORDS = {
    "Nvidia", "NVIDIA", "AMD", "Micron", "Broadcom", "TSMC", "Apple",
    "Microsoft", "Amazon", "Meta", "Alphabet", "Google", "Tesla",
    "Palantir", "ARM", "Intel", "OpenAI", "SoftBank", "Foxconn", "Qualcomm",
    "Samsung", "SK Hynix",
}

UNIQUE_TARGET = {
    "NVDA", "AMD", "AVGO", "MU", "TSM", "AAPL", "MSFT", "AMZN",
    "META", "GOOGL", "TSLA", "PLTR", "ARM", "INTC",
}

MACRO_AD_KEYWORDS = ["시황", "마감", "브리핑", "라이브", "순환매", "급락", "급등주 점검"]

HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))
_HISTORICAL_CACHE_MAX = int(os.environ.get("NEWS_BOT_HISTORICAL_CACHE_MAX", "5000"))
_engine_historical_cache = []

RECENT_WINDOW_MIN = int(os.environ.get("NEWS_BOT_RECENT_WINDOW_MIN", "1440"))  # 테스트: 24시간

SEEN_DB_FILE = os.environ.get("NEWS_BOT_SEEN_DB", "news_bot_seen.txt")
EXTENDED_STATE_FILE = os.environ.get("NEWS_BOT_EXTENDED_STATE", "news_bot_extended_state.json")
SEEN_MAX_KEEP = int(os.environ.get("NEWS_BOT_SEEN_MAX_KEEP", "20000"))

_engine_seen_hashes = set()
_engine_seen_order = deque()

COLD_START_GRACE_MIN = float(os.environ.get("NEWS_BOT_COLD_START_GRACE_MIN", "10"))
_engine_cold_start_active = False
_engine_cold_start_deadline = 0.0


def _engine_load_seen():
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
        _engine_cold_start_active = True
        _engine_cold_start_deadline = time.time() + COLD_START_GRACE_MIN * 60
        _engine_log(
            "warning",
            "[콜드스타트 감지] 중복방지 이력 파일이 없어 %d분간 송출을 강제 금지합니다 "
            "(이력은 기록하지 않고 대기). 필요시 관리자가 강제 해제할 수 있습니다.",
            int(COLD_START_GRACE_MIN),
        )
    else:
        _engine_cold_start_active = False


def _engine_cold_start_check():
    global _engine_cold_start_active
    if not _engine_cold_start_active:
        return False
    if time.time() >= _engine_cold_start_deadline:
        _engine_cold_start_active = False
        _engine_log("info", "[콜드스타트 해제] 워밍업 시간 종료 | 정상 송출 재개")
        return False
    return True


def _engine_force_end_cold_start():
    global _engine_cold_start_active
    was_active = _engine_cold_start_active
    _engine_cold_start_active = False
    if was_active:
        _engine_log("warning", "[콜드스타트 강제해제] 관리자 명령으로 예정 시간 전에 워밍업을 종료했습니다.")
    return was_active


def _engine_load_extended_state():
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
    """실제 Telegram 전송 성공이 확인된 항목만 호출해야 한다."""
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


def _engine_fetch_rss(url, source):
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


def _accumulated_block_to_bullets(accumulated_summary_msg):
    if not accumulated_summary_msg:
        return []
    out = []
    for raw in accumulated_summary_msg.split("\n"):
        if not raw.strip():
            continue
        is_sub_bullet = bool(re.match(r"^\s{2,}-\s*", raw))
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

    lead_sentence = (key_points[0] if key_points else (evidence[0] if evidence else "")).strip()

    lines = [
        f"📰 [{source}] 신규 🕐 {_now_kst().strftime('%H:%M')}",
        "",
        f"📌 {title}" + (f" : {lead_sentence}" if lead_sentence else ""),
        "",
        f"🏷 관련종목 : {related_str}",
    ]

    link = str(link or "").strip()
    if link:
        lines.append("")
        lines.append(f"🔗 원문 : {link}")

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
    global _engine_cycle_stats
    with _CYCLE_STATS_LOCK:
        _engine_cycle_stats = {k: 0 for k in _CYCLE_STATS_FIELDS}


def _engine_bump_cycle_stat(key):
    with _CYCLE_STATS_LOCK:
        _engine_cycle_stats[key] = _engine_cycle_stats.get(key, 0) + 1


def _engine_cycle_stats_summary():
    with _CYCLE_STATS_LOCK:
        snapshot = dict(_engine_cycle_stats)
    return " | ".join(f"{_CYCLE_STATS_LABELS[k]}={snapshot.get(k, 0)}" for k in _CYCLE_STATS_FIELDS)


def _engine_process_item(source, title, link, published, extra, force_send=False):
    _engine_bump_cycle_stat("checked")
    try:
        title = _engine_clean(title)
        extra = _engine_clean(extra)
        link = str(link or "").strip()
        if not title:
            return False

        item_hash = _engine_item_hash(source, title, link)
        # [뉴스우선 테스트] 기존 seen DB의 704건도 다시 처리한다.
        # 정상 송출 확인 전까지 중복방지를 일시 우회한다.
        if False and item_hash in _engine_seen_hashes:
            _engine_bump_cycle_stat("already_seen")
            return False

        if _engine_cold_start_check():
            # [뉴스우선 테스트] 콜드스타트 송출 금지를 일시 해제한다.
            # 기존 뉴스도 실제 Telegram까지 도달하는지 확인하기 위한 테스트 모드.
            _engine_log("info", "[뉴스우선 테스트] 콜드스타트 제한 우회 | %s", title[:60])

        pub_dt = _engine_parse_datetime(published) if published else None
        now = _now_kst()
        if pub_dt is not None:
            age_min = (now - pub_dt).total_seconds() / 60.0
            if age_min > RECENT_WINDOW_MIN or age_min < -10:
                # 중요: 시간초과도 seen 처리하지 않는다.
                # 같은 뉴스가 다음 주기에 최신성 조건을 만족할 가능성을 보존한다.
                _engine_bump_cycle_stat("timeout")
                return False

        ko_title, ko_extra, translate_ok = _engine_translate_foreign_item(source, title, extra)
        if not translate_ok:
            # seen 처리하지 않고 번역 재시도 큐에 남긴다.
            _engine_queue_translation_retry(source, title, link, published, extra)
            _engine_bump_cycle_stat("translate_fail")
            return False
        _engine_clear_translation_retry(link, title, source)

        body_text = ko_extra or ko_title
        full_text = f"{ko_title} {body_text}"

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
            # 중요: MASTER 오류도 seen 처리하지 않는다.
            _engine_bump_cycle_stat("master_error")
            return False

        if not result.get("locked") and not force_send:
            # [뉴스우선 테스트] MASTER 미확정이어도 뉴스 송출을 계속한다.
            # MASTER 자체는 삭제하지 않고 분석 결과만 참고용으로 유지한다.
            _engine_log(
                "info",
                "[뉴스우선 테스트] MASTER 미확정이지만 송출 진행 | %s | %s",
                ko_title[:60],
                result.get("validation_errors"),
            )

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

        cache_row = {
            "text": full_text[:600], "title": ko_title, "link": link,
            "published_dt": pub_dt or now, "source": str(source),
        }
        _engine_historical_cache.append(cache_row)
        if len(_engine_historical_cache) > _HISTORICAL_CACHE_MAX:
            del _engine_historical_cache[: len(_engine_historical_cache) - _HISTORICAL_CACHE_MAX]

        try:
            from overseas_해외수집 import _US_BRIEFING_NEWS_MEMORY, _US_BRIEFING_LOCK
            with _US_BRIEFING_LOCK:
                _US_BRIEFING_NEWS_MEMORY.append(dict(cache_row))
                if len(_US_BRIEFING_NEWS_MEMORY) > _HISTORICAL_CACHE_MAX:
                    del _US_BRIEFING_NEWS_MEMORY[: len(_US_BRIEFING_NEWS_MEMORY) - _HISTORICAL_CACHE_MAX]
        except Exception as e:
            log_error("미장 브리핑 뉴스메모리 갱신 실패", e)

        news_value_high = result.get("news_value") == "높음"
        force_pass = bool(result.get("force_pass"))
        is_macro_or_ad = (not force_pass) and (
            macro_kw_hit or news_value_low or (not related_names and not news_value_high)
        )
        if force_pass and (macro_kw_hit or news_value_low or not related_names):
            _engine_log("info", "[강제통과] %s | %s", ko_title[:60], result.get("force_pass_reason", ""))
        if is_macro_or_ad and not force_send:
            # [뉴스우선 테스트] 시황/광고/관련주 없음 필터를 일시 우회한다.
            # 실제 뉴스가 Telegram에 도착하는지 먼저 확인한다.
            _engine_log(
                "info",
                "[뉴스우선 테스트] 필터 우회 송출 | %s | 관련종목=%s",
                ko_title[:60],
                related_names or "없음",
            )

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

        # 핵심 수정:
        # Telegram 전송 성공 여부를 먼저 확인한 뒤에만 seen DB에 기록한다.
        sent = _engine_send_telegram(message)

        if sent:
            _engine_mark_seen(item_hash)
            _engine_bump_cycle_stat("sent_success")
            _engine_log("info", "[송출 성공·seen 기록] %s | %s", source, ko_title[:80])
            try:
                from schedule_일정DB import _schedule_add_news_item
                _schedule_add_news_item(source, ko_title, body_text, link, published, companies=related_names)
            except Exception as e:
                log_error("일정DB 누적 실패", e, title=ko_title[:80])
            return True

        # Telegram 전송 실패: seen 기록하지 않는다.
        # 다음 주기에 다시 송출을 시도할 수 있다.
        _engine_bump_cycle_stat("sent_fail")
        _engine_log("warning", "[송출 실패·seen 미기록] %s | %s", source, ko_title[:80])
        return False

    except Exception as e:
        # 미확인 예외 역시 seen 기록하지 않는다.
        log_error("뉴스 항목 처리 중 미확인 오류", e, source=source, title=str(title)[:80])
        _engine_bump_cycle_stat("master_error")
        return False
