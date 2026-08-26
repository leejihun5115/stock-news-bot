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

# ==== module: admin (auto-split from original main.py) ====

from common_공용유틸 import BOT_TOKEN, CHAT_ID, ENGINE_HTTP_TIMEOUT, _engine_log, _now_kst, log_error
from engine_state_공유상태 import (
    _engine_cycle_lock, _engine_wake_event, _engine_list_disabled_stages,
    _engine_reset_all_stage_breakers, _engine_set_paused,
)
from news_engine_핵심엔진 import _engine_force_end_cold_start, _engine_cold_start_check
from outcome_tracking_성과추적 import _outcome_aggregate_report
from sources_external_외부연동 import _engine_backfill_dart_historical
import engine_state_공유상태


# ============================================================
# 관리자 최우선 명령 통제소 (Top-Level Control Tower)
# MASTER가 개별 뉴스 판정의 최종 두뇌라면, 이 통제소는 엔진 전체 동작을
# 관리자가 텔레그램으로 내린 '마지막 명령' 기준으로 즉시 제어하는 최상위 계층이다.
# 뉴스 수집 사이클과 완전히 분리된 별도 스레드에서 짧은 주기로 명령을 감시하므로,
# 데이터 수집 중이라도 명령 실행이 지연되지 않는다.
#
# [성공 패턴 요약 — 이 통제소가 반드시 지키는 5원칙]
# 1) 단일 진실 공급원(SSOT): 상태는 engine_state_공유상태 모듈 하나만 읽고 쓴다.
# 2) 즉시 영속화: 명령으로 바뀐 값은 그 자리에서 디스크에 원자적으로 저장한다.
#    → 재배포/재시작돼도 마지막 명령 상태가 유지된다.
# 3) 최신 명령 우선: 처리 못한 명령이 쌓여도 항상 '가장 마지막' 명령만 실행한다.
# 4) 반드시 회신: 모든 명령은 성공/실패와 무관하게 텔레그램으로 결과를 알린다.
#    → "먹혔는지 안 먹혔는지 몰라서 불안한" 상황 자체를 없앤다.
# 5) 격리 실행: 명령 감시/실행 스레드는 뉴스 수집 루프와 락을 공유하지 않는다.
#    → 수집이 멈추거나 느려져도 명령 응답은 항상 즉시 온다.
# ============================================================
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "") or CHAT_ID
ADMIN_COMMAND_PREFIX = "/"
ADMIN_COMMAND_POLL_INTERVAL = float(os.environ.get("ADMIN_COMMAND_POLL_INTERVAL", "2"))

# --- 관리자 최우선 명령 통제소 전역 상태 ---
_admin_lock = threading.Lock()
_admin_last_update_id = 0
_admin_pending_command = None      # 아직 실행되지 않은 '가장 최신' 명령만 보관 (덮어쓰기 방식)
_admin_command_event = threading.Event()   # 새 명령 도착 시 실행 스레드를 즉시 깨움
_admin_last_poll_ts = 0.0          # 감시 스레드가 마지막으로 정상 동작한 시각(하트비트)

# ============================================================
# 🧭 update_id 영속화
# ------------------------------------------------------------
# 이전 구조는 _admin_last_update_id가 메모리 변수뿐이라 재시작하면 0으로
# 초기화됐다. 그러면 재시작 직후 Telegram이 갖고 있는 과거 메시지 이력을
# 처음부터 다시 훑게 되어(오래된 /pause, /resume 등이 뒤섞여 재생),
# "분명 마지막에 resume을 눌렀는데 재시작 후엔 다시 pause처럼 보이는" 류의
# 혼란이 생길 수 있었다. offset을 디스크에 저장해 재시작해도 이어서 읽는다.
# ============================================================
_ADMIN_OFFSET_FILE = os.environ.get("NEWS_BOT_ADMIN_OFFSET_FILE", "news_bot_admin_offset.json")


