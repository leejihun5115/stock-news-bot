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
from engine_state_공유상태 import _engine_cycle_lock, _engine_wake_event
from news_engine_핵심엔진 import _engine_force_end_cold_start
from outcome_tracking_성과추적 import _outcome_aggregate_report
from sources_external_외부연동 import _engine_backfill_dart_historical
from ml_learning_기계학습 import _ml_status_report
from 정책_최상위통제 import get_runtime_policy, set_runtime_policy, reset_runtime_policy, format_policy
import engine_state_공유상태
import news_engine_핵심엔진  # 실시간 값(콜드스타트 플래그 등) 읽기용 — 값은 반드시 모듈 경로로 접근


# ============================================================
# 관리자 최우선 명령 통제소 (Top-Level Control Tower)
# MASTER가 개별 뉴스 판정의 최종 두뇌라면, 이 통제소는 엔진 전체 동작을
# 관리자가 텔레그램으로 내린 '마지막 명령' 기준으로 즉시 제어하는 최상위 계층이다.
# 뉴스 수집 사이클과 완전히 분리된 별도 스레드에서 짧은 주기로 명령을 감시하므로,
# 데이터 수집 중이라도 명령 실행이 지연되지 않는다.
# ============================================================
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "") or CHAT_ID
ADMIN_COMMAND_PREFIX = "/"
ADMIN_COMMAND_POLL_INTERVAL = float(os.environ.get("ADMIN_COMMAND_POLL_INTERVAL", "2"))

# --- 관리자 최우선 명령 통제소 전역 상태 ---
_admin_lock = threading.Lock()
_admin_last_update_id = 0
_admin_pending_command = None      # 아직 실행되지 않은 '가장 최신' 명령만 보관 (덮어쓰기 방식)
_admin_command_event = threading.Event()   # 새 명령 도착 시 실행 스레드를 즉시 깨움


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


def _admin_fetch_updates():
    """Telegram getUpdates로 새 메시지만 가져온다(이미 읽은 update_id는 제외)."""
    global _admin_last_update_id
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
            _engine_log(
                "error",
                "[관리자 명령] getUpdates 409 Conflict | 동일 BOT_TOKEN을 다른 프로세스가 "
                "이미 폴링 중입니다(중복 배포 인스턴스 또는 webhook 설정을 확인하세요).",
            )
            return []
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
    return updates


def _admin_command_listener():
    """관리자 채팅방을 짧은 주기(기본 2초)로 감시한다.
    새 명령이 오면 이전에 처리되지 않은 명령이 남아있어도 무조건 최신 명령으로 덮어쓴다.
    → '마지막으로 내린 명령'만 실행 대상이 된다."""
    global _admin_pending_command
    _engine_log("info", "[관리자 명령] 통제소 감시 시작 | ADMIN_CHAT_ID=%s", ADMIN_CHAT_ID)
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
        except Exception as e:
            _engine_log("error", "[관리자 명령] 감시 루프 오류 | 원인=%s", str(e)[:160])
        time.sleep(ADMIN_COMMAND_POLL_INTERVAL)


def _admin_cmd_status(arg=""):
    state = "⏸ 일시정지" if engine_state_공유상태._engine_paused else "▶️ 정상 가동"
    last = _now_kst().strftime("%Y-%m-%d %H:%M:%S") if engine_state_공유상태._engine_last_cycle_finished else "없음"
    cold = "🥶 콜드스타트 워밍업 중(송출 강제금지)" if news_engine_핵심엔진._engine_cold_start_active else "정상(워밍업 아님)"
    disabled = engine_state_공유상태._engine_list_disabled_stages()
    if disabled:
        disabled_lines = "\n".join(
            f"  - {name} | 연속실패 {info.get('fail_count',0)}회 | 원인: {info.get('last_error','')[:100]}"
            for name, info in disabled.items()
        )
    else:
        disabled_lines = "  없음"
    return (f"🟢 [통제소] 엔진 상태: {state}\n최근 주기 완료 시각: {last}\n중복방지 상태: {cold}\n"
            f"🔌 자동 비활성화된 단계(회로차단):\n{disabled_lines}")


def _admin_cmd_pause(arg=""):
    engine_state_공유상태._engine_paused = True
    return "⏸ [통제소] 뉴스 수집·송출을 일시정지했습니다."


def _admin_cmd_resume(arg=""):
    engine_state_공유상태._engine_paused = False
    _engine_wake_event.set()
    return "▶️ [통제소] 뉴스 수집·송출을 재개했습니다."


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


