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

# ==== module: config (auto-split from original main.py) ====


def _startup_env_flag(name, default=True):
    val = os.environ.get(name)
    return default if val is None else val.strip().lower() in ("true", "1", "yes", "on")
ENABLE_DOMESTIC_NEWS = _startup_env_flag("ENABLE_DOMESTIC_NEWS")
ENABLE_US_NEWS = _startup_env_flag("ENABLE_US_NEWS")
ENABLE_TELEGRAM_CHANNELS = _startup_env_flag("ENABLE_TELEGRAM_CHANNELS")
ENABLE_YOUTUBE = _startup_env_flag("ENABLE_YOUTUBE")


def _env_flag(name, default=True):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


ENABLE_DOMESTIC_NEWS = _env_flag("ENABLE_DOMESTIC_NEWS")         # 국내 RSS
ENABLE_US_NEWS = _env_flag("ENABLE_US_NEWS")                     # 해외 RSS
ENABLE_MORNING_BRIEFING = _env_flag("ENABLE_MORNING_BRIEFING")   # 아침 브리핑(해외지수/테마)
ENABLE_US_INTRADAY_BRIEFING = _env_flag("ENABLE_US_INTRADAY_BRIEFING", True)  # 미국장 개장 30분 + 장중 변동 브리핑
ENABLE_TELEGRAM_CHANNELS = _env_flag("ENABLE_TELEGRAM_CHANNELS") # 텔레그램1(필터)+2(무조건)
ENABLE_CUSTOM_SOURCES = _env_flag("ENABLE_CUSTOM_SOURCES")       # 약업신문/전자신문
ENABLE_DART = _env_flag("ENABLE_DART")                           # DART 공시
ENABLE_NAVER_NEWS = _env_flag("ENABLE_NAVER_NEWS", False)               # 네이버 뉴스 — [2026-08] 네이버 개발자센터 검색 오픈API 서비스 종료로 기본 OFF. 대체 키(API HUB) 확보 시에만 켤 것.
ENABLE_BLOG = _env_flag("ENABLE_BLOG")                           # 분석 블로그
ENABLE_YOUTUBE = _env_flag("ENABLE_YOUTUBE")                     # 유튜브
ENABLE_SCHEDULE_REMINDERS = _env_flag("ENABLE_SCHEDULE_REMINDERS")   # 일정 D-7/D-3 리마인더
ENABLE_SCHEDULE_BOOTSTRAP = _env_flag("ENABLE_SCHEDULE_BOOTSTRAP", False)  # [버그 수정] 최초 1년 일정 백필(200회+ Google RSS 요청)이 구글 연쇄차단→국내뉴스 유실을 유발한 적이 있어 기본 OFF. 필요 시 /일정백필 명령으로 수동 실행.
ENABLE_IPO_ALERTS = _env_flag("ENABLE_IPO_ALERTS")               # 신규상장(IPO) 알림

_SOLO_MODE_ALIASES = {
    "국내RSS": "DOMESTIC_NEWS", "국내뉴스": "DOMESTIC_NEWS",
    "해외RSS": "US_NEWS", "해외뉴스": "US_NEWS", "해외": "US_NEWS",
    "DART공시": "DART", "공시": "DART",
    "텔레그램1+2": "TELEGRAM", "텔레그램": "TELEGRAM", "텔레그램1": "TELEGRAM", "텔레그램2": "TELEGRAM",
    "약업전자": "CUSTOM_SOURCES", "약업/전자신문": "CUSTOM_SOURCES", "약업신문": "CUSTOM_SOURCES", "전자신문": "CUSTOM_SOURCES",
    "네이버": "NAVER", "네이버뉴스": "NAVER",
    "블로그": "BLOG", "분석블로그": "BLOG",
    "유튜브": "YOUTUBE",
}
_SOLO_MODE_RAW = os.environ.get("SOLO_MODE", "").strip().upper()
_SOLO_MODE_TOKENS = [t.strip() for t in re.split(r"[,/]", _SOLO_MODE_RAW) if t.strip()]
_SOLO_MODES = set()
for _tok in _SOLO_MODE_TOKENS:
    _resolved = _SOLO_MODE_ALIASES.get(_tok, _tok)
    _SOLO_MODES.add(_resolved)

_KNOWN_SOLO_MODES = {
    "DOMESTIC_NEWS", "US_NEWS", "DART", "TELEGRAM", "CUSTOM_SOURCES",
    "NAVER", "BLOG", "YOUTUBE",
}
_SOLO_MODES_VALID = _SOLO_MODES & _KNOWN_SOLO_MODES

if _SOLO_MODES_VALID:
    ENABLE_DOMESTIC_NEWS = False
    ENABLE_US_NEWS = False
    ENABLE_MORNING_BRIEFING = False
    ENABLE_TELEGRAM_CHANNELS = False
    ENABLE_CUSTOM_SOURCES = False
    ENABLE_DART = False
    ENABLE_NAVER_NEWS = False
    ENABLE_BLOG = False
    ENABLE_YOUTUBE = False
    ENABLE_SCHEDULE_REMINDERS = False
    ENABLE_IPO_ALERTS = False
    ENABLE_US_INTRADAY_BRIEFING = False

    for _mode in _SOLO_MODES_VALID:
        if _mode == "DOMESTIC_NEWS":
            ENABLE_DOMESTIC_NEWS = True
        elif _mode == "US_NEWS":
            ENABLE_US_NEWS = True
            ENABLE_MORNING_BRIEFING = True
        elif _mode == "DART":
            ENABLE_DART = True
        elif _mode == "TELEGRAM":
            ENABLE_TELEGRAM_CHANNELS = True
        elif _mode == "CUSTOM_SOURCES":
            ENABLE_CUSTOM_SOURCES = True
        elif _mode == "NAVER":
            ENABLE_NAVER_NEWS = True
        elif _mode == "BLOG":
            ENABLE_BLOG = True
        elif _mode == "YOUTUBE":
            ENABLE_YOUTUBE = True
MAIN_LOOP_TICK = 5               

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
ENABLE_GLOBAL_BRIEFING_DB = _env_flag("ENABLE_GLOBAL_BRIEFING_DB")
ENABLE_HISTORICAL_SURGE_DB = _env_flag("ENABLE_HISTORICAL_SURGE_DB")
ENABLE_OUTCOME_TRACKING = _env_flag("ENABLE_OUTCOME_TRACKING", True)


KRX_WEEKDAY_OPEN = datetime.time(9, 0)
KRX_WEEKDAY_CLOSE = datetime.time(15, 30)
# 2026년 주요 KRX 휴장일. 주말은 별도 자동 처리한다.
KRX_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
    "2026-05-05", "2026-05-25", "2026-06-06", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25",
}


# ============================================================
# ============================================================
# 🇰🇷 국내장 장중 브리핑 + 실행 자가진단
# - 09:30 첫 브리핑, 이후 30분 슬롯
# - 지수/원달러/핵심 대형주 변화가 기준을 넘으면 장중 변동 브리핑
# - Yahoo 시세 실패 시 조용히 죽지 않고 다음 1분 주기에 재시도
# ============================================================
ENABLE_DOMESTIC_INTRADAY_BRIEFING = _env_flag("ENABLE_DOMESTIC_INTRADAY_BRIEFING", True)


# ============================================================
# 🇺🇸 미국장 마감 브리핑
# ============================================================
ENABLE_US_CLOSE_BRIEFING = _env_flag("ENABLE_US_CLOSE_BRIEFING", True)