def _admin_load_offset():
    global _admin_last_update_id
    try:
        if os.path.exists(_ADMIN_OFFSET_FILE):
            with open(_ADMIN_OFFSET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _admin_last_update_id = int(data.get("last_update_id", 0) or 0)
            _engine_log("info", "[관리자 명령] 마지막 update_id 복원 | %s", _admin_last_update_id)
    except Exception as e:
        log_error("관리자 offset 복원", e)


def _admin_save_offset():
    try:
        tmp = _ADMIN_OFFSET_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"last_update_id": _admin_last_update_id, "saved_at": _now_kst().isoformat()}, f, ensure_ascii=False)
        os.replace(tmp, _ADMIN_OFFSET_FILE)
    except Exception as e:
        log_error("관리자 offset 저장", e)


# ============================================================
# 관리자 최우선 명령 통제소 - 감시/실행 로직
# 흐름: (감시 스레드) 텔레그램 폴링 → 명령 감지 → 최신값으로 덮어쓰기 → 이벤트 set
#      (실행 스레드) 이벤트 대기 → 즉시 실행 → 관리자에게 결과 회신
# 두 스레드 모두 뉴스 수집 사이클과 독립적으로 동작하므로,
# 수집 작업이 진행 중이어도 관리자 명령은 대기하지 않고 처리된다.
# ============================================================
def _admin_reply(text):
    """명령 처리 결과를 관리자 채팅방으로 즉시 회신한다."""
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=ENGINE_HTTP_TIMEOUT)
        return bool(r.ok)
    except Exception as e:
        _engine_log("error", "[관리자 명령] 회신 실패 | 원인=%s", str(e)[:160])
        return False


_admin_conflict_409_count = 0
_ADMIN_CONFLICT_409_EXIT_THRESHOLD = 3  # 연속 3회(약 6초, 폴링주기 2초 기준)


_admin_process_started_at = time.time()
_ADMIN_CONFLICT_409_SELF_EXIT_WINDOW_SEC = 300  # 부팅 후 5분 이내에만 자가종료 허용


