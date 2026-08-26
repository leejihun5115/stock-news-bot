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


# ============================================================
# 🧭 [SSOT 상태 영속화] 일시정지 여부는 재시작해도 유지되어야 한다.
# ------------------------------------------------------------
# 관리자가 /pause를 내렸는데 배포/재시작이 한 번 일어나면 메모리 변수가 초기화되어
# 조용히 재개되는 사고를 막는다. 파일 쓰기는 tmp에 먼저 쓰고 os.replace로 원자적
# 교체하므로, 쓰는 도중 프로세스가 죽어도 파일이 반쯤 깨진 상태로 남지 않는다.
# ============================================================
_ENGINE_STATE_FILE = os.environ.get("NEWS_BOT_ENGINE_STATE_FILE", "news_bot_engine_state.json")
_engine_state_lock = threading.Lock()


def _engine_state_atomic_write(path, obj):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _engine_save_state():
    """현재 일시정지 여부 + 회로차단 상태를 디스크에 즉시 영속화한다."""
    with _engine_state_lock:
        try:
            _engine_state_atomic_write(_ENGINE_STATE_FILE, {
                "paused": _engine_paused,
                "stage_breakers": _engine_stage_breakers,
                "saved_at": _now_kst().isoformat(),
            })
        except Exception as e:
            log_error("엔진 상태 저장", e)


def _engine_load_state():
    """부팅 시 마지막으로 저장된 일시정지/회로차단 상태를 복원한다.
    관리자가 재시작 직전에 /pause를 내렸다면, 재시작 후에도 계속 정지 상태여야 한다."""
    global _engine_paused, _engine_stage_breakers
    if not os.path.exists(_ENGINE_STATE_FILE):
        return
    try:
        with open(_ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _engine_paused = bool(data.get("paused", False))
        loaded_breakers = data.get("stage_breakers") or {}
        if isinstance(loaded_breakers, dict):
            _engine_stage_breakers.update(loaded_breakers)
        _engine_log("info", "[엔진 상태 복원] paused=%s | 회로차단 단계=%d개",
                    _engine_paused, len(_engine_stage_breakers))
    except Exception as e:
        log_error("엔진 상태 복원", e)


def _engine_set_paused(value):
    """일시정지 여부를 바꾸고 즉시 디스크에 반영한다. 명령 실행 지점에서만 사용."""
    global _engine_paused
    _engine_paused = bool(value)
    _engine_save_state()


# ============================================================
# 🔌 [단계별 회로차단기] 특정 단계(예: DART, 네이버)가 계속 실패해도
# 나머지 단계와 메인 사이클 전체가 함께 멈추지 않도록 격리한다.
# - 연속 실패가 임계치를 넘으면 자동 비활성화 + 쿨다운
# - 쿨다운이 지나면 자동으로 1회 재시도
# - 관리자가 /재진단 명령으로 즉시 강제 재시도 가능
# ============================================================
STAGE_BREAKER_FAIL_THRESHOLD = max(1, int(os.environ.get("NEWS_BOT_STAGE_FAIL_THRESHOLD", "5")))
STAGE_BREAKER_COOLDOWN_SEC = max(60, int(os.environ.get("NEWS_BOT_STAGE_COOLDOWN_SEC", "900")))

_engine_stage_breakers = {}   # {단계명: {"fail_count":int, "disabled":bool, "last_error":str, "disabled_until":float}}
_engine_stage_breaker_lock = threading.Lock()


def _engine_run_stage(name, func, *args, **kwargs):
    """뉴스 사이클의 한 단계를 실행한다. 실패해도 예외를 삼켜 다음 단계로 넘어가되,
    같은 단계가 연속으로 계속 실패하면 자동으로 잠시 꺼서(회로차단) 매 사이클마다
    같은 오류로 시간을 낭비하거나 로그가 폭주하는 것을 막는다."""
    with _engine_stage_breaker_lock:
        info = _engine_stage_breakers.get(name)
        if info and info.get("disabled"):
            if time.time() < info.get("disabled_until", 0):
                _engine_log("debug", "[회로차단] %s | 쿨다운 중이라 이번 주기는 건너뜀", name)
                return False
            # 쿨다운이 끝났으므로 이번 한 번은 다시 시도해본다.
            _engine_log("info", "[회로차단] %s | 쿨다운 종료, 재시도 시작", name)

    try:
        func(*args, **kwargs)
    except Exception as e:
        log_error(name, e)
        with _engine_stage_breaker_lock:
            info = _engine_stage_breakers.setdefault(name, {"fail_count": 0, "disabled": False, "last_error": "", "disabled_until": 0})
            info["fail_count"] += 1
            info["last_error"] = f"{type(e).__name__}: {str(e)[:160]}"
            if info["fail_count"] >= STAGE_BREAKER_FAIL_THRESHOLD:
                info["disabled"] = True
                info["disabled_until"] = time.time() + STAGE_BREAKER_COOLDOWN_SEC
                _engine_log("error", "[회로차단 작동] %s | 연속 %d회 실패로 %d초간 자동 비활성화",
                            name, info["fail_count"], STAGE_BREAKER_COOLDOWN_SEC)
        _engine_save_state()
        return False
    else:
        with _engine_stage_breaker_lock:
            if name in _engine_stage_breakers and (_engine_stage_breakers[name].get("fail_count") or _engine_stage_breakers[name].get("disabled")):
                _engine_stage_breakers[name] = {"fail_count": 0, "disabled": False, "last_error": "", "disabled_until": 0}
                _engine_save_state()
        return True


def _engine_list_disabled_stages():
    """현재 회로차단으로 자동 비활성화된 단계만 반환한다. /status에서 사용."""
    with _engine_stage_breaker_lock:
        return {name: dict(info) for name, info in _engine_stage_breakers.items() if info.get("disabled")}


def _engine_reset_all_stage_breakers():
    """관리자 /재진단 명령: 모든 회로차단 상태를 즉시 초기화해 다음 주기부터 바로 재시도하게 한다."""
    with _engine_stage_breaker_lock:
        n = sum(1 for info in _engine_stage_breakers.values() if info.get("disabled"))
        for info in _engine_stage_breakers.values():
            info["disabled"] = False
            info["fail_count"] = 0
            info["disabled_until"] = 0
    _engine_save_state()
    return n


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