def _admin_cmd_end_warmup(arg=""):
    """[강제종료 명령] 콜드스타트 감지로 열린 송출금지 워밍업 구간을 관리자가
    즉시 강제로 끝낸다. 이력 파일이 없어서 열린 안전장치이므로, 관리자가
    "지금 재송출돼도 괜찮다/이미 확인했다"고 판단했을 때만 사용한다."""
    was_active = _engine_force_end_cold_start()
    if was_active:
        return "🔓 [통제소] 콜드스타트 워밍업을 강제로 해제했습니다. 지금부터 정상 송출됩니다."
    return "ℹ️ [통제소] 현재 워밍업 상태가 아닙니다(강제 해제할 대상 없음)."


def _admin_cmd_help(arg=""):
    lines = ["🟢 [통제소] 사용 가능한 명령", "/status : 엔진 상태 확인", "/pause : 일시정지",
              "/resume : 재개", "/run : 지금 즉시 1회 사이클 강제 실행",
              "/워밍업해제 : 콜드스타트 송출금지 워밍업을 강제로 즉시 해제",
              "/성과리포트 : 송출된 뉴스의 실제 등락률 집계(키워드별 적중률)",
              "/학습현황 : 누적 데이터 학습형 AI의 학습량·예측 적중률 확인",
              "/정책 : 현재 최상위 정책 조회",
              "/정책 {JSON} : 마지막 정책으로 전체 뉴스에 강제 적용",
              "/정책 초기화 : 최상위 정책을 MASTER 기본판정으로 복귀",
              "/재진단 : 회로차단으로 자동 비활성화된 단계를 즉시 재시도",
              "/백필 [일수] : DART 과거 공시를 소급해 과거DB에 적재(기본 365일)",
              "/help : 이 목록 표시"]
    return "\n".join(lines)


def _admin_cmd_policy(arg=""):
    """최상위 정책을 조회/변경한다. JSON으로 지정한 값이 이후 모든 뉴스에 공통 적용된다."""
    arg = (arg or "").strip()
    if not arg:
        return format_policy() + "\n사용법: /정책 {\"title\":\"...\",\"outlook\":[\"...\"]}"
    if arg in {"초기화", "reset", "RESET"}:
        reset_runtime_policy(source="admin:/정책 초기화")
        return "♻️ [최상위 정책] 초기화 완료. 다음 뉴스부터 MASTER 기본판정으로 돌아갑니다."
    try:
        payload = json.loads(arg)
        if not isinstance(payload, dict):
            raise ValueError("JSON 객체가 아닙니다.")
    except Exception as e:
        return "❓ 사용법: /정책 {\"title\":\"...\",\"key_points\":[\"...\"],\"outlook\":[\"...\"],\"schedule\":\"...\"}"
    allowed = {"title", "key_points", "outlook", "schedule"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        return f"❌ 허용되지 않은 정책 필드: {', '.join(unknown)}"
    state = set_runtime_policy(payload, source="admin:/정책")
    return "✅ [최상위 정책] 변경 즉시 저장/적용\n" + format_policy(state)


def _admin_cmd_outcome_report(arg=""):
    try:
        min_samples = int(arg.strip()) if arg.strip() else 3
    except ValueError:
        min_samples = 3
    return _outcome_aggregate_report(min_samples=min_samples)


def _admin_cmd_ml_status(arg=""):
    """/학습현황 : 누적 데이터로 계속 학습 중인 AI 분석 모듈의 학습량과
    예측 적중률(백테스트)을 보여준다."""
    return _ml_status_report()


def _admin_cmd_reset_stages(arg=""):
    """/재진단 : 회로차단기로 자동 비활성화된 단계를 즉시 초기화해 다음 주기부터
    바로 재시도하게 한다. 파일 수정으로 원인을 고친 뒤, 쿨다운(기본 15분)을
    기다리지 않고 즉시 정상화 여부를 확인하고 싶을 때 사용한다."""
    n = engine_state_공유상태._engine_reset_all_stage_breakers()
    return f"🔄 [통제소] 회로차단 상태 초기화 완료 | 초기화된 단계={n}개 | 다음 주기부터 재시도합니다."


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


# 새 관리자 명령을 추가하려면 아래 딕셔너리에 "/명령어": 핸들러함수(arg) 형태로 등록만 하면 된다.
# 핸들러는 문자열을 반환하면 그대로 관리자에게 회신된다.
_ADMIN_COMMANDS = {
    "/status": _admin_cmd_status,
    "/pause": _admin_cmd_pause,
    "/resume": _admin_cmd_resume,
    "/run": _admin_cmd_run,
    "/help": _admin_cmd_help,
    "/워밍업해제": _admin_cmd_end_warmup,
    "/성과리포트": _admin_cmd_outcome_report,
    "/학습현황": _admin_cmd_ml_status,
    "/정책": _admin_cmd_policy,
    "/재진단": _admin_cmd_reset_stages,
    "/백필": _admin_cmd_backfill,
}


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