def _admin_fetch_updates():
    """Telegram getUpdates로 새 메시지만 가져온다(이미 읽은 update_id는 제외)."""
    global _admin_last_update_id, _admin_conflict_409_count
    if not BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 0, "offset": _admin_last_update_id + 1}
    try:
        r = requests.get(url, params=params, timeout=ENGINE_HTTP_TIMEOUT)
        if r.status_code == 409:
            # [원인] Telegram getUpdates는 같은 BOT_TOKEN으로 동시에 한 프로세스만
            # 폴링할 수 있다. 409는 다른 프로세스(예: 재배포 시 종료되지 않은
            # 이전 인스턴스, 혹은 이 봇에 webhook이 별도로 설정된 경우)가 이미
            # 폴링 중이라는 뜻이다. 재시도만으로는 해결 안 되므로 원인을 명확히 남긴다.
            _admin_conflict_409_count += 1
            _engine_log(
                "error",
                "[관리자 명령] getUpdates 409 Conflict (%d/%d회 연속) | 동일 BOT_TOKEN을 다른 프로세스가 "
                "이미 폴링 중입니다(중복 배포 인스턴스 또는 webhook 설정을 확인하세요).",
                _admin_conflict_409_count, _ADMIN_CONFLICT_409_EXIT_THRESHOLD,
            )
            # [버그 수정] 재배포 시 신버전 프로세스가 이미 떠서 폴링을 시작했다는
            # 뜻이므로, 이 프로세스(=구버전)는 죽지 않고 계속 돌면 뉴스/브리핑을
            # 신버전과 동시에 중복 송출한다. 409가 짧은 시간 안에 반복되면(일시적
            # 네트워크 오류가 아니라 진짜 다른 인스턴스가 살아있다는 뜻) 구버전
            # 스스로 즉시 종료해 Render의 정상적인 무중단 배포 전환을 돕는다.
            if (_admin_conflict_409_count >= _ADMIN_CONFLICT_409_EXIT_THRESHOLD
                    and (time.time() - _admin_process_started_at) <= _ADMIN_CONFLICT_409_SELF_EXIT_WINDOW_SEC):
                _engine_log(
                    "error",
                    "[구버전 자가종료] 부팅 후 %d초 이내에 다른 인스턴스가 이미 떠 있는 것으로 "
                    "확인되어 중복 송출 방지를 위해 이 프로세스를 즉시 종료합니다.",
                    _ADMIN_CONFLICT_409_SELF_EXIT_WINDOW_SEC,
                )
                os._exit(0)
            elif _admin_conflict_409_count >= _ADMIN_CONFLICT_409_EXIT_THRESHOLD:
                # 부팅한 지 오래된 상태에서 409가 계속되면 재배포 겹침이 아니라
                # webhook 오설정 등 다른 원인일 가능성이 높다. 이 경우 자가종료로
                # 무한 재시작 루프에 빠지면 오히려 서비스가 완전히 멈추므로,
                # 종료하지 않고 경고만 반복해 관리자가 원인을 직접 확인하게 한다.
                _engine_log(
                    "error",
                    "[관리자 명령] 409가 부팅 %d초 이후에도 계속됩니다 | 재배포 겹침이 아닐 수 있으니 "
                    "webhook 설정(getWebhookInfo)이나 중복 배포 여부를 직접 확인하세요.",
                    int(time.time() - _admin_process_started_at),
                )
            return []
        _admin_conflict_409_count = 0
        data = r.json() if r.ok else {}
        results = data.get("result", []) if data.get("ok") else []
    except Exception as e:
        _engine_log("error", "[관리자 명령] getUpdates 실패 | 원인=%s", str(e)[:160])
        return []
    updates = []
    for u in results:
        _admin_last_update_id = max(_admin_last_update_id, int(u.get("update_id", 0)))
        msg = u.get("message") or u.get("edited_message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = str(msg.get("text", "") or "").strip()
        if chat_id and text:
            updates.append((chat_id, text))
    if results:
        _admin_save_offset()   # 새 update_id를 즉시 디스크에 반영 (재시작해도 이어서 읽기 위함)
    return updates


def _admin_command_listener():
    """관리자 채팅방을 짧은 주기(기본 2초)로 감시한다.
    새 명령이 오면 이전에 처리되지 않은 명령이 남아있어도 무조건 최신 명령으로 덮어쓴다.
    → '마지막으로 내린 명령'만 실행 대상이 된다.
    이 함수 자체가 예외로 죽으면 명령 수신이 영구히 멈추므로, 루프 내부 예외는
    반드시 여기서 잡고 절대 밖으로 전파하지 않는다(스레드가 조용히 죽는 것을 방지)."""
    global _admin_pending_command, _admin_last_poll_ts
    _admin_load_offset()
    _engine_log("info", "[관리자 명령] 통제소 감시 시작 | ADMIN_CHAT_ID=%s | offset=%s", ADMIN_CHAT_ID, _admin_last_update_id)
    while True:
        try:
            for chat_id, text in _admin_fetch_updates():
                if not ADMIN_CHAT_ID or chat_id != str(ADMIN_CHAT_ID):
                    continue
                if not text.startswith(ADMIN_COMMAND_PREFIX):
                    continue
                with _admin_lock:
                    _admin_pending_command = text
                _admin_command_event.set()
                _engine_wake_event.set()  # 메인 루프가 sleep 중이어도 즉시 깨운다.
                _engine_log("info", "[관리자 명령] 수신 | %s", text[:120])
            _admin_last_poll_ts = time.time()
        except Exception as e:
            # [핵심] 여기서 예외를 삼키지 않고 그냥 두면 스레드가 죽고, 그 순간부터
            # "명령을 아무리 보내도 반응이 없는" 상태가 영구히 지속된다.
            # 반드시 로그만 남기고 다음 주기에 계속 폴링을 이어간다.
            _engine_log("error", "[관리자 명령] 감시 루프 오류(계속 진행) | 원인=%s", str(e)[:160])
        time.sleep(ADMIN_COMMAND_POLL_INTERVAL)


def _admin_cmd_status(arg=""):
    state = "⏸ 일시정지" if engine_state_공유상태._engine_paused else "▶️ 정상 가동"
    cold_start = "🧊 워밍업 중(송출 보류) — /워밍업해제 로 즉시 해제 가능" if _engine_cold_start_check() else "정상(워밍업 아님)"
    last = _now_kst().strftime("%Y-%m-%d %H:%M:%S") if engine_state_공유상태._engine_last_cycle_finished else "없음"
    heartbeat = "정상" if (time.time() - _admin_last_poll_ts) < max(30, ADMIN_COMMAND_POLL_INTERVAL * 5) else "⚠️ 응답 지연 의심"
    disabled = _engine_list_disabled_stages()
    if disabled:
        disabled_lines = "\n".join(
            f"  - {name} | 연속실패 {info.get('fail_count', 0)}회 | 원인: {info.get('last_error', '')[:100]}"
            for name, info in disabled.items()
        )
    else:
        disabled_lines = "  없음"
    return (
        f"🟢 [통제소] 엔진 상태: {state}\n"
        f"콜드스타트: {cold_start}\n"
        f"최근 주기 완료 시각: {last}\n"
        f"명령 감시 스레드: {heartbeat}\n"
        f"마지막 처리 update_id: {_admin_last_update_id}\n"
        f"🔌 회로차단으로 자동 비활성화된 단계:\n{disabled_lines}"
    )


def _admin_cmd_pause(arg=""):
    _engine_set_paused(True)   # 즉시 디스크에도 저장 → 재시작해도 정지 상태 유지
    return "⏸ [통제소] 뉴스 수집·송출을 일시정지했습니다. (재시작해도 유지됩니다)"


def _admin_cmd_resume(arg=""):
    _engine_set_paused(False)
    _engine_wake_event.set()
    return "▶️ [통제소] 뉴스 수집·송출을 재개했습니다."


def _admin_cmd_reset_stages(arg=""):
    """/재진단 : 회로차단으로 자동 비활성화된 단계를 즉시 초기화해 다음 주기부터
    바로 재시도하게 한다. 원인을 고친 뒤 쿨다운(기본 15분)을 기다리지 않고
    바로 정상화 여부를 확인하고 싶을 때 사용한다."""
    n = _engine_reset_all_stage_breakers()
    return f"🔄 [통제소] 회로차단 상태 초기화 완료 | 초기화된 단계={n}개 | 다음 주기부터 재시도합니다."


def _admin_cmd_run(arg=""):
    """정규 주기(최대 60초)를 기다리지 않고 지금 즉시 한 사이클을 강제 실행한다."""
    from main_메인 import _engine_cycle
    def _worker():
        with _engine_cycle_lock:
            _engine_log("info", "[관리자 명령] /run 즉시 사이클 실행 시작")
            was_paused = engine_state_공유상태._engine_paused
            try:
                _engine_cycle()
            except Exception as e:
                log_error("관리자 /run 즉시 사이클", e)
        _admin_reply("✅ [통제소] 즉시 실행 완료." + ("  (참고: 현재 일시정지 상태였습니다)" if was_paused else ""))
    threading.Thread(target=_worker, name="admin-run", daemon=True).start()
    return "⏳ [통제소] 즉시 실행을 시작했습니다."


def _admin_cmd_help(arg=""):
    lines = ["🟢 [통제소] 사용 가능한 명령", "/status : 엔진 상태 확인", "/pause : 일시정지",
              "/resume : 재개", "/run : 지금 즉시 1회 사이클 강제 실행",
              "/재진단 : 회로차단으로 자동 비활성화된 단계를 즉시 재시도",
              "/워밍업해제 : 콜드스타트 워밍업(송출 보류) 상태를 즉시 강제 해제",
              "/성과리포트 : 송출된 뉴스의 실제 등락률 집계(키워드별 적중률)",
              "/백필 [일수] : DART 과거 공시를 소급해 과거DB에 적재(기본 365일)",
              "/일정백필 : 일정DB 최초 1년 백필을 수동 실행(요청 간 딜레이 있어 몇 분 소요)",
              "/help : 이 목록 표시"]
    return "\n".join(lines)


def _admin_cmd_outcome_report(arg=""):
    try:
        min_samples = int(arg.strip()) if arg.strip() else 3
    except ValueError:
        min_samples = 3
    return _outcome_aggregate_report(min_samples=min_samples)


def _admin_cmd_force_end_cold_start(arg=""):
    """/워밍업해제 : 콜드스타트 워밍업(송출 강제금지) 구간을 관리자가 즉시 끝낸다.
    [등록 배경] news_engine_핵심엔진._engine_force_end_cold_start()는 이미 구현돼
    있었지만 정작 이걸 호출하는 관리자 명령이 등록되어 있지 않아 죽은 코드였다.
    재배포 직후 이력 파일이 사라져 콜드스타트가 걸렸는데(기본 10분) 그 사이에
    뜬 진짜 새 뉴스가 워밍업 종료 전까지 전부 송출 보류되는 상황에서, 관리자가
    "지금은 안전하다"고 판단하면 대기 없이 즉시 정상 송출로 전환할 수 있다."""
    was_active = _engine_force_end_cold_start()
    if was_active:
        return "🔓 [통제소] 콜드스타트 워밍업을 강제 해제했습니다. 지금부터 정상 송출됩니다."
    return "ℹ️ [통제소] 현재 워밍업(콜드스타트) 상태가 아닙니다. 이미 정상 송출 중입니다."


def _admin_cmd_backfill(arg=""):
    """/백필 [일수] : DART 과거 공시를 지정 일수(기본 365일)만큼 소급 조회해
    과거DB(HISTORICAL_SURGE_DB)에 적재한다. 시간이 걸리므로 백그라운드로 실행하고
    완료되면 별도로 결과를 회신한다. 네이버 뉴스는 API 특성상 기간 백필이
    불가능해 DART 공시만 대상으로 한다."""
    global _ENGINE_BACKFILL_RUNNING
    try:
        days = int(arg.strip()) if arg.strip() else 365
    except ValueError:
        return "❓ 사용법: /백필 [일수]  예) /백필 365"
    with _ENGINE_BACKFILL_LOCK:
        if _ENGINE_BACKFILL_RUNNING:
            return "⏳ [통제소] 이미 백필이 진행 중입니다. 완료될 때까지 기다려주세요."
        _ENGINE_BACKFILL_RUNNING = True

    def _worker():
        global _ENGINE_BACKFILL_RUNNING
        try:
            recorded = _engine_backfill_dart_historical(days=days)
            _admin_reply(f"✅ [통제소] DART 과거 {days}일 백필 완료 | 신규 누적={recorded}건")
        except Exception as e:
            log_error("관리자 /백필", e, days=days)
            _admin_reply(f"⚠️ [통제소] 백필 중 오류가 발생했습니다: {html.escape(str(e)[:200])}")
        finally:
            with _ENGINE_BACKFILL_LOCK:
                _ENGINE_BACKFILL_RUNNING = False

    threading.Thread(target=_worker, name="admin-backfill", daemon=True).start()
    return f"⏳ [통제소] DART 과거 {days}일 백필을 시작했습니다. 완료되면 결과를 보내드립니다."


_ENGINE_SCHEDULE_BACKFILL_RUNNING = False
_ENGINE_SCHEDULE_BACKFILL_LOCK = threading.Lock()


def _admin_cmd_schedule_backfill(arg=""):
    """/일정백필 : 일정DB 최초 1년 백필을 수동으로 즉시 실행한다.
    [주의] 부팅 시 자동 실행하던 것을 껐다 — 요청 간 딜레이 없이 200회+ Google
    RSS 요청을 연달아 쏴서 구글 쪽 일시 차단을 유발했고, 그 여파로 정상 국내
    뉴스 수집까지 함께 막힌 사고가 있었다. 지금은 요청 사이에 딜레이를 넣었지만
    그래도 몇 분 정도 걸리고, 진행 중에는 다른 뉴스 수집이 살짝 느려질 수 있으니
    필요할 때만 수동으로 실행할 것."""
    global _ENGINE_SCHEDULE_BACKFILL_RUNNING
    with _ENGINE_SCHEDULE_BACKFILL_LOCK:
        if _ENGINE_SCHEDULE_BACKFILL_RUNNING:
            return "⏳ [통제소] 이미 일정 백필이 진행 중입니다. 완료될 때까지 기다려주세요."
        _ENGINE_SCHEDULE_BACKFILL_RUNNING = True

    def _worker():
        global _ENGINE_SCHEDULE_BACKFILL_RUNNING
        try:
            from schedule_일정DB import _schedule_bootstrap_one_year
            _schedule_bootstrap_one_year()
            _admin_reply("✅ [통제소] 일정DB 1년 백필이 완료되었습니다.")
        except Exception as e:
            log_error("관리자 /일정백필", e)
            _admin_reply(f"⚠️ [통제소] 일정 백필 중 오류가 발생했습니다: {html.escape(str(e)[:200])}")
        finally:
            with _ENGINE_SCHEDULE_BACKFILL_LOCK:
                _ENGINE_SCHEDULE_BACKFILL_RUNNING = False

    threading.Thread(target=_worker, name="admin-schedule-backfill", daemon=True).start()
    return "⏳ [통제소] 일정DB 1년 백필을 시작했습니다 (요청 간 딜레이 있어 몇 분 소요). 완료되면 결과를 보내드립니다."


# 새 관리자 명령을 추가하려면 아래 딕셔너리에 "/명령어": 핸들러함수(arg) 형태로 등록만 하면 된다.
# 핸들러는 문자열을 반환하면 그대로 관리자에게 회신된다.
_ADMIN_COMMANDS = {
    "/status": _admin_cmd_status,
    "/pause": _admin_cmd_pause,
    "/resume": _admin_cmd_resume,
    "/run": _admin_cmd_run,
    "/재진단": _admin_cmd_reset_stages,
    "/워밍업해제": _admin_cmd_force_end_cold_start,
    "/help": _admin_cmd_help,
    "/성과리포트": _admin_cmd_outcome_report,
    "/백필": _admin_cmd_backfill,
    "/일정백필": _admin_cmd_schedule_backfill,
}


def _admin_selfcheck_commands():
    """[부팅 자가진단] 등록된 모든 명령 핸들러가 실제로 호출 가능한 함수인지
    부팅 시점에 검증한다. 과거 사고 원인이 '존재하지 않는 함수/모듈을 참조한 채
    배포'였기 때문에, 이런 문제는 반드시 부팅 단계에서 걸러내고 명확한 에러를
    텔레그램으로 즉시 알린다 — "조용히 예전 코드로 되돌아간 것처럼 보이는"
    상황 자체를 없애는 것이 목적이다."""
    problems = []
    for cmd, handler in _ADMIN_COMMANDS.items():
        if not callable(handler):
            problems.append(f"{cmd} → 핸들러가 함수가 아님({type(handler)})")
    return problems


def _admin_execute_command(raw_text):
    parts = raw_text.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""
    handler = _ADMIN_COMMANDS.get(cmd)
    if not handler:
        return f"❓ [통제소] 알 수 없는 명령입니다: {html.escape(cmd)}\n/help 로 사용 가능한 명령을 확인하세요."
    try:
        return handler(arg)
    except Exception as e:
        _engine_log("error", "[관리자 명령] 실행 실패 | 명령=%s | 원인=%s", cmd, str(e)[:160])
        return f"⚠️ [통제소] 명령 실행 중 오류가 발생했습니다: {html.escape(cmd)}"


def _admin_command_executor():
    """감지된 '마지막 명령'을 즉시 실행하는 최상위 통제 스레드.
    뉴스 수집 사이클, 대기(sleep) 상태와 완전히 무관하게 최우선으로 실행된다."""
    global _admin_pending_command
    while True:
        _admin_command_event.wait()
        with _admin_lock:
            command = _admin_pending_command
            _admin_pending_command = None
            _admin_command_event.clear()
        if not command:
            continue
        _engine_log("info", "[관리자 명령] 즉시 실행 | %s", command[:120])
        result = _admin_execute_command(command)
        _admin_reply(result)


_ENGINE_BACKFILL_RUNNING = False
_ENGINE_BACKFILL_LOCK = threading.Lock()
