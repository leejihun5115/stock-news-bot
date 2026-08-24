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
