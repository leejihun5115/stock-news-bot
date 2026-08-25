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

# ==== module: engine_state (auto-split from original main.py) ====

from common_공용유틸 import _engine_log, _engine_send_telegram, _now_kst, log_error

# ============================================================
# [실행 엔진 복구] 1분 주기 실시간 수집/분석/텔레그램 전송
# ============================================================
# 이 파일에는 설정/키워드만 남고 실제 반복 실행부가 빠진 경우에도
# 뉴스 수집이 멈추지 않도록 독립 실행 엔진을 붙인다.
# 기존 설정값/키워드/환경변수는 그대로 사용한다.

ENGINE_INTERVAL = 60
WATCHDOG_TIMEOUT = max(120, int(os.environ.get("NEWS_BOT_WATCHDOG_TIMEOUT", "300")))
WATCHDOG_ALERT_INTERVAL = max(300, int(os.environ.get("NEWS_BOT_WATCHDOG_ALERT_INTERVAL", "900")))

_engine_last_cycle_started = 0.0
_engine_last_cycle_finished = 0.0
_engine_last_watchdog_alert = 0.0
_engine_wake_event = threading.Event()     # 메인 루프의 대기(sleep)를 즉시 깨움
_engine_cycle_lock = threading.Lock()      # /run 즉시실행과 정규 사이클이 동시에 돌지 않도록 보호
_engine_paused = False


def _engine_watchdog_alert(force=False):
    global _engine_last_watchdog_alert
    if not _engine_last_cycle_started:
        return
    stale = time.time() - max(_engine_last_cycle_started, _engine_last_cycle_finished)
    if stale < WATCHDOG_TIMEOUT:
        return
    if not force and time.time() - _engine_last_watchdog_alert < WATCHDOG_ALERT_INTERVAL:
        return
    _engine_last_watchdog_alert = time.time()
    msg = f"🚨 뉴스봇 WATCHDOG\n마지막 주기 응답 지연: {int(stale)}초\nKST: {_now_kst().strftime('%Y-%m-%d %H:%M:%S')}"
    _engine_log("error", "[WATCHDOG] %s", msg.replace("\n", " | "))
    try:
        _engine_send_telegram(msg)
    except Exception as e:
        log_error("WATCHDOG Telegram 알림", e)


# ============================================================
# [단계별 회로차단기 — Stage Circuit Breaker]
# ------------------------------------------------------------
# [배경] 기존 _engine_cycle()은 국내수집/네이버/DART/텔레그램/유튜브/브리핑
# 등 각 단계를 개별 try/except로만 감싸고 있었다. 파일을 수정하다 특정 단계에
# 버그가 생기면(오타, 잘못된 인자, 삭제된 함수 등) 그 버그가 60초 주기마다
# "영원히" 재발생한다. log_error() 자체에는 반복 억제(dedup)가 있어 로그 줄
# 수는 줄었지만, 그 단계는 계속 죽은 채로 방치되고 관리자는 텔레그램으로
# 아무 것도 모른 채 "왜 특정 뉴스가 안 오지?"만 겪게 된다.
#
# [해결] 각 단계를 이 함수로 감싸면:
#   1) 같은 단계가 threshold회(기본 5회) 연속 실패하면 cooldown(기본 15분)
#      동안 그 단계만 자동으로 건너뛴다 → 나머지 단계는 정상 동작 유지.
#   2) 회로가 열릴 때(cooldown 시작) 딱 1번만 "어느 단계가 왜 실패하는지"를
#      요약해 관리자 텔레그램으로 보낸다 → "파일 수정 후 문제가 생겼는지"를
#      바로 알 수 있다.
#   3) cooldown이 지나면 자동으로 다시 시도하고, 성공하면 카운터를 리셋한다
#      → 원인을 고치고 재배포하면 별도 조치 없이 자동으로 정상 복귀한다.
#   4) 관리자가 원인을 고친 걸 확인했으면 /재진단 명령으로 즉시 재시도시킬
#      수 있다(admin_관리자._admin_cmd_reset_stages).
# ============================================================
STAGE_FAILURE_THRESHOLD = int(os.environ.get("NEWS_BOT_STAGE_FAILURE_THRESHOLD", "5"))
STAGE_COOLDOWN_SEC = int(os.environ.get("NEWS_BOT_STAGE_COOLDOWN_SEC", "900"))  # 15분

_engine_stage_state = {}   # {단계명: {"fail_count", "disabled_until", "alerted", "last_error"}}
_engine_stage_state_lock = threading.Lock()


def _engine_run_stage(stage_name, func):
    """주기 안의 각 단계(수집/브리핑 등)를 안전하게 실행한다. 위 회로차단기 설명 참고."""
    now = time.time()
    with _engine_stage_state_lock:
        st = _engine_stage_state.setdefault(
            stage_name, {"fail_count": 0, "disabled_until": 0.0, "alerted": False, "last_error": ""}
        )
        if st["disabled_until"] > now:
            return  # 쿨다운 중 - 이미 1회 알림을 보냈으므로 조용히 건너뛴다(로그 폭주 방지)

    try:
        func()
        with _engine_stage_state_lock:
            if st["fail_count"] > 0:
                _engine_log("info", "[자동복구] '%s' 단계 정상화(이전 연속 실패 %d회)", stage_name, st["fail_count"])
            st["fail_count"] = 0
            st["alerted"] = False
    except Exception as e:
        log_error(f"{stage_name}", e)
        alert_msg = None
        with _engine_stage_state_lock:
            st["fail_count"] += 1
            st["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            if st["fail_count"] >= STAGE_FAILURE_THRESHOLD and not st["alerted"]:
                st["disabled_until"] = now + STAGE_COOLDOWN_SEC
                st["alerted"] = True
                alert_msg = (
                    f"🚨 [자동진단] '{stage_name}' 단계가 {st['fail_count']}회 연속 실패해 "
                    f"{STAGE_COOLDOWN_SEC // 60}분간 자동으로 건너뜁니다.\n"
                    f"마지막 원인: {st['last_error']}\n"
                    f"※ 최근 이 단계 관련 파일을 수정했다면 그 변경부터 확인해주세요.\n"
                    f"※ 수정 완료 후 /재진단 명령으로 즉시 재시도할 수 있습니다."
                )
        if alert_msg:
            try:
                _engine_send_telegram(alert_msg)
            except Exception as send_e:
                log_error("회로차단 알림 전송", send_e, stage=stage_name)


def _engine_list_disabled_stages():
    """/status 명령에서 현재 자동 비활성화된 단계 목록을 보여주기 위함."""
    now = time.time()
    with _engine_stage_state_lock:
        return {name: dict(st) for name, st in _engine_stage_state.items() if st.get("disabled_until", 0) > now}


def _engine_reset_all_stage_breakers():
    """/재진단 명령: 회로차단으로 비활성화된 모든 단계를 즉시 초기화해 다음 주기부터 재시도한다."""
    with _engine_stage_state_lock:
        n = len(_engine_stage_state)
        _engine_stage_state.clear()
    return n
