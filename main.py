# -*- coding: utf-8 -*-
"""
AI 주식 브리핑 엔진 — 국내/해외 뉴스·공시·텔레그램 채널을 수집해
조건 기반으로 검증한 뒤 Telegram으로 송출하는 봇.

# ============================================================
# 핵심 원칙 (FINAL AGREED BEHAVIOR)
# ============================================================
# 국내 관련주:
# - 직접 사업연관을 최우선으로 연결한다.
# - 직접연관이 없더라도 실제 시장에서 동일 테마로 움직인 근거가 있으면 연결한다.
# - 과거 상한가/급등 이력 + 과거 테마 주도 이력 + 반복적인 강한 수급 반응을
#   '끼/탄력'의 확인 근거로 사용한다.
# - 대장주를 선정하면 반드시 선정 이유를 함께 표시한다.
# - 이후 약한 순으로 약 3개까지 관찰 후보를 제시한다.
# - 글로벌 기업을 국내 상장기업으로 오인 연결하지 않는다.
# - 카테고리(분류 결과)가 없는 뉴스는 절대 노출하지 않는다.
#
# 미국장:
# - 미국 선물 급등/급락 시 별도 브리핑.
# - 개장 후 정기 브리핑, 장중 구조적 변화/환율/유가 등 큰 변동 시 브리핑.
# - 장마감 후 전체 시장흐름 + 강한 종목군 + 원인 + 한국 관련주 + MSCI + ADR 정리.
# - 국내 관련주가 없어도 글로벌 시황은 보존하고 글로벌 외신을 DB에 축적한다.
#
# 강한 재료:
# - 수주라면 수주 이유/금액/기간 등 확인 가능한 사실만 표시한다.
# - 과거 동일/유사 재료가 있으면 당시 주가 상승률과 원문 하이퍼링크를 연결한다.
# - 확인되지 않은 금액/수익률은 추정하지 않는다.
#
# 뉴스 품질:
# - 신규 사건 / 업그레이드 / 중복 사건 / 미확인 뉴스를 구분한다.
# - Telegram 도배를 방지한다(동일/유사 뉴스 재전송 차단).
# - 과거 상한가·급등 재료 DB 및 유사 사례 DB를 활용해 데이터 기반 비교를 제공한다.
# - 봇 미활동/장시간 무응답을 감시하고 알림을 보낸다.
#
# ============================================================
# 🔒 데이터 누적 절대 원칙 (2026-08-23 확정 / 임의 변경·롤백 금지)
# ------------------------------------------------------------
# - 과거DB(HISTORICAL_SURGE_DB) 적재는 "카테고리(분류)가 확정"되는 즉시,
#   텔레그램 실시간 송출 성공 여부·시간창(최근 60분 등)·시장시간 게이트와
#   완전히 무관하게 이루어진다. 시간/송출 게이트는 오직 "지금 당장 텔레그램에
#   내보낼지"만 결정할 뿐, "데이터를 쌓을지"를 결정해서는 절대 안 된다.
# - 즉, _engine_process_item()에서 분류(_engine_classify)가 ok=True이고
#   category가 있으면 _engine_record_historical_case(...)를 무조건 먼저
#   호출한 뒤에, 그 다음 단계로 실시간 송출 여부(시간창/게이트)를 판단하는
#   순서를 반드시 지킨다. 이 순서를 바꾸거나, 시간창 체크를 분류보다 앞에
#   두거나, "송출 성공(text_sent) 시에만 기록"하는 과거 구조로 되돌리면
#   시장비교/과거성과 분석 DB가 다시 비어버리는 원래 문제가 재발한다.
# - DART 등 기간 조회가 되는 소스는 /백필 명령으로 과거 데이터를 소급 적재하고,
#   그 외 실시간 수집분은 시간 경과에 따라 자연스럽게 누적된다.
# - [보완] 외신(영문) 뉴스는 번역이 분류보다 먼저 실행되는데, 번역 API가
#   429(Too Many Requests) 등으로 실패하면 그 즉시 뉴스를 버리지 않고
#   _engine_translate_retry_queue에 남겨 다음 주기(들)에 번역을 재시도한다.
#   번역이 성공하는 순간에만 이 원칙(분류→과거DB 무조건 누적)이 정상 적용되므로,
#   번역 재시도 큐 자체를 삭제하거나 "1회 실패 시 완전 폐기"로 되돌리지 않는다.
# - 이 절은 이후 어떤 리팩터링에서도 삭제/약화되지 않아야 하며, 관련 함수
#   (_engine_process_item, _engine_record_historical_case,
#   _engine_queue_translation_retry/_engine_retry_translation_queue)를
#   수정할 때는 이 원칙을 먼저 재확인한다.
# ============================================================
"""



try:
    from master_condition_manager import MasterConditionManager
except ModuleNotFoundError:
    # 원본 파일명(master_condition_manager(7).py)을 그대로 유지해도 부팅 가능하도록
    # 로컬 파일을 모듈명 master_condition_manager로 안전하게 로드한다.
    import importlib.util as _icu
    _os = __import__("os")
    _sys = __import__("sys")
    _mcm_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "master_condition_manager(7).py")
    _mcm_spec = _icu.spec_from_file_location("master_condition_manager", _mcm_path)
    if _mcm_spec is None or _mcm_spec.loader is None:
        raise ImportError(f"MasterConditionManager 모듈을 찾을 수 없습니다: {_mcm_path}")
    _mcm_mod = _icu.module_from_spec(_mcm_spec)
    _sys.modules["master_condition_manager"] = _mcm_mod
    _mcm_spec.loader.exec_module(_mcm_mod)
    MasterConditionManager = _mcm_mod.MasterConditionManager
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
from collections import defaultdict, Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
# === MASTER 65-CONDITION ENGINE ===
# 모든 최종 뉴스 판단은 이 엔진을 통과하도록 연결할 수 있다.
_MASTER_MANAGER = MasterConditionManager(max_related=3, min_score=40.0)

def master_finalize_news(
    title,
    body,
    source="",
    link="",
    candidates=None,
    schedule="",
    evidence=None,
):
    """뉴스 1건을 MASTER -> Validator -> FINAL LOCK 순으로 확정.

    [수정] 기존에는 Validator에서 오류가 하나라도 나오면 여기서 예외를 던졌고,
    호출부(_engine_master_result)의 try/except가 이를 통째로 삼켜 None을
    반환했다. 그 결과 MASTER가 이미 계산해 둔 제목/핵심요약/용어설명/관련종목이
    사소한 검증 오류 하나 때문에 전부 사라지고 원본 제목만 나가는 문제가 있었다.
    이제 검증 오류가 있어도 예외를 던지지 않고, locked=False 상태로 계산된
    내용을 그대로 반환한다. 오직 검증을 완전히 통과했을 때만 FINAL LOCK(locked=True)
    처리한다. Formatter 쪽은 locked 여부와 무관하게 사용 가능한 내용을 그대로 쓴다.
    """
    result = _MASTER_MANAGER.analyze(
        title=title,
        body=body,
        source=source,
        link=link,
        candidates=candidates or [],
        schedule=schedule,
        evidence=evidence or [],
    )
    result = _MASTER_MANAGER.validate(result)
    if result.get("validation_errors"):
        return result
    return _MASTER_MANAGER.lock(result)

# ============================================================
# 🕐 서버 시간대와 무관한 정확한 한국시간(KST)
# ------------------------------------------------------------
# Render 같은 클라우드는 보통 UTC로 돌아가서, 서버 로컬시간을 그냥 쓰면
# 실제 한국시간(KST)보다 9시간 밀려서 나올 수 있음. 아래 _now_kst() 함수를
# 텔레그램 시각 표시, DART 날짜 조회, 아침브리핑 발송시각 판정 등 "지금이
# 몇 시인지" 필요한 모든 곳에서 씀 - 서버 시간대가 뭐든 항상 정확한 KST를 줌.
# ============================================================
_KST = datetime.timezone(datetime.timedelta(hours=9))


def _now_kst():
    """서버 시스템 시간대와 무관하게 항상 정확한 한국시간(KST)을 naive
    datetime으로 반환. UTC 기준으로 정확히 계산한 뒤 tzinfo만 떼어내므로,
    기존 코드에서 datetime.datetime.now()를 쓰던 자리에 그대로 대체 가능."""
    return datetime.datetime.now(datetime.timezone.utc).astimezone(_KST).replace(tzinfo=None)


# ============================================================
# 🪵 로그 버퍼링 문제 해결 (실시간 로그 출력 강화)
# ------------------------------------------------------------
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import builtins as _builtins
_original_print = _builtins.print


def print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)



# ============================================================
# --- 시작 로그에 필요한 환경변수 선행 초기화 ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CHAT_ID_OVERSEAS = os.environ.get("CHAT_ID_OVERSEAS", "") or CHAT_ID
DART_API_KEY = os.environ.get("DART_API_KEY", "")

def _clean_secret_env(name):
    # Render 환경변수에 실수로 따옴표/앞뒤 공백이 붙어도 인증값 자체는 깨끗하게 사용한다.
    value = os.environ.get(name, "")
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        value = value[1:-1].strip()
    return value

# ⚠️ 중요: NAVER_CLIENT_*는 구형 Developer Center Search API용,
# NAVER_APIHUB_CLIENT_*는 NAVER API HUB용이다. 서로 섞어서 보내지 않는다.
NAVER_CLIENT_ID = _clean_secret_env("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _clean_secret_env("NAVER_CLIENT_SECRET")
NAVER_APIHUB_CLIENT_ID = _clean_secret_env("NAVER_APIHUB_CLIENT_ID")
NAVER_APIHUB_CLIENT_SECRET = _clean_secret_env("NAVER_APIHUB_CLIENT_SECRET")
NAVER_API_MODE = "auto"
NAVER_APIHUB_BASE_URL = "https://naverapihub.apigw.ntruss.com"
NAVER_LEGACY_BASE_URL = "https://openapi.naver.com/v1/search/news.json"

def _startup_env_flag(name, default=True):
    val = os.environ.get(name)
    return default if val is None else val.strip().lower() in ("true", "1", "yes", "on")
ENABLE_DOMESTIC_NEWS = _startup_env_flag("ENABLE_DOMESTIC_NEWS")
ENABLE_US_NEWS = _startup_env_flag("ENABLE_US_NEWS")
ENABLE_TELEGRAM_CHANNELS = _startup_env_flag("ENABLE_TELEGRAM_CHANNELS")
ENABLE_YOUTUBE = _startup_env_flag("ENABLE_YOUTUBE")

# 🔎 상세 로그 기록 강화
# ------------------------------------------------------------
# Render 콘솔 + news_bot.log에 동시에 기록
# HTTP 실패 시 URL / 상태코드 / 응답 내용 / 예외 / traceback 기록
# 처리되지 않은 예외도 마지막 traceback까지 기록
# ============================================================
import logging
from logging import FileHandler
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


def _redact_url(url):
    """로그에 남기는 URL에서 API 키/토큰/시크릿 계열 query parameter를 제거한다."""
    try:
        parts = urlsplit(str(url))
        pairs = []
        secret_words = ("key", "token", "secret", "password", "passwd", "authorization", "auth")
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if any(w in k.lower() for w in secret_words):
                pairs.append((k, "***REDACTED***"))
            else:
                pairs.append((k, v))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))
    except Exception:
        return "<URL_REDACTED>"


LOG_FILE = os.environ.get("NEWS_BOT_LOG_FILE", "news_bot.log")
_logger = logging.getLogger("news_bot")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    class _KSTFormatter(logging.Formatter):
        converter = staticmethod(lambda *args: __import__("time").gmtime(__import__("time").time() + 9 * 3600))
        def format(self, record):
            if record.levelno >= logging.ERROR:
                icon = "🔴"
            elif record.levelno >= logging.WARNING:
                icon = "🟠"
            else:
                icon = "🟢"
            record._status_icon = icon
            base = super().format(record)
            return f"{icon} {base}"

    _fmt = _KSTFormatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    _console = logging.StreamHandler(sys.stderr)
    _console.setLevel(logging.INFO)
    _console.setFormatter(_fmt)
    _logger.addHandler(_console)
    try:
        _file = FileHandler(LOG_FILE, mode="w", encoding="utf-8")
        _file.setLevel(logging.INFO)
        _file.setFormatter(_fmt)
        _logger.addHandler(_file)
        try:
            os.chmod(LOG_FILE, 0o600)
        except Exception:
            pass
    except Exception as _e:
        _original_print(
            f"[로그파일 생성 실패] {type(_e).__name__}: {_e}",
            file=sys.stderr, flush=True
        )


def log_info(message, *args):
    _logger.info(message, *args)


def log_debug(message, *args):
    return


def log_error(context, exc=None, **details):
    """실패 원인을 최대한 자세히 기록한다.
    [수정/로그 시스템 점검] 기존에는 예외 타입+메시지만 남기고 traceback을
    완전히 버려서, 'str' object has no attribute 'get' 같은 예외가 정확히
    어느 파일·몇 번째 줄·어떤 함수에서 발생했는지 로그만으로는 전혀 알 수
    없었다(원인 추적 불가 → 같은 오류가 반복돼도 고칠 지점을 못 찾음).
    이제 traceback의 마지막 몇 프레임(파일:줄번호(함수명))을 한 줄로 압축해
    함께 남긴다. 로그 폭주 방지를 위해 전체 스택은 남기지 않고, 실제 예외가
    발생한 지점에 가까운 프레임 몇 개만 남긴다.
    """
    parts = [f"[실패] {context}"]
    for k, v in details.items():
        if "url" in k.lower():
            v = _redact_url(v)
        parts.append(f"{k}={v}")
    if exc is not None:
        parts.append(f"예외={type(exc).__name__}: {exc}")
        tb = getattr(exc, "__traceback__", None)
        if tb is not None:
            frames = traceback.extract_tb(tb)[-4:]
            trace_str = " > ".join(
                f"{os.path.basename(f.filename)}:{f.lineno}({f.name})" for f in frames
            )
            if trace_str:
                parts.append(f"위치={trace_str}")
    _logger.error(" | ".join(parts))


def _log_uncaught_exception(exc_type, exc_value, exc_tb):
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _logger.critical("[치명적 예외] %s: %s", exc_type.__name__, exc_value)

sys.excepthook = _log_uncaught_exception

# 시작 시점에 환경 정보를 남겨 Render 설정 문제도 바로 확인할 수 있게 한다.
_logger.info("============================================================")
_logger.info("[뉴스봇 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
_logger.info("[환경] Render=%s | NAVER=%s(%s) | DART=%s | RSS=%s | 미국뉴스=%s | 텔레그램=%s | 유튜브=%s",
             bool(os.environ.get("PORT")), bool((NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET) or (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)), NAVER_API_MODE,
             bool(DART_API_KEY), ENABLE_DOMESTIC_NEWS, ENABLE_US_NEWS,
             ENABLE_TELEGRAM_CHANNELS, ENABLE_YOUTUBE)
_logger.info("[정상] 국내뉴스=시장반영형 | 텔레그램/유튜브=최근60분 기본 | 강한 마감후·휴무 재료만 예외")
_logger.info("============================================================")

# requests를 사용하는 기존 함수는 수정하지 않고, 모든 HTTP 요청을 자동 진단한다.
# 정상 요청은 기록하지 않고 실패만 간략하게 기록한다.
try:
    _original_session_request = requests.sessions.Session.request

    def _logged_session_request(self, method, url, **kwargs):
        started = time.time()
        try:
            response = _original_session_request(self, method, url, **kwargs)
            elapsed = time.time() - started
            if response.status_code >= 400:
                # 일시적 외부 RSS 장애(429/500/502/503/504)는 WARNING으로 기록해 장애와 봇 자체 오류를 구분한다.
                # HTML/XML 응답 원문은 운영 로그에 기록하지 않는다.
                target = _redact_url(getattr(response, "url", url))
                # 유튜브 404는 호출부의 채널ID 실패 로그와 중복되므로 생략한다.
                if not ("youtube.com" in str(target).lower() and response.status_code == 404):
                    (_logger.warning if response.status_code in (429,500,502,503,504) else _logger.error)(
                        "[HTTP 실패] %s %s | %s %s | %.2fs",
                        str(method).upper(), target,
                        response.status_code,
                        getattr(response, "reason", "") or "HTTP 오류",
                        elapsed
                    )
            else:
                pass  # 정상 요청은 로그에 남기지 않음
            return response
        except Exception as _e:
            _logger.error(
                "[HTTP 오류] %s %s | %.2fs | %s: %s",
                method, _redact_url(url), time.time() - started, type(_e).__name__, _e
            )
            raise

    requests.sessions.Session.request = _logged_session_request
except Exception as _e:
    log_error("requests 상세 로깅 초기화", _e)

# feedparser가 파싱 실패/bozo를 반환하는 경우에도 원인을 로그에 남긴다.
try:
    _original_feedparser_parse = feedparser.parse

    def _logged_feedparser_parse(*args, **kwargs):
        source = args[0] if args else kwargs.get("url", "(없음)")
        if isinstance(source, (bytes, bytearray)):
            source = "<RSS 원문 생략>"
        elif len(str(source)) > 180:
            source = str(source)[:180] + "..."
        try:
            result = _original_feedparser_parse(*args, **kwargs)
            if getattr(result, "bozo", False):
                exc = getattr(result, "bozo_exception", None)
                _logger.error(
                    "[RSS 파싱 실패] source=%s | 예외=%s: %s | entries=%s",
                    source,
                    type(exc).__name__ if exc else "unknown",
                    exc if exc else "원인 미상",
                    len(getattr(result, "entries", []) or [])
                )
            else:
                pass  # 상세 성공 로그 숨김
            return result
        except Exception as _e:
            log_error("RSS 파싱 실행", _e, source=source)
            raise

    feedparser.parse = _logged_feedparser_parse
except Exception as _e:
    log_error("feedparser 상세 로깅 초기화", _e)


# ============================================================
# 환경설정 - BOT_TOKEN, CHAT_ID, DART_API_KEY 설정
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CHAT_ID_OVERSEAS = os.environ.get("CHAT_ID_OVERSEAS", "") or CHAT_ID

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
ENABLE_NAVER_NEWS = _env_flag("ENABLE_NAVER_NEWS")               # 네이버 뉴스
ENABLE_BLOG = _env_flag("ENABLE_BLOG")                           # 분석 블로그
ENABLE_YOUTUBE = _env_flag("ENABLE_YOUTUBE")                     # 유튜브
ENABLE_SCHEDULE_REMINDERS = _env_flag("ENABLE_SCHEDULE_REMINDERS")   # 일정 D-7/D-3 리마인더
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

DART_API_KEY = os.environ.get("DART_API_KEY", "")
# NAVER_CLIENT_ID / NAVER_CLIENT_SECRET는 위에서 이미 정규화한 값을 그대로 사용한다.

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "❌ BOT_TOKEN / CHAT_ID가 비어 있습니다.\n"
        "    환경변수(BOT_TOKEN, CHAT_ID)에 값을 설정해주세요."
    )

RSS_CHECK_INTERVAL = 15          
CUSTOM_SOURCE_INTERVAL = 300     
TELEGRAM_CHANNEL_INTERVAL = 60   
TELEGRAM_UNFILTERED_INTERVAL = 60  
DART_CHECK_INTERVAL = 60         
NAVER_CHECK_INTERVAL = 300       
BLOG_CHECK_INTERVAL = 1800       
YOUTUBE_CHECK_INTERVAL = 1800    
MAIN_LOOP_TICK = 5               

US_MARKET_START_HOUR = 22
US_MARKET_END_HOUR = 6

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

PAUSED_SOURCES = {}

UNRESTRICTED_SOURCES = {
    "시황맨TV",
    "라르고TV 공식채널",
}

TARGET_TELEGRAM_CHANNELS = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
    ("뉴스짱", "https://t.me/s/newszzang"),
    ("공시알리미", "https://t.me/s/stockdartalert"),
]

TARGET_TELEGRAM_CHANNELS_UNFILTERED = [
    ("빠짐없이실적공시", "https://t.me/s/allsiljuk"),
    ("선진짱 주식공부방", "https://t.me/s/sunstudy"),
    ("시황맨의 주식이야기", "https://t.me/s/shmstory"),
    ("루팡", "https://t.me/s/bornlupin"),
    ("D의 테크 투자", "https://t.me/s/DrDtech"),
    ("요약하는 고잉", "https://t.me/s/one_going"),
    ("하나 중국/신흥국 전략 김경환", "https://t.me/s/HANAchina"),
    ("재야의 고수들", "https://t.me/s/gaoshoukorea"),
    ("도널드 J. 트럼프 대통령", "https://t.me/s/goddessTTF"),
    ("디일렉_IT신문사", "https://t.me/s/theelec"),
    ("라르고TV 공식채널", "https://t.me/s/scalpinglove"),
]

ANALYSIS_BLOG_RSS_URLS = [
    ("ranto28", "https://rss.blog.naver.com/ranto28.xml"),
    ("tosoha1", "https://rss.blog.naver.com/tosoha1.xml"),
    ("freechip", "https://rss.blog.naver.com/freechip.xml"),
    ("dkanchup", "https://rss.blog.naver.com/dkanchup.xml"),
    ("noruda11", "https://rss.blog.naver.com/noruda11.xml"),
    ("richyun0108", "https://rss.blog.naver.com/richyun0108.xml"),
    ("crush212121", "https://rss.blog.naver.com/crush212121.xml"),
    ("bsj7000", "https://rss.blog.naver.com/bsj7000.xml"),
    ("limsk1212", "https://rss.blog.naver.com/limsk1212.xml"),
    ("cart10101", "https://rss.blog.naver.com/cart10101.xml"),
    ("zero_family", "https://rss.blog.naver.com/zero_family.xml"),
    ("pokara61", "https://rss.blog.naver.com/pokara61.xml"),
    ("와이스트릿(프리미엄)", "https://contents.premium.naver.com/ystreet/irnote/rss"),
]

YOUTUBE_CHANNELS = [
    ("IT의 신 이형수", "GODofIT_official"),
    ("내일은 투자왕_단테", "김단테"),
    ("닥터조의 쉬운 바이오", "easybio_shiba"),
    ("삼프로TV", "3protv"),
    ("슈카월드", "syukaworld"),
    ("안될공학", "unrealtech"),
    ("언더스탠딩", "understanding."),
    ("엔지니어TV", "eng_tv"),
    ("와이스트릿", "Ystreet"),
    ("월가아재", "wsaj"),
    ("EZ KIPOST", "EZKIPOST-p4o"),
    ("시황맨TV", "blueoak1004"),
]

TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", "MU", "INTC",
    "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META", "TRUMP", "EARNINGS",
    "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER", "COREWAVE", "IONQ", "SMR",
    "이란", "이스라엘", "하마스", "헤즈볼라", "후티", "가자", "레바논", "시리아",
    "사우디", "카타르", "예멘", "팔레스타인", "네타냐후", "하메네이",
    "걸프", "페르시아만", "호르무즈해협",
    "전쟁", "휴전", "종전", "정전", "침공", "공습", "폭격", "미사일",
    "교전", "확전", "무력충돌", "군사충돌", "호르무즈", "봉쇄", "제재",
    "러시아", "우크라이나", "푸틴", "젤렌스키", "크렘린", "나토", "NATO",
    "대만", "대만해협", "남중국해", "북한", "김정은", "ICBM",
    "유엔", "UN", "안보리", "G7", "G20", "다보스",
    "남북", "南北", "북측", "北", "南제안", "北제안",
    "DMZ", "비무장지대",
    "개성공단", "개성연락사무소", "금강산", "금강산관광",
    "고위급", "북미대화", "북미회담", "실무협상", "실무회담",
    "연락채널", "통신연락선", "극비접촉", "방북", "북방정책", "신북방정책", "新남방정책",
    "비핵화", "핵실험", "핵추진", "인공지진",
    "발사", "로켓", "총살", "피격", "폭파", "중대보도", "중태설", "진돗개", "통치",
    "경수로", "가스관", "화력발전소", "전력망",
    "경제협력", "경제사절단", "대북사업", "북한제의",
    "이산가족", "산림복구", "조림사업", "세계생태평화공원",
    "비료", "농기계", "수산물", "인프라",
    "자원개발", "지하자원", "희토류", "광업공단",
    "나진-하산", "남-북-러", "南-北-러", "남북러", "극동장관",
    "중국", "시진핑", "자안그룹", "한중", "알리바바", "텐센트", "화웨이", "바이두",
    "양회", "니오", "CATL", "韓•中",
    "中그룹", "中관영매체", "中금지령", "中대륙", "中매출", "中매체", "中법인", "中배터리",
    "中시장", "中사업", "中수출", "中상용화", "中수소차", "中식약청", "中언론", "中외교부",
    "中업체", "中진출", "中정부", "中전기차", "中최대", "中흥행", "中CFDA", "中공급",
    "中공장", "中파트너사", "中잡지", "中현지", "中합작법인",
    "샤오미", "BYD", "비야디", "지리자동차", "징둥", "JD닷컴", "메이투안",
    "핀둬둬", "틱톡", "바이트댄스", "SMIC", "중신궈지", "폭스콘", "레노버",
    "DJI", "아이플라이텍", "센스타임", "이항", "샤오펑", "샤오펑모터스", "리오토",
    "BOE", "징둥팡", "차이나모바일", "차이나텔레콤", "페트로차이나", "시노펙",
    "공상은행", "건설은행", "초상은행",
    "AI바이러스", "SFTS", "광우병", "구제역", "뎅기열", "돼지독감", "돼지콜레라",
    "로타바이러스", "메르스", "브루셀라", "사스", "진드기", "소두증",
    "슈퍼바이러스", "슈퍼박테리아", "신종플루", "에볼라", "에이즈", "인플루엔자",
    "조류독감", "조류인플루엔자", "지카", "코로나", "콜레라",
    "세계보건기구", "WHO",
    "고병원성", "바이러스", "박테리아", "법정감염병", "변이", "변종",
    "사람간", "사망", "성관계", "성접촉", "性접촉", "신종",
    "양성반응", "양성판정", "양성환자", "의심신고", "의심환자",
    "첫감염", "첫발생", "첫환자", "콘돔", "항바이러스",
    "확산", "확진", "환자급증", "침에서",
]

US_MACRO_STRONG_WORDS = {
    "FED", "POWELL", "TRUMP", "EARNINGS",
    "전쟁", "침공", "공습", "폭격", "미사일", "교전", "확전", "호르무즈",
}

KEYWORDS_1 = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴", "키옥시아", "창신메모리",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
    "반도체", "AI", "인공지능", "자율주행", "전기차", "이차전지", "배터리",
    "수소", "태양광", "원전", "전력", "로봇", "UAM", "메타버스", "블록체인", "양자",
    "방산", "조선",
    "누리호", "발사체", "위성", "저궤도위성", "스타링크", "SpaceX", "우주항공청",
    "스테이블코인",
    "남북", "대북",
    "실적", "상장", "공시", "특허",
]

KEYWORDS_2 = [
    "계약", "공급", "체결", "수주", "수출", "납품", "독점", "라이선스", "입찰", "MOU",
    "승인", "허가", "인가",
    "인수", "합병", "매각", "지분", "투자", "유치", "출자전환",
    "유상증자", "무상증자", "전환사채", "최대주주변경", "경영권분쟁",
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
    "양산", "출시", "개발", "완료", "착수", "상용화", "완치",
    "타결", "협약", "합의", "제휴",
    "가닥", "가상현실", "가속화", "가시화", "가치부각", "개발성공", "개발中", "개발중",
    "개시", "개시결정", "거래재개", "결론낸다", "계약체결", "공개매각", "공급계약", "공급중",
    "공급中", "공동개발", "공동관리", "공동연구", "공동제작", "공동투자", "공식제안", "공식진출",
    "공식화", "공식확인", "공약검토", "국산화", "국회통과", "극적타결", "극적-타결", "금지",
    "급부상", "급증", "급증에", "기능적완치", "기술개발", "기술도입", "기술보유", "기술수출",
    "기술이전", "껑충", "도입추진", "독점계약", "독점공급", "독점생산", "독점권", "독점기술",
    "독점사업권", "독점운영", "독점판권", "대란", "라이선스계약", "러브콜", "매물로", "비상",
    "발표", "발표키로", "발표하나", "발표할듯", "범위확대", "보급", "본격화", "본계약",
    "본입찰", "부품공급", "부품사", "부품사와", "분쟁", "분할", "불티", "사업추진",
    "사재투입", "상업화", "상장", "상장유지", "상장추진", "상품공급", "새주인", "생산",
    "생산계약", "선언", "선정", "선정계획", "선포", "설립", "설립추진", "성공",
    "소재공급", "손잡고", "손잡는다", "쇄도", "수주전", "수출길", "수출재개", "수출허가",
    "승인신청서", "승인심사", "시동", "시동거나", "시장진출", "시판", "시판허가", "시험계획",
    "시험생산", "신청", "신호탄", "실탄", "실시허가", "실사허가", "실질심사", "양산체계",
    "연구", "연구개발", "연구지원", "연구참여", "예감", "예고", "예약", "완전관해",
    "완전해소", "완치성공", "완판", "완판행진", "완화", "위생허가", "유력", "의무화",
    "인기몰이", "인상", "인수검토", "인수설", "인수전", "인수추진", "인수키로", "인수하기로",
    "인수하나", "인수한다", "인수합병", "인허가", "임박", "임상", "임상1상", "임상2상",
    "임상3상", "임상결과", "임상시험", "임상신청", "임상실험", "임상실험서", "임상치료", "임상허가",
    "임상효과", "입점", "입증", "잇따라", "위탁생산(CMO)", "위탁생산", "위탁생산한다", "연구발표",
    "재개", "재매각", "재상장", "재시동", "재인수", "재점화", "재추진", "재판매",
    "재평가", "재협상", "재확인", "잭팟", "적정", "제네릭사", "제안", "제안키로",
    "제안하기로", "제안할듯", "제의", "제출", "중국진출", "증가", "증설", "증시상장",
    "지분가치", "지분매각", "지분인수", "지분투자", "지원과제", "진단기술", "진출", "집중투자",
    "첫승인", "청신호", "최대유통", "최대주주된다", "최고치", "최대치", "최종임상", "추진",
    "추진설", "추진중", "추진키로", "추진할", "취득", "출범", "타당성", "탄력",
    "탑재", "통과", "투입", "투약", "투자한", "투자유치", "투자제안", "투자합작",
    "피인수", "판권계약", "판권인수", "판매", "판매개시", "판매계약", "판매권", "판매승인",
    "판매허가", "팔렸다", "품귀", "품귀현상", "품는다", "품목허가", "품절", "합류",
    "합자기업", "합작", "해소", "해제", "해지", "해체", "허가승인", "허가신청",
    "허가심사", "허가취득", "허용", "허용검토", "협력", "협력키로", "협상", "협의",
    "협의중", "협의中", "확보", "확정", "회생계획", "회생절차", "획득", "효과입증",
    "효능입증", "흥행", "매각설", "비밀유지계약", "상장설", "액면분할", "우회상장", "3상",
    "美임상3상", "치료제3상", "임상1b상", "임상2b상", "임상3b상", "미FDA", "美FDA", "美FDA에",
    "美FDA임상", "흑자전환", "최대매출", "최대-매출", "투자판단", "흡수합병", "분할합병", "3자배정",
    "제3자배정", "주식분할", "주식합병", "M&A", "M&A타진", "경영참여", "경영참가",
    "핵심기술", "국내최초", "최대투자", "주문폭주", "역대급", "공급부족", "세계최초", "표대결",
]

EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트",
    "마켓파워", "인베스트조선", "[핫!종목]", "핫!종목",
    "[SP단독]", "[단독]", "단독", "풍문",
]

BLOCKED_KEYWORDS_BY_CATEGORY = {
    "🧹 광고성": ["스탁론"],
    "🧹 사진·생활정보": ["포토", "화보", "날씨", "운세"],
    "🧹 부고·인사": ["부고", "별세", "인사", "동정", "취임", "퇴직", "승진", "조문", "만찬", "영입", "선임", "위촉", "임명", "발탁", "조직개편"],
    "🧹 시상·행사": ["수상", "기념", "축제", "콘서트", "전시", "간담회", "워크숍"],
    "🧹 스포츠": ["야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "홈런", "승리", "패배", "우승", "득점", "실점", "연패", "연승"],
    "🧹 연예·문화": ["연예인", "영화", "드라마", "뮤지컬", "음원", "시사회", "팬미팅"],
    "🧹 사건·사고": ["사건", "사고", "붕괴", "화재", "음주운전", "구속", "징역", "폭행", "스캔들", "이혼", "결혼", "출산"],
    "🧹 부동산·생활경제": ["낙찰", "분양", "출시", "예산", "청약", "접수", "대표팀", "화제", "논란", "논쟁", "비판"],
    "🧹 행정·일반": ["교육", "주민", "점검", "의원", "채용", "업무", "의견", "정비", "임원", "현장", "응찰"],
    "🧹 블로그 잡담성": ["홧팅", "화이팅", "가즈아", "월욜", "화욜", "수욜", "목욜", "금욜", "불금"],
    "🧹 답글·댓글성": ["답글", "댓글", "리플", "re:", "RE:", "Re:", "댓글창"],
    "🧹 찌라시·홍보성 클릭베이트": [
        "수혜株!", "급등예고!", "관련株!", "극비재료주", "오늘의추천株", "잡아라!!", "잡아라!", "폭등임박!", "황제주!", "황제주!!", "급등임박", "급등임박!",
        "알짜매물", "오늘의", "오늘장", "코넥스", "[장외주식]", "[장외주식시황]", "[종합시황]", "테마동향", "위클리", "비결", "주간결산", "투자자의",
        "추천", "추천종목", "추천주", "주간추천종목", "주간추천주", "장마감후종목뉴스", "증권거래현황", "증권사별", "주간업종등락률", "투자記", "투자자별", "투자주체",
        "투자주체를", "현재가", "꺾고", "'上'진입", "놓치면", "즐기세요", "아듀", "시황", "증시일정",
    ],
    "🧹 지역·지자체 행정": [
        "화순군", "경남", "경기", "경기도", "광주", "인천서", "예천군", "울산", "강릉", "수원시", "재난지원금", "희망재단",
        "취약계층", "거리두기", "접종", "건보공단", "검진", "예방접종", "가뭄피해", "국감", "국감서", "국정감사", "국정원", "관세청",
        "교역", "강진군", "경남도", "고양시", "공주시", "광양시", "광주시", "광주전남", "남양주", "남양주시", "대구경북", "무안",
        "무안군", "무안서", "밀양시", "보성군", "봉화군", "서대문구", "순천시", "아산시", "안산시", "양산시", "양산신도시", "양양군",
        "영광군", "영덕군", "영등포구", "영암군", "용인시", "울릉서", "음성군", "익산시", "인천시", "장흥군", "전남", "전남도",
        "전북", "전북도", "전주시", "정읍시", "진주시", "창원시", "천안시", "청송군", "청주시", "충남도", "충주시", "태백시",
        "통영시", "파주시", "판교", "평택시", "함평군", "해남군", "호남선", "경기도의회", "원주시의회", "잠실", "장마철", "장맛비",
        "재산세", "저소득층", "서민", "서민층",
    ],
    "🧹 대학·병원·기관명": [
        "삼육대", "목포대", "호남대", "단국대", "영남대", "연세대", "한국폴리텍대학", "폴리텍대학", "광주대", "성신여대", "계명대", "원광대",
        "대구한의대", "한남대", "영남대병원", "전남대병원", "화순전남대병원", "전북대병원", "광주은행", "부산농협", "의료원", "LH", "SK행복나눔재단",
    ],
    "🧹 언론사 코너·연재물 태그": [
        "[표]", "[경기인터뷰]", "[공감]", "[기자가만난세상]", "[기획]", "[김능구의정국진단]", "[녹색세상]", "[단상]", "[디지털산책]", "[롤드컵]", "뉴스&분석", "뉴스브리핑",
        "뉴스해설", "뉴욕마켓워치", "[fn★성적표]", "[GOAL]", "[LPGA]", "ML사이트]", "[PGA]", "[SS스타기상청]", "[SS영상]", "[SS위클리토크]", "[SS프리즘]", "[TD영상]",
        "[TV예감]", "[WCS]", "[WTKL]", "[WT논평]", "[y스페셜]", "[답변공시]", "[종목상담]", "DT광장", "ET단상", "fn사설", "HD영상", "K팝스타",
        "MISS출장대행", "SK전", "SS다시보기", "SS인턴수첩", "SS탐사보도", "S스토리", "TV신문고", "TV줌인", "TV프로그램", "TV하이라이트", "US여자오픈", "US오픈",
        "V라이브", "Why", "y피플", "[美친box]", "[美친차트]", "[美친시청률]", "[창간특집]", "[e2BOT]", "[생생건강]", "[스포츠투데이]", "[와글와글]", "[연예]",
        "[투데이]", "ET투자뉴스", "경인만평", "경인포터", "경향NIE", "뉴스파이터", "모닝와이드", "오프닝", "헤드라인", "전체뉴스", "MVP", "SHOT",
        "HOLD(유지)", "UFC", "다시보기", "해설",
    ],
    "🧹 거시지표·환율(루틴 발표)": [
        "고시환율", "기준환율", "달러/위안", "달러/환율", "원•달러", "환율", "고용동향", "고용지표", "실업률", "실업률은", "성장률", "소비자물가",
        "저금리", "재정난", "재정증권", "수출액", "수출입은행", "무역", "소득공제", "도매재고", "물동량", "상하이지수", "생산자물가", "생산자물가지수",
        "수주액", "수입물가", "신규주택", "산업생산", "산업생산도", "소매판매", "증가폭", "전월비", "전월比", "제조업생산", "주택착공실적", "최저임금",
        "가계대출", "주택담보대출", "기업재고", "경기침체", "경매시장", "법원경매", "입주", "입주아파트", "입주예정", "주택금융", "주택금융공사",
    ],
    "🧹 기업·행정 잡무 일반": [
        "강소기업", "강좌", "개강", "개관", "개막식", "개선", "개장", "개최", "개통", "결산", "공동캠퍼스",
        "개설", "경력사원", "과징금", "관리우수기업", "우수기업", "우수기관", "우수사업단", "우수인증기관", "우수기관으로", "유네스코",
        "중소기업", "중소기업청", "中企", "중기중앙회", "사옥", "신제품", "신축공사", "준공", "준공식", "참가자", "창단", "출연",
        "취업난", "취재", "취재수첩", "축소", "총력", "철회", "창출", "창출에", "캠페인", "캠퍼스", "품질향상", "한정판",
        "한정판매", "할인", "할인판매", "할인행사", "행사", "홈페이지", "홈플러스", "크리스마스", "어린이", "어린이날", "앨범", "나눔",
        "행복나눔", "열린광장", "열린마당", "열린세상", "전당대회", "헌법", "한국인", "한은", "특가상품", "교통정보", "가족캠프", "모집",
    ],
    "🧹 잡담·일반 표현": [
        "미안", "미안하다", "눈길", "뇌물", "노출", "노조", "반발", "방송", "불공정", "부결", "부과", "불발",
        "불투명", "불안감", "불법자금", "방산비리", "감독", "감소", "간부", "경험", "기록", "기고", "기자수첩", "기획전",
        "기업분석리포트", "금융단신", "금융사", "리포트", "브리핑", "논평", "대표연설", "동영상", "녹화", "달성", "둘째주", "셋째주",
        "디지털세상", "이시각", "인덱스", "인터뷰", "임금", "연속", "연임", "유출", "열정", "일반공모", "증권사", "재무리스크",
        "적정수준", "전망", "전일대비", "제공", "주의보", "준수해야", "지표", "직장인", "집중취재", "조회공시", "공시", "기업공시",
        "e공시", "대파", "소폭", "선보여", "선봬", "선수단", "선도", "선보인다", "이벤트", "영상", "예방수칙", "운전자",
        "운행", "유가증권", "유가증권시장", "음주", "투표", "페스티벌", "포럼", "피해액만", "파문", "현황", "토마토",
        "파라다이스", "기자들의", "사진", "사설", "상담회", "상생경영", "소개", "평생", "폐쇄", "침묵", "진통",
        "저축", "종료", "증발", "중단", "전일", "정정", "가려움증", "버스회사", "보험", "보험금", "보험사", "신년사",
        "제동", "증상들", "키워드", "펀드",
    ],
    "🧹 달력·숫자 패턴": ["주년", "루수", "호선", "01월", "02월", "03월", "04월", "05월", "06월", "07월", "08월", "09월"],
}

BLOCKED_KEYWORDS = set()
for _category, _words in BLOCKED_KEYWORDS_BY_CATEGORY.items():
    BLOCKED_KEYWORDS |= set(_words)


def is_blocked_title(title):
    if not title:
        return False
    return any(word in title for word in BLOCKED_KEYWORDS)


GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "네이버", "카카오", "두산", "한화", "HD현대", "LS",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
]

NAVER_EXTRA_THEME_QUERIES = [
    "반도체", "HBM", "이차전지", "AI 반도체", "로봇", "방산", "원전",
    "조선", "바이오", "양자컴퓨팅", "우주항공",
]

UNIQUE_KEYWORDS_1 = set(KEYWORDS_1)
UNIQUE_KEYWORDS_2 = set(KEYWORDS_2)
UNIQUE_EXCLUSIVE = set(EXCLUSIVE_KEYWORDS)
UNIQUE_TARGET = set(TARGET_KEYWORDS)
UNIQUE_GIANTS = set(GLOBAL_AND_DOMESTIC_GIANTS)
UNIQUE_CELEBS = {
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명"
}

GLOBAL_COMPANY_KEYWORDS = {
    # 한글 표기 (번역 후 본문에서 매칭)
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "알파벳", "아마존", "메타",
    "인텔", "마이크론", "넷플릭스", "오픈AI", "팔란티어", "브로드컴", "퀄컴",
    "슈퍼마이크로", "AMD", "ASML", "TSMC",
    "코스트코", "월마트", "스타벅스", "디즈니", "보잉", "포드", "제너럴모터스",
    "JP모건", "골드만삭스", "버크셔해서웨이", "비자", "마스터카드", "페이팔",
    "어도비", "세일즈포스", "오라클", "IBM", "시스코", "퀄컴", "리비안", "루시드",
    "코인베이스", "마이크로스트래티지", "스트래티지",
    # 영문 원문(번역 실패/일부 미번역 대비 fallback)
    "Nvidia", "Tesla", "Apple", "Microsoft", "Google", "Alphabet", "Amazon", "Meta",
    "Intel", "Micron", "Netflix", "OpenAI", "Palantir", "Broadcom", "Qualcomm",
    "Super Micro", "SMCI", "Costco", "Walmart", "Starbucks", "Disney", "Boeing",
    "Ford", "General Motors", "JPMorgan", "Goldman Sachs", "Berkshire Hathaway",
    "Visa", "Mastercard", "PayPal", "Adobe", "Salesforce", "Oracle", "IBM", "Cisco",
    "Rivian", "Lucid", "Coinbase", "MicroStrategy", "Strategy",
}

KOREAN_GROUP_NAMES = {
    "삼성", "SK", "LG", "현대차", "현대중공업", "현대", "롯데", "포스코", "한화",
    "GS", "농협", "신세계", "KT", "두산", "CJ", "한진", "카카오", "네이버",
    "HD현대", "신한", "KB", "하나", "우리", "미래에셋", "코오롱", "효성",
    "DL", "DB", "OCI", "금호아시아나", "이랜드", "태광", "세아", "부영",
    "중흥건설", "아모레퍼시픽", "교보생명", "한국타이어", "애경", "KCC",
    "삼천리", "영풍", "하림", "HMM", "S-Oil", "LS", "동원",
}

PHARMA_KEYWORDS = {
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
}

US_MARKET_KEYWORDS = {
    "나스닥", "다우", "S&P500", "뉴욕증시", "국채", "금리", "연준", "FOMC",
    "관세", "인플레이션", "CPI", "PCE", "고용지표", "실업률", "필라델피아반도체지수",
    "환율", "달러", "유가", "장중",
}

US_CONTENT_KEYWORDS = UNIQUE_TARGET | GLOBAL_COMPANY_KEYWORDS | US_MARKET_KEYWORDS

US_FEATURE_STOCK_WORDS = {
    "surge", "surges", "surging", "soar", "soars", "soaring", "jump", "jumps",
    "rally", "rallies", "spike", "spikes", "plunge", "plunges", "plunging",
    "tumble", "tumbles", "skyrocket", "skyrockets", "sink", "sinks", "slump",
}
US_BREAKING_WORDS = {"breaking", "just in", "alert"}

US_EARNINGS_WORDS = {
    "earnings", "quarterly results", "q1 results", "q2 results", "q3 results",
    "q4 results", "guidance", "revenue", "eps",
}
US_EARNINGS_BEAT_WORDS = {"beats", "beat", "tops", "exceeds", "surpasses"}
US_EARNINGS_MISS_WORDS = {"misses", "miss", "falls short", "below estimates"}


def _extract_earnings_info(title):
    title_lower = title.lower()
    is_earnings = any(w in title_lower for w in US_EARNINGS_WORDS) or "실적" in title

    if not is_earnings:
        return False, None, None, None

    beat_or_miss = None
    if any(w in title_lower for w in US_EARNINGS_BEAT_WORDS) or "어닝서프라이즈" in title:
        beat_or_miss = "beat"
    elif any(w in title_lower for w in US_EARNINGS_MISS_WORDS) or "어닝쇼크" in title:
        beat_or_miss = "miss"

    revenue = None
    rev_match = re.search(r"revenue[^\d]{0,10}\$?([\d,.]+)\s*(billion|million|B|M)", title, re.I)
    if rev_match:
        unit = "billion" if rev_match.group(2).lower().startswith("b") else "million"
        revenue = f"${rev_match.group(1)} {unit}"

    eps = None
    eps_match = re.search(r"EPS[^\d]{0,10}\$?([\d.]+)", title, re.I)
    if eps_match:
        eps = f"${eps_match.group(1)}"

    return True, beat_or_miss, revenue, eps

MONEY_STRONG_WORDS = {
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
}

STRONG_KEYWORDS_1 = UNIQUE_KEYWORDS_1
STRONG_KEYWORDS_2 = UNIQUE_KEYWORDS_2

DART_WATCH_COMPANIES = set(GLOBAL_AND_DOMESTIC_GIANTS)
DART_RUMOR_KEYWORDS = ["조회공시", "풍문", "보도", "해명", "설명요구"]

# [불변 명령체계] 최신 사용자 지시가 최우선이며 충돌하는 하위 출력 명령은 실행하지 않는다.
LATEST_USER_COMMAND_WINS = True
COMMAND_PRIORITY_POLICY = ("LATEST_USER_COMMAND",)
# 하위 명령/출력 레이어는 사용자 최우선 명령을 덮어쓸 수 없다.
DISABLE_LEGACY_SUBCOMMAND_OVERRIDES = True

DART_STRONG_REPORT_KEYWORDS = {
    "유상증자결정", "무상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정",
    "교환사채권발행결정", "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정",
    "영업양수결정", "영업양도결정", "합병결정", "분할결정", "분할합병결정",
    "주식교환ㆍ이전결정", "주식교환·이전결정", "감자결정",
    "자기주식취득결정", "자기주식처분결정",
    "최대주주변경", "경영권분쟁", "매출액또는손익구조",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결",
    "특허권취득", "임상시험계획승인", "품목허가", "우회상장", "주요사항보고서",
    "회생절차", "파산신청", "관리종목", "상장폐지", "불성실공시법인",
    "흑자전환", "적자전환",
    "감사의견거절", "감사의견부적정", "감사의견한정",
    "공개매수",
    "유형자산양수결정", "유형자산양도결정",
    "주식병합결정", "주식분할결정",
    "배당결정",
    "신규시설투자",
    "소송등의제기",
    "투자판단관련주요경영사항",
    "자산재평가실시결정",
    "채권은행관리절차",
    "대량보유상황보고서",
    "주식등의대량보유상황보고서",
    "양수결정", "양도결정",
    "추가상장",
}

DART_ALWAYS_EXPOSE_KEYWORDS = DART_STRONG_REPORT_KEYWORDS - {
    "유상증자결정",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결",
    "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정",
    "영업양수결정", "영업양도결정", "합병결정", "분할결정", "분할합병결정",
    "자기주식취득결정",
    "주요사항보고서",
}

DOMESTIC_RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://www.hankyung.com/feed/all-news",
    "https://www.mk.co.kr/rss/30000001/",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    "http://www.cstimes.com/rss/allArticle.xml",
    "https://politepol.com/fd/lRjhc60Zukff",
    "http://www.theguru.co.kr/data/rss/section_30.xml",
    "https://www.theguru.co.kr/data/rss/news.xml",
]

DOMESTIC_RSS_SOURCE_NAMES = {
    "https://www.yna.co.kr/rss/economy.xml": "연합뉴스",
    "https://www.hankyung.com/feed/all-news": "한국경제",
    "https://www.mk.co.kr/rss/30000001/": "매일경제",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko": "Google",
    "http://www.cstimes.com/rss/allArticle.xml": "CS타임즈",
    "https://politepol.com/fd/lRjhc60Zukff": "폴리트폴",
    "http://www.theguru.co.kr/data/rss/section_30.xml": "더구루",
    "https://www.theguru.co.kr/data/rss/news.xml": "더구루",
}

def _google_news_rss_url(query, korean=False):
    from urllib.parse import quote_plus
    # [수정] "when:1h"를 검색어에 직접 넣으면 Google News가 복잡한 boolean 쿼리와
    # 결합될 때 결과를 0건으로 반환하는 경우가 잦다(불리언+시간창 동시 파싱 신뢰도 낮음).
    # 실시간성 보장은 어차피 _engine_process_item()의 "최근 60분" 게이트가 이미
    # 담당하고 있으므로, 수집 단계에서는 시간 제약 없이 넓게 가져오고 필터링은
    # 다운스트림(발행시각 기준)에서 정확하게 처리한다. → 이중 시간필터로 후보가
    # 과도하게 희박해지는 문제를 해소한다.
    encoded = quote_plus(query)
    if korean:
        return f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


US_RSS_URLS = [
    _google_news_rss_url("US Stock Market Trump Earnings SKHY Nvidia Semiconductor Oil Gold Copper"),
    _google_news_rss_url("(Nvidia OR AMD OR Micron OR Broadcom OR TSMC) AND (surge OR earnings OR guidance OR chip)"),
    _google_news_rss_url('(Fed OR "Federal Reserve" OR "interest rate" OR inflation) AND (rate cut OR hike OR CPI)'),
    _google_news_rss_url("(Tesla OR Microsoft OR Amazon OR Meta OR Alphabet) AND (earnings OR beats OR misses OR plunge OR surge)"),
    _google_news_rss_url("미국증시 나스닥 다우 S&P500 반도체", korean=True),
    _google_news_rss_url("미국 연준 금리 FOMC 인플레이션", korean=True),
    _google_news_rss_url("테슬라 엔비디아 마이크론 애플 아마존 급등 급락", korean=True),
]

NAVER_SEARCH_QUERIES = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS + NAVER_EXTRA_THEME_QUERIES + [
    "특징주", "속보 주식", "주식 속보", "급등 급락 주식", "상한가 주식", "단독 주식",
    "수주 공급계약 임상 승인 실적", "삼성전자 SK하이닉스 특징주", "반도체 특징주", "바이오 특징주"
]))

US_MARKET_INDICES = [
    ("나스닥", "^IXIC"),
    ("S&P500", "^GSPC"),
    ("다우", "^DJI"),
    ("러셀2000", "^RUT"),
    ("필라델피아반도체(SOX)", "^SOX"),
    ("VIX(공포지수)", "^VIX"),
    ("원/달러 환율", "USDKRW=X"),
    ("WTI 유가", "CL=F"),
]
# ============================================================
# [실행 엔진 복구] 1분 주기 실시간 수집/분석/텔레그램 전송
# ============================================================
# 이 파일에는 설정/키워드만 남고 실제 반복 실행부가 빠진 경우에도
# 뉴스 수집이 멈추지 않도록 독립 실행 엔진을 붙인다.
# 기존 설정값/키워드/환경변수는 그대로 사용한다.

ENGINE_INTERVAL = 60

# ============================================================
# [일정 DB / 1년 과거 특징주·급등뉴스 + 중요 공시 + 미국/기업 일정]
# - 과거 약 1년의 특징주/급등/상한가/대형재료 뉴스에서 미래 일정만 추출
# - 뉴스 속 일정은 큰 이벤트만 저장
# - DART는 급등 가능성이 있는 주요 공시만 일정화
# - 미국 시장/기업 일정은 가까운 날짜순으로 병합
# - 매일 KST 07:00 / 19:00에 한 번씩 자동 전송
# ============================================================
SCHEDULE_DB_FILE = os.environ.get("NEWS_BOT_SCHEDULE_DB", "news_bot_schedule.jsonl")
SCHEDULE_STATE_FILE = os.environ.get("NEWS_BOT_SCHEDULE_STATE", "news_bot_schedule_send_state.json")
SCHEDULE_BOOTSTRAP_STATE = os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_STATE", "news_bot_schedule_bootstrap.json")
SCHEDULE_LOOKBACK_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_LOOKBACK_DAYS", "365")))
SCHEDULE_FORWARD_DAYS = max(7, int(os.environ.get("NEWS_BOT_SCHEDULE_FORWARD_DAYS", "120")))
SCHEDULE_MAX_ITEMS = max(10, int(os.environ.get("NEWS_BOT_SCHEDULE_MAX_ITEMS", "80")))
SCHEDULE_BOOTSTRAP_MAX_CHECKED = max(1000, int(os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_MAX_CHECKED", "6000")))
SCHEDULE_DAILY_FORWARD_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_DAILY_FORWARD_DAYS", "180")))
SCHEDULE_BOOTSTRAP_QUERIES = [
    '특징주 상한가 급등 일정 발표 예정',
    '상한가 종목 재료 일정 실적 발표 임상 승인',
    '급등주 특징주 수주 공급계약 양산 출시 상용화 일정',
    '상한가 급등 종목 계약 투자 증설 기술이전 마일스톤 일정',
    '특징주 종목 임상 결과 FDA 승인 기술수출 일정',
    '미국 기업 실적 발표 일정 반도체 AI 빅테크',
    '미국 주요 경제지표 FOMC CPI PCE 고용 GDP 일정',
    '한국 증시 주요 일정 실적발표 임상 수주 공시',
]
SCHEDULE_MAJOR_WORDS = {
    '실적발표','실적 발표','어닝','임상','임상시험','허가','승인','품목허가','FDA',
    '수주','공급계약','계약 체결','공급 개시','양산','출시','상용화','기술이전',
    '마일스톤','주주총회','합병','분할','공개매수','증자','신규시설투자','증설',
    'FOMC','CPI','PCE','고용지표','금리결정','잭슨홀','GDP','ISM','소비자물가',
}
SCHEDULE_NOISE_WORDS = {'텔레그램','조회수','좋아요','구독','광고','이벤트','쿠폰','게시','업로드'}

def _schedule_load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 로드 실패 | %s | %s', path, str(e)[:120])
    return default

def _schedule_save_json(path, obj):
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 저장 실패 | %s | %s', path, str(e)[:120])

def _schedule_append(row):
    key = str(row.get('key') or '')
    if not key:
        key = '|'.join([str(row.get('date','')), str(row.get('title','')), str(row.get('source',''))])
        row['key'] = key
    try:
        existing = set()
        if os.path.exists(SCHEDULE_DB_FILE):
            with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        x=json.loads(line); existing.add(str(x.get('key','')))
                    except Exception:
                        pass
        if key in existing:
            return False
        with open(SCHEDULE_DB_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return True
    except Exception as e:
        _engine_log('warning', '[일정] DB 저장 실패 | %s', str(e)[:160])
        return False

def _schedule_load_rows():
    rows=[]
    if not os.path.exists(SCHEDULE_DB_FILE):
        return rows
    try:
        with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    r=json.loads(line)
                    if r.get('date'): rows.append(r)
                except Exception:
                    continue
    except Exception as e:
        _engine_log('warning', '[일정] DB 읽기 실패 | %s', str(e)[:160])
    return rows

def _schedule_parse_date(text, base=None):
    t=_engine_clean(str(text or ''))
    base = base or _now_kst().date()
    pats=[
        r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})',
        r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일',
        r'(\d{1,2})\s*월\s*(\d{1,2})\s*일',
    ]
    for pat in pats:
        m=re.search(pat,t)
        if not m: continue
        try:
            if len(m.groups())==3:
                y,mo,d=map(int,m.groups())
            else:
                y=base.year; mo,d=map(int,m.groups())
            dt=datetime.date(y,mo,d)
            if dt < base - datetime.timedelta(days=2) and len(m.groups())==2:
                dt=dt.replace(year=y+1)
            return dt
        except Exception:
            continue
    return None

def _schedule_is_high_impact_context(text, companies=None, market_hits=None):
    t=str(text or '').lower()
    strong = [
        '상한가','급등','특징주','대규모 수주','초대형 수주','대형 계약','공급계약',
        '기술수출','기술이전','마일스톤','임상 결과','임상 성공','허가','승인','fda',
        '양산','상용화','출시','신규시설투자','증설','대규모 투자','실적 서프라이즈',
        '어닝 서프라이즈','자사주','공개매수','합병','분할','유상증자','제3자배정'
    ]
    if any(x in t for x in strong):
        return True
    return bool(companies or market_hits) and any(x in t for x in SCHEDULE_MAJOR_WORDS)

def _schedule_extract_from_text(title, extra, source, published='', companies=None, market_hits=None, limitup=False):
    text=_engine_clean(f'{title} {extra}')
    if not text or any(w in text.lower() for w in SCHEDULE_NOISE_WORDS):
        return None
    if not any(w.lower() in text.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    if not _schedule_is_high_impact_context(text, companies, market_hits) and not limitup:
        return None
    base=_now_kst().date()
    date_patterns=[
        r'20\d{2}[./-]\d{1,2}[./-]\d{1,2}',
        r'20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'(?:올해|금년|내년)\s*(?:하반기|상반기)',
        r'(?:올해|금년|내년)\s*(?:\d{1,2}분기|\d{1,2}Q)',
        r'(?:다음달|내달|다음주|이번달|이번주|다음 분기|이번 분기)',
    ]
    found=None
    for pat in date_patterns:
        m=re.search(pat,text,re.I)
        if m:
            found=m.group(0); break
    if not found:
        return None
    dt=_schedule_parse_date(found,base)
    if not dt:
        # 상반기/하반기/분기/상대기간은 정확한 날짜를 만들 수 없으므로 날짜 DB에는 보류하지 않는다.
        return None
    if dt < base or dt > base+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS):
        return None
    pos=text.find(found)
    snippet=text[max(0,pos-160):min(len(text),pos+260)].strip()
    if not any(w.lower() in snippet.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    category='공시' if str(source).startswith('DART') else ('미국일정' if 'US' in str(source) or 'Google-US' in str(source) else '뉴스일정')
    tag='상한가연계' if limitup else '특징주연계' if any(x in text.lower() for x in ('특징주','급등')) else '주요뉴스'
    company_text='·'.join((companies or [])[:3])
    key=f'{dt.isoformat()}|{category}|{tag}|{company_text}|{re.sub(r"[^0-9a-zA-Z가-힣]", "", snippet.lower())[:120]}'
    return {
        'key':key,
        'date':dt.isoformat(),'category':category,'source':str(source),
        'tag':tag,'companies':list((companies or [])[:5]),
        'title':str(title).strip()[:220],'detail':snippet[:300],
        'link':'','created_at':_now_kst().isoformat(),
    }

def _schedule_add_news_item(source, title, extra, link, published='', companies=None, market_hits=None):
    text=_engine_clean(f'{title} {extra}')
    low=text.lower()
    limitup=any(x in low for x in ('상한가','상한가 기록','상한가 마감'))
    row=_schedule_extract_from_text(title, extra, source, published, companies, market_hits, limitup=limitup)
    if row:
        row['link']=str(link or '')
        if _schedule_append(row):
            _engine_log('info','[일정DB 누적] %s | %s | %s', row['date'], row['tag'], row['title'][:90])
            return True
    return False

def _schedule_bootstrap_one_year():
    state=_schedule_load_json(SCHEDULE_BOOTSTRAP_STATE,{})
    if state.get('done'):
        return
    # 최초 1회는 최근 1년을 월/주 단위로 잘게 나눠 최대한 빠짐없이 훑는다.
    # 특히 상한가·특징주·급등 재료를 별도 검색어로 넓게 수집한다.
    from urllib.parse import quote_plus
    today=_now_kst().date()
    start=today-datetime.timedelta(days=SCHEDULE_LOOKBACK_DAYS)
    added=0; checked=0; requests_count=0
    cursor=start
    while cursor < today and checked < SCHEDULE_BOOTSTRAP_MAX_CHECKED:
        end=min(today,cursor+datetime.timedelta(days=14))
        for q in SCHEDULE_BOOTSTRAP_QUERIES:
            if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
            url=f'https://news.google.com/rss/search?q={quote_plus(q)}%20after%3A{cursor.isoformat()}%20before%3A{end.isoformat()}&hl=ko&gl=KR&ceid=KR:ko'
            entries=_engine_fetch_rss(url,'일정DB/1년초기검색')
            requests_count += 1
            for e in entries:
                if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
                checked += 1
                title=e.get('title',''); extra=e.get('summary','') or e.get('description','')
                low=_engine_clean(f'{title} {extra}').lower()
                if not any(x in low for x in ('특징주','급등','상한가','수주','공급계약','임상','승인','허가','실적','양산','상용화','기술이전','마일스톤','fomc','cpi','pce','고용','gdp')):
                    continue
                row=_schedule_extract_from_text(title, extra, '일정DB/1년초기검색', e.get('published',''), limitup=('상한가' in low))
                if row:
                    row['link']=e.get('link','') or ''
                    if _schedule_append(row): added+=1
        cursor=end+datetime.timedelta(days=1)
    _schedule_save_json(SCHEDULE_BOOTSTRAP_STATE,{
        'done':True,'completed_at':_now_kst().isoformat(),
        'checked':checked,'added':added,'requests':requests_count,
        'lookback_days':SCHEDULE_LOOKBACK_DAYS,
        'note':'최초 1년 전수형 일정 후보 검색 완료. 이후 매일 뉴스/DART에서 지속 누적.'
    })
    _engine_log('info','[일정DB] 최초 1년 전수형 초기화 완료 | 확인=%d | 신규=%d | RSS요청=%d',checked,added,requests_count)

def _schedule_add_dart_row(report, corp, link, rcept_dt):
    # DART 접수일 자체는 과거 일정으로 저장하지 않고, 보고서명에 미래 이벤트가 있을 때만 추출한다.
    row=_schedule_extract_from_text(f'{corp} | {report}', '', 'DART', rcept_dt)
    if row:
        row['link']=link
        _schedule_append(row)

def _schedule_daily_message():
    today=_now_kst().date()
    end=today+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS)
    rows=[]
    seen=set()
    for r in _schedule_load_rows():
        try: dt=datetime.date.fromisoformat(str(r.get('date',''))[:10])
        except Exception: continue
        if not (today <= dt <= end): continue
        key=(dt.isoformat(),str(r.get('title','')),str(r.get('detail',''))[:120])
        if key in seen: continue
        seen.add(key); rows.append((dt,r))
    rows.sort(key=lambda x:(x[0], str(x[1].get('category',''))))
    rows=rows[:SCHEDULE_MAX_ITEMS]
    lines=['<b>📅 [시장 일정 브리핑]</b>',f'🕐 {_now_kst().strftime("%Y-%m-%d %H:%M")} KST','', '<b>가까운 일정 순</b>']
    if not rows:
        lines.append('• 현재 DB에서 확인된 중요 일정 없음')
        return '\n'.join(lines)
    current=None
    for dt,r in rows:
        if current != dt:
            current=dt
            lines += ['',f'<b>📌 {dt.strftime("%m/%d (%a)")}</b>']
        cat=html.escape(str(r.get('category','뉴스일정')))
        detail=html.escape(str(r.get('detail') or r.get('title',''))[:260])
        tag=html.escape(str(r.get('tag','')))
        companies='·'.join([str(x) for x in (r.get('companies') or [])[:3]])
        suffix=(f' | {html.escape(companies)}' if companies else '')
        lines.append(f'• [{cat}] {detail}{suffix}')
        if r.get('link'):
            lines.append(f'<a href="{html.escape(str(r["link"]),quote=True)}">🔗 원문</a>')
    lines += ['', '※ 특징주·급등 재료와 직접 연결되는 주요 일정 및 고영향 공시만 선별.']
    return '\n'.join(lines)

def _engine_schedule_daily_monitor():
    now=_now_kst()
    slot=None
    if now.hour==7 and now.minute < 2: slot='07'
    elif now.hour==19 and now.minute < 2: slot='19'
    if not slot: return
    state=_schedule_load_json(SCHEDULE_STATE_FILE,{})
    key=f'{now.date().isoformat()}-{slot}'
    if state.get('last_sent')==key: return
    msg=_schedule_daily_message()
    if msg and _engine_send_telegram(msg):
        state['last_sent']=key; state['last_sent_at']=now.isoformat(); _schedule_save_json(SCHEDULE_STATE_FILE,state)
        _engine_log('info','[일정] %s시 일일 일정 브리핑 송출 완료',slot)

ENGINE_HTTP_TIMEOUT = 20
ENGINE_MAX_SEND_PER_CYCLE = 20
ENGINE_STATE_FILE = os.environ.get("NEWS_BOT_STATE_FILE", "news_bot_seen.txt")

# 외부채널(텔레그램/유튜브)은 60분을 기본으로 하며, 시장 마감 후/휴무의 강한 국내 상장기업 재료만 예외 허용한다.

# --- 통합 확장 상태/보안 설정 ---
HISTORICAL_SURGE_DB = os.environ.get("NEWS_BOT_HISTORICAL_DB", "news_bot_historical_surge.jsonl")
GLOBAL_BRIEFING_DB = os.environ.get("NEWS_BOT_GLOBAL_BRIEFING_DB", "news_bot_global_briefing.jsonl")
TELEGRAM_SPAM_STATE = os.environ.get("NEWS_BOT_TELEGRAM_SPAM_STATE", "news_bot_telegram_spam.json")
# [도배 차단] 최근 송출한 기사의 핑거프린트(제목+본문)를 디스크에 남겨, 서버가
# 재시작돼도 "몇 분 전에 이미 보낸 기사"를 다시 신규로 착각해 재전송하지 않게 한다.
SENT_FINGERPRINT_DB = os.environ.get("NEWS_BOT_SENT_FINGERPRINT_DB", "news_bot_sent_fingerprints.jsonl")
# 제목+본문 유사도가 이 값 이상이면 "같은 뉴스"로 보고 도배 차단 대상으로 삼는다.
DUPLICATE_BLOCK_SIMILARITY = float(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_SIMILARITY", "0.80"))
# 이 시간(분)보다 오래된 과거 송출 기록과는 비교하지 않는다(며칠 뒤 동일 사건 재조명 기사는 허용).
DUPLICATE_BLOCK_WINDOW_MIN = int(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_WINDOW_MIN", "720"))
WATCHDOG_TIMEOUT = max(120, int(os.environ.get("NEWS_BOT_WATCHDOG_TIMEOUT", "300")))
WATCHDOG_ALERT_INTERVAL = max(300, int(os.environ.get("NEWS_BOT_WATCHDOG_ALERT_INTERVAL", "900")))
TELEGRAM_MAX_PER_SOURCE_HOUR = max(1, int(os.environ.get("NEWS_BOT_TELEGRAM_MAX_PER_SOURCE_HOUR", "6")))
HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))
ENABLE_GLOBAL_BRIEFING_DB = _env_flag("ENABLE_GLOBAL_BRIEFING_DB")
ENABLE_HISTORICAL_SURGE_DB = _env_flag("ENABLE_HISTORICAL_SURGE_DB")

# [성과 피드백 루프 1단계] 실제로 알림을 보낸 뉴스의 "관련주 판정 근거"를 별도 DB에 기록한다.
# 이 시점에는 아직 주가 반응을 모른다(checked=False) - 2단계(추후 시세 재조회)에서
# 이 DB를 읽어 실제 등락률을 채워 넣고, 3단계(집계)에서 키워드/재료별 적중률을 계산하는 데 쓴다.
# 지금은 "기록만" 한다 - 판정 로직/발송 로직에는 전혀 영향을 주지 않는 순수 부가 기능이다.
OUTCOME_TRACKING_DB = os.environ.get("NEWS_BOT_OUTCOME_TRACKING_DB", "news_bot_outcome_tracking.jsonl")
ENABLE_OUTCOME_TRACKING = _env_flag("ENABLE_OUTCOME_TRACKING", True)
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

_engine_last_cycle_started = 0.0
_engine_last_cycle_finished = 0.0
_engine_last_watchdog_alert = 0.0
_engine_telegram_counts = {}
_engine_historical_cache = []
# [중복적재 방지] 실시간 송출 성공 여부와 무관하게 과거DB(HISTORICAL_SURGE_DB)에
# 무조건 누적 기록하게 되면서, 같은 기사가 매 폴링 주기(RSS 재수집/네이버 재검색)마다
# 반복 적재되는 것을 막기 위한 별도 키 셋. 실시간 송출 dedupe(_engine_seen)와는
# 완전히 분리되어 있어 실시간 송출 로직에는 영향을 주지 않는다.
_engine_historical_recorded_keys = set()
_engine_historical_recorded_lock = threading.Lock()
_engine_global_briefing_cache = []
MARKET_IMPACT_KEYWORDS = {
    "인수", "합병", "M&A", "m&a", "세계최초", "세계 최대", "세계최대", "사상 최대", "사상최대",
    "대규모 수주", "수주", "공급계약", "계약", "독점", "FDA", "승인", "허가", "특허",
    "흑자전환", "어닝서프라이즈", "실적 급증", "대규모 투자", "증설", "양산", "상용화",
    "신규 수주", "수출", "기술수출", "기술이전", "자사주", "배당", "매각", "공개매수",
    "신약", "임상 3상", "임상3상", "임상 성공", "대형 계약", "초대형 계약", "공급 확대",
    # 정책·규제·테마 중 실제 주가 반응으로 이어질 가능성이 높은 재료
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    # 특징주/실시간 주가 재료: 실제 종목 움직임을 포착하기 위한 가격·목표가 신호
    "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
    "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
    "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
    "수혜", "수혜주", "관련주", "테마주", "모멘텀", "호재", "악재",
}
# 실제 주가 반응 가능성이 높은 강한 재료.
# 상장기업이 직접 연결되고 아래 재료가 있으면 시간 제한 없이 시장 반영 여부를 기준으로 검토한다.
STRONG_MARKET_HITS = {
    "인수", "합병", "M&A", "m&a", "공급계약", "계약 체결", "계약",
    "대규모 수주", "수주", "신규 수주", "대형 계약", "초대형 계약",
    "독점", "FDA", "승인", "허가", "특허", "기술수출", "기술이전",
    "임상 3상", "임상3상", "임상 성공", "대규모 투자", "증설", "양산",
    "상용화", "공급 확대", "매각", "공개매수", "자사주", "배당",
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가",
    "목표가 상향", "목표가 하향", "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각", "수혜", "수혜주",
}
BREAKING_WORDS = {"속보"}
FEATURE_WORDS = {"특징주"}
EXCLUSIVE_WORDS = {"단독"}

_engine_seen = set()
_engine_lock = threading.Lock()

# --- 관리자 최우선 명령 통제소 전역 상태 ---
_admin_lock = threading.Lock()
_admin_last_update_id = 0
_admin_pending_command = None      # 아직 실행되지 않은 '가장 최신' 명령만 보관 (덮어쓰기 방식)
_admin_command_event = threading.Event()   # 새 명령 도착 시 실행 스레드를 즉시 깨움
_engine_wake_event = threading.Event()     # 메인 루프의 대기(sleep)를 즉시 깨움
_engine_cycle_lock = threading.Lock()      # /run 즉시실행과 정규 사이클이 동시에 돌지 않도록 보호
_engine_paused = False


def _engine_log(level, message, *args):
    try:
        if level == "error":
            _logger.error(message, *args)
        elif level == "warning":
            _logger.warning(message, *args)
        elif level == "debug":
            pass  # 상세 성공 로그 숨김
        else:
            _logger.info(message, *args)
    except Exception:
        print(message % args if args else message, flush=True)


def _engine_atomic_append_jsonl(path, obj):
    """상태/브리핑 DB를 한 줄 JSON으로 안전하게 추가한다. 민감정보는 기록하지 않는다."""
    try:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        return True
    except Exception as e:
        log_error("JSONL 상태 저장", e, file=path)
        return False


def _engine_atomic_rewrite_jsonl(path, rows):
    """JSONL 파일 전체를 다시 쓴다(append 전용 DB와 달리, 값을 갱신해야 하는
    성과 피드백 DB처럼 '기존 줄의 내용을 수정'해야 하는 경우에만 사용한다).
    임시파일에 먼저 쓰고 os.replace로 교체해 중간에 프로세스가 죽어도 원본이
    깨지지 않게 한다."""
    try:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return True
    except Exception as e:
        log_error("JSONL 전체 재작성", e, file=path)
        return False


def _engine_is_global_market_news(text):
    """국내 관련주가 없어도 보존해야 하는 글로벌 시황 재료."""
    low = _engine_clean(text).lower()
    macro = [
        "fomc", "fed", "powell", "cpi", "pce", "nonfarm", "payroll", "unemployment",
        "treasury", "yield", "bond yield", "tariff", "sanction", "ceasefire", "war",
        "oil", "wti", "brent", "gold", "copper", "dollar", "usd", "nasdaq", "s&p 500",
        "dow", "semiconductor index", "phlx", "호르무즈", "전쟁", "휴전", "관세", "제재",
        "연준", "금리", "국채", "환율", "유가", "뉴욕증시", "필라델피아반도체지수",
    ]
    movement = list(US_FEATURE_STOCK_WORDS) + ["급등", "급락", "폭등", "폭락", "신고가", "신저가"]
    return any(k in low for k in macro) and any(k in low for k in movement + ["발표", "결정", "회의", "인상", "인하", "확산", "충돌", "협상"])


def _engine_confidence_state(item):
    """미확인/확인/업그레이드 구분. 소문·전망은 확인 전 상태로 표시한다."""
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    rumor = ["가능성", "전망", "관측", "추정", "검토", "추진설", "인수설", "협상중", "논의중", "rumor", "reportedly", "could", "may"]
    confirmed = ["확정", "공식", "체결", "발표", "승인", "허가", "수주", "공급계약", "실적", "공시", "confirmed", "official", "approved"]
    rumor_hit = any(k in text for k in rumor) or bool(re.search(r"(?:^|\s)(?:설|루머)(?:$|\s)", text))
    if rumor_hit and not any(k in text for k in confirmed):
        return "미확인"
    return "확인"


def _engine_strong_material(item):
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    strong = set(str(x).lower() for x in STRONG_MARKET_HITS | MONEY_STRONG_WORDS)
    strong |= {"계약 체결", "공급계약", "대규모 수주", "수주 확정", "사상 최대", "세계 최대", "독점", "승인", "허가", "인수 확정", "대규모 투자"}
    amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|억원|조원|달러|usd|million|billion))", text, re.I))
    hits = [x for x in strong if x in text]
    return bool(hits or amount or len(item.get("market_hits", [])) >= 2), hits[:5]


def _engine_historical_match(item):
    if not ENABLE_HISTORICAL_SURGE_DB or not _engine_historical_cache:
        return None
    current = item.get("title", "") + " " + item.get("extra", "")
    best = None
    for row in _engine_historical_cache[-3000:]:
        old = str(row.get("text", ""))
        if not old:
            continue
        ratio = difflib.SequenceMatcher(None,
            re.sub(r"[^0-9a-zA-Z가-힣]", "", current.lower())[:260],
            re.sub(r"[^0-9a-zA-Z가-힣]", "", old.lower())[:260]).ratio()
        if ratio >= HISTORICAL_MATCH_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, row)
    return best


def _engine_load_extended_state():
    global _engine_historical_cache, _engine_global_briefing_cache, _engine_telegram_counts
    global _engine_sent_fingerprints
    if ENABLE_HISTORICAL_SURGE_DB and os.path.exists(HISTORICAL_SURGE_DB):
        try:
            with open(HISTORICAL_SURGE_DB, "r", encoding="utf-8") as f:
                _engine_historical_cache = [json.loads(x) for x in f if x.strip()][-5000:]
            # [중복적재 방지] 실시간 송출 여부와 무관하게 과거DB에 기록하도록 바뀌면서
            # 같은 기사(RSS 재폴링/재검색)가 매 주기 반복 적재되지 않도록, 서버 재시작 후에도
            # 이미 적재된 기사의 dedupe key(link 우선, 없으면 title)를 복원해 둔다.
            for _row in _engine_historical_cache:
                _k = str(_row.get("link") or "").strip() or str(_row.get("title") or "").strip()
                if _k:
                    _engine_historical_recorded_keys.add(_k)
        except Exception as e:
            log_error("과거 급등 DB 읽기", e, file=HISTORICAL_SURGE_DB)
    if ENABLE_GLOBAL_BRIEFING_DB and os.path.exists(GLOBAL_BRIEFING_DB):
        try:
            with open(GLOBAL_BRIEFING_DB, "r", encoding="utf-8") as f:
                _engine_global_briefing_cache = [json.loads(x) for x in f if x.strip()][-5000:]
        except Exception as e:
            log_error("글로벌 브리핑 DB 읽기", e, file=GLOBAL_BRIEFING_DB)
    if os.path.exists(TELEGRAM_SPAM_STATE):
        try:
            with open(TELEGRAM_SPAM_STATE, "r", encoding="utf-8") as f:
                _engine_telegram_counts = json.load(f) or {}
        except Exception:
            _engine_telegram_counts = {}
    # [도배 차단] 서버 재시작 후에도 "방금 보낸 기사" 기록을 이어받는다.
    if os.path.exists(SENT_FINGERPRINT_DB):
        try:
            with open(SENT_FINGERPRINT_DB, "r", encoding="utf-8") as f:
                _engine_sent_fingerprints = [json.loads(x) for x in f if x.strip()][-3000:]
            _engine_log("info", "[상태] 최근 송출 핑거프린트=%d건 복원", len(_engine_sent_fingerprints))
        except Exception as e:
            log_error("송출 핑거프린트 DB 읽기", e, file=SENT_FINGERPRINT_DB)


def _engine_record_global_briefing(item):
    if not ENABLE_GLOBAL_BRIEFING_DB:
        return
    if not (item.get("market_hits") or _engine_is_global_market_news(item.get("title", "") + " " + item.get("extra", ""))):
        return
    row = {
        "ts": _now_kst().isoformat(),
        "source": str(item.get("source", ""))[:80],
        "published": str(item.get("published", ""))[:80],
        "title": str(item.get("title", ""))[:500],
        "link": str(item.get("link", ""))[:1000],
        "companies": _engine_global_companies(item.get("companies", []))[:6],
        "market_hits": item.get("market_hits", [])[:8],
    }
    _engine_atomic_append_jsonl(GLOBAL_BRIEFING_DB, row)


def _engine_record_historical_case(item, force=False):
    """[1원칙: 데이터는 무조건 누적] 강도/조건과 무관하게 카테고리가 확정된 뉴스는
    실시간 텔레그램 송출 성공 여부와 무관하게 전부 누적 DB에 기록한다.
    (기존에는 텔레그램 송출에 성공한 뉴스만 여기로 왔지만, 실시간 송출 시간 게이트
    [최근 60분 등]가 데이터 누적까지 함께 막아 시장비교/과거성과 DB가 비는 문제가
    있었다. 이제 송출 여부와 적재를 분리해, 분류(category)만 확정되면 여기로 온다.)
    '급등/폭등/상한가/신고가' 같은 강한 재료였는지는 is_surge_hit 플래그로만
    구분해서 남기고, 기록 자체를 막지 않는다.
    이 누적 데이터가 이후 모든 뉴스의 관련주/테마 판정, 분석 근거의 기반이 된다.

    [중복적재 방지] 같은 기사(link 또는 title)가 매 폴링 주기마다 반복 적재되지
    않도록 _engine_historical_recorded_keys로 별도 dedupe한다. 실시간 송출용
    dedupe(_engine_seen)와는 분리되어 있으므로 실시간 송출 로직에는 영향이 없다.
    force=True면 dedupe를 건너뛴다(백필 등 이미 기간 단위로 별도 중복제어를 하는 경우).
    """
    if not ENABLE_HISTORICAL_SURGE_DB:
        return False
    dedupe_key = str(item.get("link") or "").strip() or str(item.get("title") or "").strip()
    if not force and dedupe_key:
        with _engine_historical_recorded_lock:
            if dedupe_key in _engine_historical_recorded_keys:
                return False
            _engine_historical_recorded_keys.add(dedupe_key)
    strong, hits = _engine_strong_material(item)
    title = item.get("title", "")
    text_all = _engine_clean(title + " " + item.get("extra", "")).lower()
    is_surge_hit = strong and any(
        x in text_all for x in ["급등", "폭등", "상한가", "신고가", "surge", "soar", "rally"]
    )
    row = {
        "ts": _now_kst().isoformat(), "text": (title + " " + item.get("extra", ""))[:800],
        "title": title[:500], "link": str(item.get("link", ""))[:1000],
        "companies": item.get("companies", [])[:6], "hits": hits,
        "market_state": str(item.get("market_state") or "").strip(),
        "is_surge_hit": is_surge_hit,
        "published": str(item.get("published") or "")[:80],
    }
    if _engine_atomic_append_jsonl(HISTORICAL_SURGE_DB, row):
        _engine_historical_cache.append(row)
        if len(_engine_historical_cache) > 5000:
            del _engine_historical_cache[:-5000]
        return True
    return False


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


def _engine_telegram_spam_allowed(item):
    source = str(item.get("source", ""))
    if not source.startswith("텔레그램/"):
        return True
    now = time.time()
    bucket = _engine_telegram_counts.setdefault(source, [])
    bucket[:] = [x for x in bucket if now - float(x) < 3600]
    if len(bucket) >= TELEGRAM_MAX_PER_SOURCE_HOUR:
        _engine_log("info", "[제외] Telegram 도배방지 | source=%s | 1시간=%d", source, len(bucket))
        return False
    return True


def _engine_telegram_mark_sent(item):
    source = str(item.get("source", ""))
    if source.startswith("텔레그램/"):
        _engine_telegram_counts.setdefault(source, []).append(time.time())
        try:
            with open(TELEGRAM_SPAM_STATE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(_engine_telegram_counts, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(TELEGRAM_SPAM_STATE + ".tmp", TELEGRAM_SPAM_STATE)
        except Exception as e:
            log_error("Telegram 도배상태 저장", e, file=TELEGRAM_SPAM_STATE)


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


def _engine_load_seen():
    global _engine_seen
    try:
        if os.path.exists(ENGINE_STATE_FILE):
            with open(ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
                _engine_seen = {x.strip() for x in f if x.strip()}
        _engine_log("info", "[상태] 이미 처리한 기사=%d건", len(_engine_seen))
    except Exception as e:
        log_error("상태파일 읽기", e, file=ENGINE_STATE_FILE)


def _engine_mark_seen(key):
    global _engine_seen
    if not key:
        return False
    with _engine_lock:
        if key in _engine_seen:
            return False
        _engine_seen.add(key)
        # 메모리 폭주 방지
        if len(_engine_seen) > 20000:
            _engine_seen = set(list(_engine_seen)[-15000:])
        try:
            with open(ENGINE_STATE_FILE, "a", encoding="utf-8") as f:
                f.write(key + "\n")
        except Exception as e:
            log_error("상태파일 저장", e, file=ENGINE_STATE_FILE)
        return True


def _engine_clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(str(text or ""), "html.parser").get_text(" ")).strip()


def _engine_item_key(title, link):
    return difflib.SequenceMatcher(None, title[:200].lower(), link[:200].lower()).ratio() and (link or title[:200])


def _engine_send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        _engine_log("error", "[실패] Telegram | BOT_TOKEN/CHAT_ID 없음")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=ENGINE_HTTP_TIMEOUT)
        api_result = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if r.ok and api_result.get("ok", True):
            _engine_log("info", "[성공] Telegram 전송")
            return True
        _engine_log("error", "[실패] Telegram 전송 | 원인=%s", api_result.get("description") or r.reason)
    except Exception as e:
        _engine_log("error", "[실패] Telegram 전송 | 원인=%s", str(e)[:160])
    return False


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
    state = "⏸ 일시정지" if _engine_paused else "▶️ 정상 가동"
    last = _now_kst().strftime("%Y-%m-%d %H:%M:%S") if _engine_last_cycle_finished else "없음"
    return f"🟢 [통제소] 엔진 상태: {state}\n최근 주기 완료 시각: {last}"


def _admin_cmd_pause(arg=""):
    global _engine_paused
    _engine_paused = True
    return "⏸ [통제소] 뉴스 수집·송출을 일시정지했습니다."


def _admin_cmd_resume(arg=""):
    global _engine_paused
    _engine_paused = False
    _engine_wake_event.set()
    return "▶️ [통제소] 뉴스 수집·송출을 재개했습니다."


def _admin_cmd_run(arg=""):
    """정규 주기(최대 60초)를 기다리지 않고 지금 즉시 한 사이클을 강제 실행한다."""
    def _worker():
        with _engine_cycle_lock:
            _engine_log("info", "[관리자 명령] /run 즉시 사이클 실행 시작")
            was_paused = _engine_paused
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
              "/성과리포트 : 송출된 뉴스의 실제 등락률 집계(키워드별 적중률)",
              "/백필 [일수] : DART 과거 공시를 소급해 과거DB에 적재(기본 365일)",
              "/help : 이 목록 표시"]
    return "\n".join(lines)


def _admin_cmd_outcome_report(arg=""):
    try:
        min_samples = int(arg.strip()) if arg.strip() else 3
    except ValueError:
        min_samples = 3
    return _outcome_aggregate_report(min_samples=min_samples)


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
    "/성과리포트": _admin_cmd_outcome_report,
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


def _engine_parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            dt = parsedate_to_datetime(s)
        except Exception:
            dt = None
        if dt is None:
            for candidate in (s, s.replace("Z", "+00:00")):
                try:
                    dt = datetime.datetime.fromisoformat(candidate)
                    break
                except Exception:
                    pass
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_KST).replace(tzinfo=None)
    return dt


KRX_WEEKDAY_OPEN = datetime.time(9, 0)
KRX_WEEKDAY_CLOSE = datetime.time(15, 30)
# 2026년 주요 KRX 휴장일. 주말은 별도 자동 처리한다.
KRX_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
    "2026-05-05", "2026-05-25", "2026-06-06", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25",
}
US_OPEN = datetime.time(9, 30)
US_CLOSE = datetime.time(16, 0)

# ============================================================
# [테스트 모드 / 조건56 테스트분리] 실시간 뉴스가 없는 시간대(장 마감/새벽/휴일 등)에도
# 파이프라인 전체(수집→MASTER→포맷터→텔레그램)를 눈으로 검증할 수 있도록,
# 아래 시간 필터들을 환경변수로만 완화한다. 기본값은 OFF(운영 동작 그대로)이며,
# 코드상 어떤 값도 하드코딩으로 바꾸지 않는다 — 검증이 끝나면 환경변수만 지우면
# 즉시 원래 동작(최근 60분)으로 복귀한다.
# ============================================================
NEWS_BOT_TEST_MODE = _env_flag("NEWS_BOT_TEST_MODE", False)
NEWS_BOT_TEST_WINDOW_MIN = int(os.environ.get("NEWS_BOT_TEST_WINDOW_MIN", "10080"))  # 기본 7일치까지 허용
if NEWS_BOT_TEST_MODE:
    _logger.warning(
        "[테스트 모드] 시간 필터 완화 ON | 최근 %d분(%.1f일) 이내 뉴스까지 통과 | "
        "검증이 끝나면 NEWS_BOT_TEST_MODE를 반드시 끌 것(광고성/오래된 뉴스가 실제 채널로 도배될 수 있음)",
        NEWS_BOT_TEST_WINDOW_MIN, NEWS_BOT_TEST_WINDOW_MIN / 1440,
    )


def _engine_market_state(source, published):
    dt = _engine_parse_datetime(published)
    if dt is None:
        return "시장시간 확인불가"
    if source == "Google-US" and ZoneInfo is not None:
        aware = dt.replace(tzinfo=_KST).astimezone(ZoneInfo("America/New_York"))
        d, tm = aware.date(), aware.time()
        if d.weekday() >= 5:
            return "시장 휴무로 미반영"
        if US_OPEN <= tm <= US_CLOSE:
            return "장중"
        return "시장 마감 후 뉴스"
    date_key = dt.strftime("%Y-%m-%d")
    if dt.weekday() >= 5 or date_key in KRX_HOLIDAYS_2026:
        return "시장 휴무로 미반영"
    if KRX_WEEKDAY_OPEN <= dt.time() <= KRX_WEEKDAY_CLOSE:
        return "장중"
    return "시장 마감 후 뉴스"


def _engine_recent_enough(published, source=""):
    """외부 콘텐츠(텔레그램/유튜브)는 최근 60분을 기본으로 한다.
    단, 국내 장 마감 후/휴무에 발생한 강한 주가 재료는 다음 거래일 반영을 위해 예외 허용한다.
    국내 RSS/NAVER/DART/미국뉴스는 이 함수로 노출을 제한하지 않는다.
    """
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True
    return False


def _engine_external_time_gate(source, published, title, extra, market_state, market_hits):
    """텔레그램/유튜브 도배 방지용 시간 관문.
    60분 초과는 원칙적으로 차단하고, 장 마감 후/휴무의 강한 재료만 예외로 통과시킨다.
    """
    if NEWS_BOT_TEST_MODE:
        return True, "테스트모드(시간필터 완화)"
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True, ""
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False, "발행시간 확인불가"
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True, "최근60분"
    text = _engine_clean(f"{title} {extra}")
    text_l = text.lower()

    # 60분 예외는 절대로 "강한 단어" 하나만으로 열지 않는다.
    # 시장 마감 후/휴무일에 다음 거래일 주가 반영 가능성이 있는
    # "국내 상장기업 + 실제 사건 + 강한 재료"가 모두 확인될 때만 허용한다.
    domestic_companies = {
        "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
        "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
        "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
        "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
        "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
        "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
        "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    }
    domestic_hit = any(c.lower() in text_l for c in domestic_companies)

    # 실제 사건형 재료만 인정. 전망/분석/관심/지원 등의 약한 표현은 예외를 열지 않는다.
    strong_hits = [k for k in STRONG_MARKET_HITS if k.lower() in text_l]
    strong = bool(strong_hits)

    if market_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영") and domestic_hit and strong:
        return True, f"{market_state} | 국내상장기업+강한재료"

    return False, "60분 초과"


AMBIGUOUS_COMPANY_TERMS = {
    "삼성", "SK", "LG", "현대", "한화", "포스코", "두산", "LS", "우리", "하나", "KB",
    "신한", "KT", "CJ", "GS", "DL", "DB", "농협", "롯데", "신세계", "네이버", "카카오",
}
LISTED_COMPANY_ALIASES = {
    "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
    "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
    "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
    "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
    "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
    "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
    "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    # [수정] 그룹 지주사/모회사 자체도 실제 코스피 상장사인데 빠져 있었다.
    # (예: "한화 건설부문" 뉴스가 계열사명이 아니라 "한화" 자체로만 언급되는 경우)
    "한화", "삼성물산", "포스코홀딩스", "두산", "GS건설", "DL이앤씨", "현대건설",
    "롯데케미칼", "CJ제일제당", "카카오뱅크", "네이버", "LG",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타", "AMD",
    "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "팔란티어", "브로드컴", "퀄컴",
}

# ============================================================
# [성과 피드백 루프 2단계 - 종목코드 매핑] DART corpCode.xml 기반
# ------------------------------------------------------------
# LISTED_COMPANY_ALIASES는 "이름만" 있고 종목코드가 없어서, 사후 시세 조회를
# 하려면 이름→코드 매핑이 필요하다. DART가 제공하는 corpCode.xml(전체 상장/비상장
# 법인 목록, zip 압축)을 내려받아 종목코드가 있는(=상장된) 법인만 추려서 캐시한다.
# - 하루 수십~수백 건 조회에 매번 네트워크를 타지 않도록 디스크에 캐시하고,
#   일정 기간(기본 7일)이 지나야 다시 내려받는다.
# - 실패해도(키 없음/네트워크 오류) 조용히 빈 매핑으로 계속 동작한다(기존 기능에
#   영향을 주지 않기 위함 - 종목코드가 없으면 해당 항목의 사후 시세 조회만 건너뜀).
# ============================================================
DART_CORP_CODE_CACHE = os.environ.get("NEWS_BOT_DART_CORP_CODE_CACHE", "dart_corp_code_map.json")
DART_CORP_CODE_CACHE_DAYS = max(1, int(os.environ.get("NEWS_BOT_DART_CORP_CODE_CACHE_DAYS", "7")))

_DART_CORP_CODE_MAP = {}          # {법인명: 종목코드(6자리)}
_DART_CORP_CODE_LOADED = False    # 이번 프로세스에서 로드를 시도했는지(성공/실패 무관)


def _dart_download_corp_code_map():
    """DART corpCode.xml을 내려받아 종목코드가 있는 법인만 {이름: 코드}로 반환한다.
    실패 시 빈 dict를 반환한다(예외를 던지지 않음 - 호출부가 항상 안전하게 처리)."""
    if not DART_API_KEY:
        _engine_log("warning", "[DART corpCode] DART_API_KEY 없음 - 종목코드 매핑 건너뜀")
        return {}
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": DART_API_KEY},
            timeout=30,
        )
        if not r.ok:
            _engine_log("warning", "[DART corpCode] 다운로드 실패 | status=%s", r.status_code)
            return {}
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")
        root = ET.fromstring(xml_bytes)
        mapping = {}
        for node in root.iter("list"):
            name = (node.findtext("corp_name") or "").strip()
            code = (node.findtext("stock_code") or "").strip()
            if name and code and code.isdigit() and len(code) == 6:
                # 동일 이름이 여러 번 나오면 먼저 나온 것을 유지한다(개명/재상장 등 예외 케이스).
                mapping.setdefault(name, code)
        _engine_log("info", "[DART corpCode] 종목코드 매핑 구축 완료 | 상장법인=%d건", len(mapping))
        return mapping
    except Exception as e:
        _engine_log("warning", "[DART corpCode] 처리 실패 | 원인=%s", str(e)[:160])
        return {}


def _dart_load_corp_code_map(force=False):
    """디스크 캐시가 신선하면 그대로 쓰고, 오래됐거나 없으면 새로 받아 캐시한다."""
    global _DART_CORP_CODE_MAP, _DART_CORP_CODE_LOADED
    if _DART_CORP_CODE_LOADED and not force:
        return _DART_CORP_CODE_MAP
    _DART_CORP_CODE_LOADED = True
    try:
        if os.path.exists(DART_CORP_CODE_CACHE) and not force:
            age_days = (time.time() - os.path.getmtime(DART_CORP_CODE_CACHE)) / 86400.0
            if age_days < DART_CORP_CODE_CACHE_DAYS:
                with open(DART_CORP_CODE_CACHE, "r", encoding="utf-8") as f:
                    _DART_CORP_CODE_MAP = json.load(f) or {}
                _engine_log("info", "[DART corpCode] 캐시 로드 완료 | %d건 | %.1f일 경과",
                            len(_DART_CORP_CODE_MAP), age_days)
                return _DART_CORP_CODE_MAP
    except Exception as e:
        _engine_log("warning", "[DART corpCode] 캐시 로드 실패 | 원인=%s", str(e)[:160])

    mapping = _dart_download_corp_code_map()
    if mapping:
        _DART_CORP_CODE_MAP = mapping
        try:
            with open(DART_CORP_CODE_CACHE, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False)
        except Exception as e:
            _engine_log("warning", "[DART corpCode] 캐시 저장 실패 | 원인=%s", str(e)[:160])
    elif os.path.exists(DART_CORP_CODE_CACHE):
        # 이번 다운로드는 실패했지만 예전 캐시가 있으면(만료됐어도) 없는 것보다는 낫다.
        try:
            with open(DART_CORP_CODE_CACHE, "r", encoding="utf-8") as f:
                _DART_CORP_CODE_MAP = json.load(f) or {}
            _engine_log("warning", "[DART corpCode] 새 다운로드 실패 - 만료된 캐시로 계속 사용 | %d건",
                        len(_DART_CORP_CODE_MAP))
        except Exception:
            _DART_CORP_CODE_MAP = {}
    return _DART_CORP_CODE_MAP


def _dart_stock_code_for_name(name):
    """종목명으로 6자리 종목코드를 찾는다. 못 찾으면 빈 문자열을 반환한다(예외 없음)."""
    name = str(name or "").strip()
    if not name:
        return ""
    mapping = _dart_load_corp_code_map()
    if not mapping:
        return ""
    if name in mapping:
        return mapping[name]
    # DART 정식 법인명과 뉴스에서 쓰는 약칭이 다를 수 있어(예: "현대차" vs "현대자동차")
    # 흔한 접두/접미 변형 한두 가지만 보조로 시도한다. 억지 유사매칭은 하지 않는다(오탐 방지).
    for suffix in ("보통주", "우선주"):
        if name.endswith(suffix) and name[:-len(suffix)].strip() in mapping:
            return mapping[name[:-len(suffix)].strip()]
    return ""


# ------------------------------------------------------------
# [성과 피드백 루프 2단계 - 네이버 보완 조회] DART corpCode에 없는 이름(약칭·최근
# 상장·표기 차이 등)을 위한 폴백. finance.naver.com 종목검색은 별도 인증이 필요
# 없다. 매 조회마다 네트워크를 타지 않도록 결과(성공/실패 모두)를 디스크에 캐시하고,
# 일정 기간이 지나야 재시도한다(재상장/이름변경 등을 반영할 여지를 남김).
# ------------------------------------------------------------
NAVER_STOCK_CODE_CACHE = os.environ.get("NEWS_BOT_NAVER_STOCK_CODE_CACHE", "naver_stock_code_cache.json")
NAVER_STOCK_CODE_CACHE_DAYS = max(1, int(os.environ.get("NEWS_BOT_NAVER_STOCK_CODE_CACHE_DAYS", "30")))

_NAVER_STOCK_CODE_CACHE = {}       # {이름: {"code": "005930" 또는 "", "ts": epoch초}}
_NAVER_STOCK_CODE_CACHE_LOADED = False


def _naver_load_stock_code_cache():
    global _NAVER_STOCK_CODE_CACHE, _NAVER_STOCK_CODE_CACHE_LOADED
    if _NAVER_STOCK_CODE_CACHE_LOADED:
        return
    _NAVER_STOCK_CODE_CACHE_LOADED = True
    if os.path.exists(NAVER_STOCK_CODE_CACHE):
        try:
            with open(NAVER_STOCK_CODE_CACHE, "r", encoding="utf-8") as f:
                _NAVER_STOCK_CODE_CACHE = json.load(f) or {}
        except Exception as e:
            _engine_log("warning", "[네이버 종목코드] 캐시 로드 실패 | 원인=%s", str(e)[:160])
            _NAVER_STOCK_CODE_CACHE = {}


def _naver_save_stock_code_cache():
    try:
        with open(NAVER_STOCK_CODE_CACHE, "w", encoding="utf-8") as f:
            json.dump(_NAVER_STOCK_CODE_CACHE, f, ensure_ascii=False)
    except Exception as e:
        _engine_log("warning", "[네이버 종목코드] 캐시 저장 실패 | 원인=%s", str(e)[:160])


def _naver_search_stock_code(name):
    """finance.naver.com 종목검색 결과에서 이름과 정확히 일치하는 첫 항목의 코드를 찾는다.
    부분일치/유사매칭은 하지 않는다(엉뚱한 종목코드를 기록하는 것이 아예 없는 것보다 위험).
    실패해도 예외를 던지지 않고 빈 문자열을 반환한다."""
    try:
        r = requests.get(
            "https://finance.naver.com/search/searchList.naver",
            params={"query": name},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if not r.ok:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("table.tbl_search a[href*='/item/main.naver']"):
            row_text = _engine_clean(a.find_parent("tr").get_text(" ")) if a.find_parent("tr") else ""
            link_name = _engine_clean(a.get_text(" "))
            if link_name != name and name not in row_text.split():
                continue
            m = re.search(r"code=(\d{6})", a.get("href", ""))
            if m:
                return m.group(1)
        return ""
    except Exception as e:
        _engine_log("warning", "[네이버 종목코드] 검색 실패 | %s | 원인=%s", name, str(e)[:120])
        return ""


def _resolve_stock_code_for_name(name):
    """DART corpCode → (없으면) 네이버 종목검색 순으로 조회한다.
    두 경로 모두 실패하면 조용히 빈 문자열을 반환한다(사후 시세 조회만 건너뜀)."""
    name = str(name or "").strip()
    if not name:
        return ""
    code = _dart_stock_code_for_name(name)
    if code:
        return code
    _naver_load_stock_code_cache()
    cached = _NAVER_STOCK_CODE_CACHE.get(name)
    if cached and (time.time() - float(cached.get("ts", 0))) < NAVER_STOCK_CODE_CACHE_DAYS * 86400:
        return cached.get("code", "")
    code = _naver_search_stock_code(name)
    _NAVER_STOCK_CODE_CACHE[name] = {"code": code, "ts": time.time()}
    _naver_save_stock_code_cache()
    return code


def _engine_company_mentions(text):
    """기업명을 '발견'하는 것과 관심종목으로 '인정'하는 것을 분리한다.
    URL/출처/인용/광고 문구에 우연히 등장한 기업명은 후보에서 제외할 수 있도록
    회사명 주변 문맥을 함께 반환한다.
    """
    t = _engine_clean(text)
    low = t.lower()
    found = []
    candidates = (set(LISTED_COMPANY_ALIASES) | set(GLOBAL_COMPANY_KEYWORDS)) - set(UNIQUE_CELEBS)

    # 네이버/다음 등 링크 도메인이나 출처 표기에 포함된 회사명은 회사 사건으로 인정하지 않는다.
    context_bad = [
        "n.news.naver.com", "news.naver.com", "naver.com", "blog.naver.com",
        "youtube.com", "youtu.be", "t.me/", "telegram", "원문", "출처",
        "광고", "협찬", "캠페인", "제공", "에 따르면", "관계자는", "인용",
    ]
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시",
        "상용화", "승인", "허가", "특허", "임상", "기술이전", "기술수출",
        "로열티", "마일스톤", "제품", "생산", "수출", "수입", "판매", "공급계약",
        "수혜", "피해", "주가", "주식", "지분율", "보유", "취득", "신규 공시",
        # [수정] 건설/정비사업 관련 뉴스(예: "한화 건설부문, 도시정비사업 공략")가
        # 위 목록에 없는 표현이라 회사 후보로 아예 잡히지 않던 문제를 보완.
        "정비사업", "도시정비", "재건축", "재개발", "컨소시엄", "시공권",
        "수주전", "일감", "분양", "착공", "준공",
    ]

    # (000000) 형태의 종목코드 바로 앞 회사명은 강한 직접기업 신호로 사용한다.
    # 정적 관심종목 목록에 없는 종목도 코드가 붙으면 국내 상장사 후보로 인정한다.
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in found and len(name) >= 2:
            found.append(name)

    for x in sorted(candidates, key=len, reverse=True):
        if not x or x in found or x.lower() not in low:
            continue
        for m in re.finditer(re.escape(x), t, re.I):
            a, b = max(0, m.start()-110), min(len(t), m.end()+110)
            ctx = t[a:b]
            ctx_low = ctx.lower()
            # URL/출처 안에만 있으면 제외
            if any(bad.lower() in ctx_low for bad in context_bad):
                # 같은 회사명이 본문에 또 있으면 아래 반복에서 다시 검토
                continue
            if any(w.lower() in ctx_low for w in event_words):
                found.append(x)
                break
    return found[:12]


def _engine_find_companies(text):
    """기업명 추출은 후보 탐색용이며, 관심종목 선정은 별도 문맥 검증을 거친다."""
    return _engine_company_mentions(text)


def _engine_company_direct_context(text, company):
    t = _engine_clean(text)
    contexts = []
    for m in re.finditer(re.escape(company), t, re.I):
        contexts.append(t[max(0,m.start()-150):min(len(t),m.end()+150)])
    return contexts


def _engine_company_is_directly_related(text, company):
    """기업명이 실제 사건 당사자인지 확인한다. 단순 언급/출처/인용은 불인정."""
    contexts = _engine_company_direct_context(text, company)
    if not contexts:
        return False
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시", "상용화",
        "승인", "허가", "특허", "임상", "기술이전", "기술수출", "로열티", "마일스톤",
        "생산", "수출", "판매", "제품", "주가", "지분율", "보유", "취득", "공시",
        "수혜", "피해", "사업", "개발", "공급계약", "상업화",
    ]
    bad_words = [
        "에 따르면", "관계자는", "광고", "협찬", "캠페인", "브랜드", "출처",
        "원문", "기자", "비교", "예시", "검색", "뉴스 링크", "https://", "http://",
    ]
    for ctx in contexts:
        low = ctx.lower()
        if any(b.lower() in low for b in bad_words) and not any(e.lower() in low for e in event_words):
            continue
        if any(e.lower() in low for e in event_words):
            return True
    return False


def _engine_has_keyword_pair(text):
    t = _engine_clean(text).lower()
    k1 = [x for x in UNIQUE_KEYWORDS_1 if x and x.lower() in t]
    k2 = [x for x in UNIQUE_KEYWORDS_2 if x and x.lower() in t]
    return k1, k2


def _engine_market_hit(text):
    t = _engine_clean(text).lower()
    return [x for x in MARKET_IMPACT_KEYWORDS if x.lower() in t]


def _engine_is_lagging_interpretive_news(text):
    """이미 벌어진 주가 움직임을 사후적으로 설명·평가하는 후행적/해석성 뉴스 차단.
    예: '~이후 주가가 안정되었다', '~만큼 가치가 있다', '~돌파한 후' 등은
    새로운 시세 재료가 아니라 지나간 결과에 대한 해설이므로 실시간 송출 대상에서 제외한다.
    단, 계약/실적/승인 등 실제 강한 재료가 함께 있으면 통과시킨다(오버라이드)."""
    low = _engine_clean(text).lower()
    # 순수 사후 해설/평가성 표현: 강한 재료 단어가 같이 있어도(과거 계약 언급 등)
    # 제목 자체가 결과에 대한 해석일 뿐이므로 오버라이드 없이 무조건 차단한다.
    hard_lagging_patterns = [
        "안정되었습니다", "안정세", "안정적으로", "안정을 되찾",
        "만큼 가치가 있", "가치가 있다는", "가치 있다는",
        "돌파한 후", "돌파하며", "돌파한 이후",
        "소매 신뢰도", "투자자 심리", "투심 개선", "투심 회복",
    ]
    # 상승/회복 흐름 서술: 실제 새 재료(계약/실적/승인 등)와 함께 나오면 통과시킨다.
    soft_lagging_patterns = [
        "회복세를 보이", "회복하고 있", "반등하고 있",
        "상승세를 이어가", "상승세를 보이", "하락세를 보이",
    ]
    strong_override = [
        "계약", "공급", "수주", "실적", "어닝", "승인", "허가",
        "인수", "합병", "특허", "목표가", "공개매수", "임상",
        "신제품", "출시", "증설", "제재", "규제", "소송",
    ]
    if any(x in low for x in hard_lagging_patterns):
        return True
    return any(x in low for x in soft_lagging_patterns) and not any(x in low for x in strong_override)


def _engine_is_weak_nonstock_news(text):
    """주가와 직접 연결되지 않는 사회공헌/캠페인/일반 홍보성 뉴스 차단."""
    low = _engine_clean(text).lower()
    weak = [
        "사회공헌", "캠페인", "인신매매 근절", "기부", "후원", "봉사",
        "공익", "홍보대사", "브랜드 캠페인", "csr", "esg 활동",
    ]
    strong_business = [
        "수주", "계약", "공급", "투자", "증설", "양산", "실적",
        "기술이전", "기술수출", "인수", "합병", "승인", "허가",
        "특허", "지분", "배당", "자사주", "정책 확정", "법안 통과",
        "관세 부과", "세액공제 확정", "상용화", "매출",
    ]
    return any(x in low for x in weak) and not any(x in low for x in strong_business)


def _engine_domestic_companies(companies, text=""):
    """글로벌 기업을 국내 상장기업으로 오인하지 않도록 국내 종목만 반환.
    종목코드(6자리)가 붙은 회사명은 정적 목록에 없어도 국내 상장사 후보로 인정한다."""
    text = _engine_clean(text)
    out = []
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS:
            continue
        code_bearing = bool(re.search(rf"{re.escape(str(c))}\s*\((?:KRX:)?\d{{6}}\)", text, re.I)) if text else False
        if c in LISTED_COMPANY_ALIASES or code_bearing:
            if c not in out:
                out.append(c)
    return out


def _engine_global_companies(companies):
    return [c for c in companies if c in GLOBAL_COMPANY_KEYWORDS]


def _engine_classify(source, title, extra=""):
    text = _engine_clean(f"{title} {extra}")
    companies = _engine_find_companies(text)
    domestic = _engine_domestic_companies(companies, text)
    global_companies = _engine_global_companies(companies)
    k1, k2 = _engine_has_keyword_pair(text)
    market_hits = _engine_market_hit(text)
    low = text.lower()
    # [수정] 외신은 _engine_process_item()에서 이미 한국어로 번역된 뒤 넘어오지만,
    # 번역이 일부만 되거나(예: "Breaking: ..."가 그대로 남는 경우) 대비해
    # 영문 속보 표지도 함께 인정한다(BREAKING_WORDS는 원래 한글 전용이라 죽은 코드였음).
    is_breaking = any(x in low for x in BREAKING_WORDS) or any(x in low for x in US_BREAKING_WORDS)
    is_feature = any(x in low for x in FEATURE_WORDS)
    is_exclusive = any(x in low for x in EXCLUSIVE_WORDS)
    is_external = source.startswith("텔레그램/") or source.startswith("유튜브/")

    # 사회공헌/캠페인 등 주가와 무관한 뉴스는 기업명이 있어도 원천 차단.
    if _engine_is_weak_nonstock_news(text):
        return False, "주가재료 미충족", [], k1, k2, []

    # 이미 벌어진 주가 움직임을 사후적으로 설명·평가하는 후행적/해석성 뉴스 차단.
    if _engine_is_lagging_interpretive_news(text):
        return False, "후행적 해석성 뉴스", [], k1, k2, []

    # 관련주 연결은 '국내 상장기업'이 실제로 존재하거나,
    # 국내 테마 연결을 별도 검증한 경우에만 허용한다.
    stock_links = _engine_stock_links(text, domestic)
    stock_linked = bool(domestic) or bool(stock_links)
    # 특징주/속보/단독은 '기업 + 실제 가격/재료 신호'가 있으면 통과시킨다.
    # 기존처럼 계약/FDA 등 강한 재료만 요구하면 목표가 상향, 어닝서프라이즈, 공개매수,
    # 급등/급락 같은 실제 시장 특징주가 과도하게 누락된다.
    FEATURE_PRICE_HITS = {
        "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
        "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
        "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
        "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
        "수혜", "수혜주", "관련주", "모멘텀", "호재", "악재",
    }
    feature_price_hits = [x for x in FEATURE_PRICE_HITS if x.lower() in low]
    market_relevant = bool(market_hits) or bool(feature_price_hits)

    # 글로벌 기업 자체 뉴스는 글로벌 뉴스로 노출할 수 있지만
    # 글로벌 기업명을 국내 상장기업/관련주로 절대 사용하지 않는다.
    global_relevant = bool(global_companies) and market_relevant

    # 주식시장 관련 속보/특징주/단독은 최대한 보존한다.
    # 제목에 강한 표지가 있거나 실제 국내 상장기업/종목코드/주가재료가 확인되면 통과.
    feature_context_words = {
        "주식", "증시", "코스피", "코스닥", "종목", "상장", "거래", "주가", "투자",
        "급등", "급락", "상한가", "하한가", "신고가", "신저가", "수주", "계약",
        "공급", "실적", "임상", "승인", "허가", "공시", "특징주"
    }
    strong_stock_signal = bool(domestic or stock_linked or re.search(r"(?:\(|KRX:)\d{6}\)", text))
    feature_context_signal = any(w.lower() in low for w in feature_context_words)
    if is_breaking and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀속보", domestic or global_companies, k1, k2, market_hits
    if is_feature and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚨특징주", domestic or global_companies, k1, k2, market_hits
    if is_exclusive and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀단독", domestic or global_companies, k1, k2, market_hits

    if is_external:
        if stock_linked and market_relevant:
            return True, "📌", domestic, k1, k2, market_hits
        # 외부 콘텐츠는 글로벌 기업 단독 뉴스도 주가 영향 재료가 있을 때만 허용.
        if global_relevant:
            return True, "🌐", global_companies, k1, k2, market_hits
        return False, "외부콘텐츠", [], k1, k2, market_hits

    # 일반 뉴스는 '키워드 2개'가 없다는 이유만으로 좋은 재료를 버리지 않는다.
    # 국내 상장기업 + 명확한 시장재료, 또는 강한 이벤트 신호가 있으면 통과시킨다.
    strong_event_hits = [x for x in (
        "수주", "공급계약", "계약 체결", "양산", "상용화", "출시", "승인", "허가",
        "임상", "기술이전", "마일스톤", "실적", "어닝서프라이즈", "대규모 투자",
        "증설", "공개매수", "자사주", "배당", "신제품"
    ) if x.lower() in low]
    if stock_linked and (market_relevant or strong_event_hits or (k1 and k2)):
        return True, "📌", domestic, k1, k2, market_hits
    if global_relevant:
        return True, "🌐", global_companies, k1, k2, market_hits
    # 국내 관련주가 없어도 의미 있는 글로벌 시황은 보존한다.
    if _engine_is_global_market_news(text):
        return True, "🌐시황", [], k1, k2, market_hits
    return False, "일반", [], k1, k2, market_hits


# 국내 상장기업/관련주 연결 문구. 단순 산업 키워드만으로 종목을 억지 연결하지 않는다.
STOCK_LINK_MAP = {
    "LNG선": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "LNG": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "조선": ["HD한국조선해양", "한화오션", "삼성중공업", "HD현대중공업"],
    "HBM": ["SK하이닉스", "삼성전자", "한미반도체"],
    "AI 반도체": ["SK하이닉스", "삼성전자", "한미반도체"],
    "전력기기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "변압기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "방산": ["한화에어로스페이스", "LIG넥스원", "현대로템"],
    "원전": ["두산에너빌리티", "한전기술", "한전KPS"],
    "로봇": ["두산로보틱스", "레인보우로보틱스", "로보티즈"],
    "2차전지": ["LG에너지솔루션", "삼성SDI", "SK이노베이션"],
    "바이오": ["알테오젠", "유한양행", "셀트리온"],
    "헬스케어": ["알테오젠", "유한양행", "셀트리온"],
    "신약": ["알테오젠", "유한양행", "셀트리온"],
    "기술이전": ["알테오젠", "유한양행", "올릭스"],
    "로열티": ["알테오젠", "유한양행", "셀트리온"],
    "임상": ["HLB", "알테오젠", "유한양행"],
    "항암": ["HLB", "알테오젠", "유한양행"],
}

def _engine_stock_links(text, companies):
    """국내 관심종목 후보를 만든다.
    1) 직접 관련 기업은 실제 사건 문맥이 확인된 경우만 인정
    2) 직접 기업이 없으면 뉴스의 테마를 판별하고 과거 급등/주도 이력으로 순위를 매김
    3) 글로벌 기업명/URL/출처명만으로 국내 종목을 만들지 않음
    """
    t = _engine_clean(text)
    links = []
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, c)]
    for stock in domestic:
        if stock not in links:
            links.append(stock)

    # 종목코드 표기 회사도 직접 관련으로 인정
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, name):
            if name not in links:
                links.append(name)

    # 직접 관련 기업이 없을 때만 테마 후보를 생성한다.
    if not links:
        theme_keys = []
        low = t.lower()
        for key in sorted(STOCK_LINK_MAP, key=len, reverse=True):
            if key.lower() in low:
                theme_keys.append(key)
        # 테마는 단어 하나만으로 강제하지 않고, 사건/수급/산업 변화가 함께 있어야 한다.
        theme_event = any(k in low for k in [
            "수주", "계약", "공급", "투자", "증설", "양산", "출시", "상용화", "승인",
            "허가", "기술이전", "기술수출", "임상", "지분", "실적", "매출", "수출",
            "급등", "급락", "폭등", "폭락", "정책", "규제", "관세", "수요", "가격",
        ])
        if theme_keys and theme_event:
            scored = []
            for key in theme_keys:
                for stock in STOCK_LINK_MAP[key]:
                    hist = 0
                    leader = 0
                    for row in _engine_historical_cache[-3000:]:
                        tx = str(row.get("text", "")) + " " + str(row.get("title", ""))
                        if stock.lower() in tx.lower():
                            hist += 1
                            if any(w in tx.lower() for w in ["상한가", "대장", "주도", "급등", "폭등", "신고가"]):
                                leader += 1
                    score = 10 + min(hist, 10) * 2 + min(leader, 10) * 4
                    scored.append((score, stock, key, hist, leader))
            seen = set()
            for _, stock, key, hist, leader in sorted(scored, reverse=True):
                if stock not in seen:
                    links.append(stock)
                    seen.add(stock)
                if len(links) >= 3:
                    break
    return links[:5]


THEME_MAP = {
    "HBM": "HBM·AI반도체", "AI 반도체": "HBM·AI반도체", "AI칩": "HBM·AI반도체",
    "로봇": "휴머노이드·로봇", "휴머노이드": "휴머노이드·로봇",
    "LNG선": "LNG선·조선", "LNG": "LNG선·조선",
    "방산": "방산·우주항공", "원전": "원전·SMR", "SMR": "원전·SMR",
    "2차전지": "2차전지·배터리", "전고체": "전고체배터리",
    "전력기기": "전력기기·전력망", "변압기": "전력기기·전력망",
    "바이오": "바이오·헬스케어", "AI": "AI",
}

def _engine_ambiguous_group_mentions(text):
    """'삼성', 'SK', 'LG' 같은 그룹명이 실제 사업 이벤트 문맥과 함께 언급됐는지 확인한다.
    특정 상장 계열사를 단정하지 않고, 어떤 그룹이 언급됐는지만 사실 그대로 반환한다.
    (AMBIGUOUS_COMPANY_TERMS는 이전까지 정의만 되고 실제로 쓰이는 곳이 없었다.)"""
    t = _engine_clean(text)
    low = t.lower()
    event_words = [
        "수주", "계약", "공급", "투자", "지분", "매수", "매각", "인수", "합병",
        "실적", "매출", "영업이익", "증설", "양산", "출시", "승인", "허가",
        "특허", "임상", "주가", "주식", "공시", "채용", "구조조정",
    ]
    hits = []
    for g in sorted(AMBIGUOUS_COMPANY_TERMS, key=len, reverse=True):
        if g.lower() not in low or g in hits:
            continue
        # 이미 같은 그룹의 구체적 상장 계열사명이 텍스트에 있으면(예: "SK하이닉스")
        # 그룹명 단독 언급으로 보지 않는다 - 구체적 종목 배지가 이미 따로 표시된다.
        if any(alias != g and alias.startswith(g) and alias.lower() in low for alias in LISTED_COMPANY_ALIASES):
            continue
        for m in re.finditer(re.escape(g), t, re.I):
            a, b = max(0, m.start()-60), min(len(t), m.end()+60)
            ctx = t[a:b].lower()
            if any(w.lower() in ctx for w in event_words):
                hits.append(g)
                break
    return hits[:3]


def _engine_theme(text):
    low = text.lower()
    for key, theme in sorted(THEME_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if key.lower() in low:
            return theme
    return ""

def _engine_relation_reason(text, companies, market_hits):
    low = _engine_clean(text).lower()
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text, c)]

    if domestic:
        # 뉴스에서 실제로 확인되는 사건을 우선해 이유를 만든다.
        if any(x in low for x in ["기술이전", "기술수출", "라이선스", "로열티", "마일스톤"]):
            return "기술이전·기술수출 및 로열티/마일스톤의 실제 현금창출 가능성과 직접 연결"
        if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
            return "임상·허가·상업화 단계가 실제 매출과 기업가치 변화로 이어질 가능성이 확인됨"
        if any(x in low for x in ["지분", "매수", "투자", "유치", "3자배정", "제3자배정"]):
            return "실제 자금 유입·지분 확대가 확인된 기업으로 이번 뉴스의 투자 이벤트와 직접 연결"
        if any(x in low for x in ["수주", "공급계약", "계약", "납품", "공급"]):
            return "실제 수주·계약·공급이 확인돼 향후 매출과 실적에 직접 연결"
        if any(x in low for x in ["실적", "매출", "영업이익", "흑자전환"]):
            return "실적·매출 변화가 직접 확인돼 사업가치와 주가 재평가 가능성 연결"
        if any(x in low for x in ["증설", "양산", "생산", "출시"]):
            return "생산능력 확대·제품 출시가 실제 사업 확대로 이어지는 구간"
        return "뉴스의 핵심 사건 당사자로 직접 확인되며 사업·실적과 연결"

    if any(x in low for x in ["기술이전", "기술수출", "로열티", "마일스톤"]):
        return "기술이전·상업화 가능성이 확인된 바이오 사업가치 변화 테마"
    if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
        return "임상·허가·상업화 진척이 실제 기업가치에 영향을 주는 바이오 테마"
    if any(x in low for x in ["수주", "공급계약", "계약", "납품"]):
        if "lng" in low or "조선" in low:
            return "조선 수주 확대가 국내 조선업체의 수주잔고·실적에 연결되는 테마"
        if "hbm" in low or "반도체" in low or "ai" in low:
            return "AI·반도체 수요 변화가 국내 HBM·메모리 공급망에 전이되는 테마"
        return "계약·수주·공급 변화가 국내 관련 산업의 실적에 전이되는 테마"
    if any(x in low for x in ["투자", "증설", "양산", "수요"]):
        return "투자·증설·수요 변화가 국내 공급망과 관련 종목의 실적 기대에 연결되는 테마"
    if market_hits:
        return "뉴스에서 확인된 시장 재료가 국내 관련 산업의 수급과 실적 기대에 연결되는 테마"
    return ""


def _engine_domestic_watchlist(item):
    """[50] 국내 관련주 단일 판정기.
    출력용 서열(대장주/관찰/관심)을 절대 생성하지 않는다.
    직접 관련 > 실제 테마연결 > 간접연결 순으로 필요한 만큼만 반환한다.
    """
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", ""))
    low = text.lower()
    companies = item.get("companies", []) or []
    theme = _engine_theme(text)
    rows = []

    def event_score(stock):
        score = 0
        best = ""
        terms = {
            "수주":12,"공급계약":12,"계약":10,"납품":9,"투자":9,"유치":10,
            "지분":9,"매수":8,"실적":10,"매출":10,"영업이익":10,"증설":9,
            "양산":10,"출시":10,"상용화":12,"승인":11,"허가":11,"임상":10,
            "기술이전":12,"기술수출":12,"로열티":12,"마일스톤":11,"생산":8,
            "수출":8,"판매":8,"제품":6,"개발":7,"사업":5,"공급":8,
        }
        for ctx in _engine_company_direct_context(text, stock):
            cl=ctx.lower(); n=sum(v for k,v in terms.items() if k in cl)
            if n>score:
                score=n; best=re.sub(r"\s+"," ",ctx).strip()
        return score,best

    def history(stock):
        hist=leader=limitup=surge=0
        for h in _engine_historical_cache[-5000:]:
            tx=_engine_clean(str(h.get("text",""))+" "+str(h.get("title","")))
            if stock.lower() not in tx.lower(): continue
            hist+=1; tl=tx.lower()
            if any(w in tl for w in ["상한가","주도주","주도"]): leader+=1
            if "상한가" in tl: limitup+=1
            if any(w in tl for w in ["급등","폭등","신고가"]): surge+=1
        return hist,leader,limitup,surge

    # 50-01 직접 관련
    direct=[]
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS: continue
        if (c in LISTED_COMPANY_ALIASES or re.search(rf"{re.escape(c)}\s*\((?:KRX:)?\d{{6}}\)",text,re.I)) and _engine_company_is_directly_related(text,c):
            direct.append(c)
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)",text):
        c=m.group(1).strip()
        if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text,c) and c not in direct:
            direct.append(c)
    for c in direct:
        es,ctx=event_score(c)
        if es<10: continue
        hist,leader,limitup,surge=history(c)
        reason = "뉴스 핵심 사건의 직접 사업연관"
        if ctx:
            reason = re.sub(r"\s+"," ",ctx)[:150]
        rows.append({"name":c,"theme":theme or "직접 관련","reason":reason,"score":1000+es*8+leader*10+limitup*12+surge*4,"direct":True})
    if rows:
        rows.sort(key=lambda x:x["score"],reverse=True)
        return rows[:3]

    # 50-02~04 테마/간접 연결: 실제 사건이 있는 경우만
    event_words=["수주","계약","공급","납품","투자","증설","양산","출시","상용화","승인","허가","기술이전","기술수출","임상","지분","실적","매출","수출","정책","규제","관세","수요","가격","데이터센터","AI칩","HBM"]
    if not any(k.lower() in low for k in event_words): return []
    theme_keys=[k for k in sorted(STOCK_LINK_MAP,key=len,reverse=True) if k.lower() in low]
    if not theme_keys:
        if any(k in low for k in ["h200","hbm","ai칩","ai 반도체","반도체","메모리"]): theme_keys=["HBM"]
        elif any(k in low for k in ["바이오","신약","임상","fda","키트루다","로열티","마일스톤"]): theme_keys=["바이오"]
        elif any(k in low for k in ["lng선","lng","조선","선박"]): theme_keys=["조선"]
        elif any(k in low for k in ["방산","미사일","무기","전투기"]): theme_keys=["방산"]
    if not theme_keys: return []
    scored=[]
    for key in theme_keys[:5]:
        if not any(k.lower() in low for k in event_words): continue
        for stock in STOCK_LINK_MAP.get(key,[]):
            hist,leader,limitup,surge=history(stock)
            scored.append({"name":stock,"theme":key,"reason":f"{THEME_MAP.get(key,key)} 테마의 실제 사업·수요 변화와 연결","score":300+limitup*30+leader*20+surge*8+hist*2,"direct":False})
    best={}
    for r in scored:
        if r["name"] not in best or r["score"]>best[r["name"]]["score"]: best[r["name"]]=r
    return sorted(best.values(),key=lambda x:x["score"],reverse=True)[:3]

def _engine_schedule(text):
    """실제 투자 일정만 추출한다.
    텔레그램 게시 시각(예: 14:25)은 일정으로 취급하지 않는다.
    날짜/예정/발표/실적/출시/공급개시 등 미래 이벤트가 명시된 경우만 반환한다.
    """
    t = _engine_clean(text)
    patterns = [
        r'(20\d{2}[./-]\d{1,2}[./-]\d{1,2})[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(\d{1,2}월\s*\d{1,2}일)[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(?:올해|올해\s*하반기|하반기|상반기|다음달|내달|이번달|다음주|이번주)[^.\n]{0,100}(?:공급|출시|발표|실적|승인|시행|양산|상용화|수주)',
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(0).strip()[:160]
    return ""


def _engine_summary(title, extra, companies, market_hits):
    """[40] 기자식 핵심요약 단일 생성기.
    방향 단어만 있는 요약은 폐기하고 사건+변화/원인 중심의 한 문장만 반환한다.
    """
    text=_engine_clean(f"{title} {extra}")
    clean_title=re.sub(r"^\s*(?:\[(?:속보|단독|특징주|종합|긴급)\]\s*)+","",str(title)).strip()
    # 제목에서 흔한 클릭/채널 꼬리표 제거
    clean_title=re.sub(r"\s*(?:[-|｜]\s*)?(?:연합뉴스|뉴스1|매일경제|한국경제|더구루|THEELEC|세모뉴).*$","",clean_title,flags=re.I).strip()
    sentences=[x.strip(" -•") for x in re.split(r"\n+|(?<=[.!?。])\s+",text) if x.strip()]
    movement_only={"상승","하락","강세","약세","급등","급락","폭등","폭락","시장 핵심 재료","증설","상용화"}
    event_terms=["수주","계약","공급","투자","증설","양산","출시","상용화","승인","허가","임상","기술이전","기술수출","실적","매출","영업이익","배당","지분","인수","합병","금리","환율","유가","관세","정책","수요","가격","락업","상장","수출"]
    cause_terms=["때문","따라","여파","배경","원인","확대","감소","증가","후퇴","강화","약화","전환","확정","발표","돌파","개선","악화"]
    candidates=[]
    for idx,p in enumerate(sentences):
        q=re.sub(r"^\([^)]{1,60}\)\s*","",p).strip()
        if len(q)<12 or q in movement_only: continue
        if re.fullmatch(r"[가-힣A-Za-z·\s]+",q) and q in movement_only: continue
        ev=sum(k.lower() in q.lower() for k in event_terms)
        cause=sum(k.lower() in q.lower() for k in cause_terms)
        nums=bool(re.search(r"\d|%|억|조|원",q))
        score=ev*5+cause*3+(4 if nums else 0)+min(len(q),180)/100
        candidates.append((score,idx,q))
    if candidates:
        candidates.sort(reverse=True)
        q=candidates[0][2]
    else:
        q=clean_title if clean_title and clean_title not in movement_only else ""
    q=re.sub(r"^(?:🔎|시장 핵심 재료\s*→)\s*","",q).strip()
    if q in movement_only or re.fullmatch(r"(?:상승|하락|강세|약세|급등|급락|폭등|폭락)(?:·(?:상승|하락|강세|약세|급등|급락|폭등|폭락))*",q):
        q=""
    if len(q)>220: q=q[:220].rsplit(" ",1)[0]+"…"
    return q, _engine_schedule(text)

def _engine_score(item):
    return (4 if item["category"] in ("🚀속보", "🚨특징주", "🚀단독") else 0) + min(3, len(_engine_domestic_companies(item["companies"]))) + min(3, len(item["market_hits"])) + min(2, len(item["extra"]))

_engine_pending = []
_engine_sent_fingerprints = []  # {text, source, time_text, published, title}


def _engine_freshness(item):
    """시장 반영 가능 여부를 고려한 신규/업그레이드/재탕 판정."""
    full = item["title"] + " " + item.get("extra", "")
    current_state = item.get("market_state", "")
    for prev in reversed(_engine_sent_fingerprints):
        prev_text = prev.get("text", "") if isinstance(prev, dict) else str(prev)
        if not _engine_similar(full, prev_text):
            continue
        current_hits = set(_engine_market_hit(full))
        prev_hits = set(_engine_market_hit(prev_text))
        strong_new_words = [
            "계약 체결", "공급계약", "대규모 수주", "신규 수주", "대형 계약", "초대형 계약",
            "확정", "확정 계약", "수주 확정", "공급 확정", "인수 확정", "승인", "허가",
            "독점", "사상 최대", "세계최대", "세계 최대", "대규모 투자"
        ]
        has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", full, re.I))
        prev_has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", prev_text, re.I))
        new_strong = any(w.lower() in full.lower() and w.lower() not in prev_text.lower() for w in strong_new_words)
        new_hit = bool(current_hits - prev_hits)
        if new_strong or new_hit or (has_amount and not prev_has_amount):
            return "업그레이드", prev
        # 시장이 닫혀 있거나 휴무여서 아직 반영할 시간이 없었다면 중복으로 제거하지 않는다.
        if current_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영"):
            return "신규", None
        # 이전 보도 이후 최소 한 번의 시장 세션이 지났을 때만 재탕으로 본다.
        prev_dt = _engine_parse_datetime(prev.get("published", "")) if isinstance(prev, dict) else None
        cur_dt = _engine_parse_datetime(item.get("published", ""))
        if prev_dt and cur_dt and cur_dt.date() > prev_dt.date():
            return "재탕", prev
        return "재탕", prev
    return "신규", None


def _engine_similar(a, b):
    ta = re.sub(r"[^0-9a-zA-Z가-힣]", "", a.lower())
    tb = re.sub(r"[^0-9a-zA-Z가-힣]", "", b.lower())
    ratio = difflib.SequenceMatcher(None, ta[:240], tb[:240]).ratio()
    if ratio >= 0.78:
        return True
    ca = set(_engine_find_companies(a))
    cb = set(_engine_find_companies(b))
    ma = set(_engine_market_hit(a))
    mb = set(_engine_market_hit(b))
    return bool(ca & cb) and bool(ma & mb) and difflib.SequenceMatcher(None, ta[:180], tb[:180]).ratio() >= 0.52


# ============================================================
# [도배 차단] 유사도 80%+ 동일 뉴스 재송출 차단
# ------------------------------------------------------------
# _engine_freshness()는 "재탕"이라고 라벨만 붙이고 그대로 내보내지만,
# 이 함수는 실제로 송출 자체를 막는다. 새로운 확정적 사실(금액/승인/체결 등)이
# 없이 제목·본문 유사도가 DUPLICATE_BLOCK_SIMILARITY 이상이면 같은 뉴스로 보고
# 차단한다. 링크가 달라도(다른 소스가 같은 사건을 재보도) 잡아낸다.
# DUPLICATE_BLOCK_WINDOW_MIN보다 오래된 과거 송출과는 비교하지 않아, 며칠 뒤
# 같은 사건을 재조명하는 기사까지 막지는 않는다.
# ============================================================
_DUPLICATE_STRONG_NEW_WORDS = [
    "계약 체결", "공급계약", "대규모 수주", "신규 수주", "대형 계약", "초대형 계약",
    "확정", "확정 계약", "수주 확정", "공급 확정", "인수 확정", "승인", "허가",
    "독점", "사상 최대", "세계최대", "세계 최대", "대규모 투자",
]
_AMOUNT_RE = re.compile(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", re.I)


def _engine_is_duplicate_spam(item):
    """제목+본문 유사도 80%+ 인 기사가 최근에 이미 송출됐다면 True를 반환한다.
    (실제 새 정보 없는 순수 재전송/도배만 차단하며, 정당한 후속 보도는 통과시킨다.)
    """
    full = _engine_clean(str(item.get("title", "")) + " " + str(item.get("extra", "")))
    if not full:
        return False, None
    now = _now_kst()
    cur_hits = set(_engine_market_hit(full))
    has_amount = bool(_AMOUNT_RE.search(full))
    for prev in reversed(_engine_sent_fingerprints[-500:]):
        prev_text = str(prev.get("text", "")) if isinstance(prev, dict) else str(prev)
        if not prev_text:
            continue
        prev_ts = (prev.get("ts") or prev.get("published") or "") if isinstance(prev, dict) else ""
        prev_dt = _engine_parse_datetime(prev_ts) if prev_ts else None
        if prev_dt:
            # _engine_parse_datetime()/_now_kst() 둘 다 tzinfo 없는 KST 기준 시간을
            # 반환하므로 그대로 뺄셈한다(다른 타임존으로 변환하지 않는다).
            age_min = (now - prev_dt).total_seconds() / 60
            if age_min > DUPLICATE_BLOCK_WINDOW_MIN:
                continue
        ta = re.sub(r"[^0-9a-zA-Z가-힣]", "", full.lower())
        tb = re.sub(r"[^0-9a-zA-Z가-힣]", "", prev_text.lower())
        ratio = difflib.SequenceMatcher(None, ta[:240], tb[:240]).ratio()
        if ratio < DUPLICATE_BLOCK_SIMILARITY:
            continue
        # [업그레이드 예외] 새로운 확정 정보/새 시장영향/새 금액이 추가됐으면
        # 도배가 아니라 정당한 후속 보도이므로 차단하지 않는다.
        prev_hits = set(_engine_market_hit(prev_text))
        new_strong = any(w.lower() in full.lower() and w.lower() not in prev_text.lower() for w in _DUPLICATE_STRONG_NEW_WORDS)
        new_hit = bool(cur_hits - prev_hits)
        prev_has_amount = bool(_AMOUNT_RE.search(prev_text))
        if new_strong or new_hit or (has_amount and not prev_has_amount):
            continue
        return True, prev
    return False, None


COMMERCIAL_VALUE_WORDS = {
    "상용화", "상업화", "양산", "출시", "판매개시", "판매 개시", "공급계약", "공급 계약",
    "수주", "대규모 수주", "계약 체결", "본계약", "독점계약", "기술수출", "기술이전",
    "라이선스", "마일스톤", "FDA 승인", "식약처 승인", "품목허가", "허가취득", "임상3상",
    "임상 성공", "신약 승인", "대규모 투자", "증설", "신규시설투자", "인수", "합병",
    "M&A", "공개매수", "자사주", "흑자전환", "어닝서프라이즈", "사상 최대", "세계 최초",
    "세계최초", "국내 최초", "국내최초", "수출계약", "판매계약", "공급 확대", "수요 급증",
}

def _engine_is_commercial_value(item, title, keypoint=""):
    text = _engine_clean(f"{title} {keypoint} {item.get('extra','')}").lower()
    return any(str(w).lower() in text for w in COMMERCIAL_VALUE_WORDS)

_BYLINE_SPLIT_RE = re.compile(
    r'[가-힣]{2,4}\s*(?:기자|특파원|앵커)\s*=\s*|\([가-힣]{1,10}\s*=\s*[가-힣A-Za-z0-9]{1,20}\)\s*'
)


def _engine_telegram_title(raw_text, channel_name=""):
    """텔레그램 본문에서 실제 기사 제목만 추출한다. [그로쓰리서치] 속보/단독 특징주는 직접 중계하지 않는다."""
    raw = _engine_clean(raw_text)
    if not raw:
        return "", ""
    # 채널명이 본문 맨 앞에 그대로 반복되는 경우 제거 (예: "재야의 고수들 뉴시스 ...")
    ch = _engine_clean(channel_name)
    if ch and raw.startswith(ch):
        raw = raw[len(ch):].strip(" -—|·")
    # 조회수/반응(reaction)/게시시각 잡음만 먼저 제거한다.
    # 기자 바이라인/데이트라인은 아직 지우지 않는다 - 헤드라인과 본문을 나누는 경계로 사용해야 하기 때문.
    raw = re.sub(r'(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*\d+\s*)+', ' ', raw)
    raw = re.sub(r'\b\d+(?:\.\d+)?\s*[Kk]?\s*views?\b', ' ', raw, flags=re.I)
    raw = re.sub(r'^\s*\d{1,2}:\d{2}\s+', '', raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    low = raw.lower()
    if "그로쓰리서치" in low and ("특징주 종목" in low or "실시간 특징주" in low or "특징주 뉴스 속보" in low):
        return "", ""

    # [헤드라인/본문 경계] "OOO 기자 = " 또는 "(서울=뉴시스)" 형태의 바이라인이 있으면
    # 그 앞은 헤드라인, 뒤는 본문으로 명확히 분리한다. 이걸 안 하면 헤드라인 뒤에
    # 공백 없이/짧은 공백으로 바로 이어지는 본문이 제목에 통째로 섞여 들어간다.
    m = _BYLINE_SPLIT_RE.search(raw)
    if m and m.start() >= 6:
        head = raw[:m.start()].strip(" -—|·,")
        body_after = raw[m.end():].strip()
        head_clean = _engine_clean_telegram_meta(head)
        if len(re.sub(r'[^가-힣A-Za-z0-9]', '', head_clean)) >= 8:
            body_clean = _engine_clean_telegram_meta(body_after) or head_clean
            return head_clean[:240], body_clean

    # 바이라인이 없으면 기존 방식대로 문장 후보 중 첫 기사형 문장을 제목으로 사용.
    raw_for_extra = _engine_clean_telegram_meta(raw)
    parts = re.split(r"(?<=[.!?])\s+|\s{2,}|\n+", str(raw))
    candidates = []
    for part in parts:
        part = _engine_clean(part).strip("-—|")
        if not part:
            continue
        if re.match(r"https?://", part, re.I):
            continue
        if any(x in part for x in ["구독", "받기", "실시간 특징주 받기", "채널", "텔레그램"]):
            continue
        if "view/" in part or "t.me/" in part:
            continue
        if part.startswith("[그로쓰리서치]") or "[그로쓰리서치]" in part:
            continue
        candidates.append(part)
    # 가장 먼저 등장하는 충분히 긴 기사형 문장을 제목으로 사용.
    for part in candidates:
        if len(re.sub(r"[^가-힣A-Za-z0-9]", "", part)) >= 8:
            return part[:240], raw_for_extra
    return (candidates[0][:240] if candidates else raw_for_extra[:240]), raw_for_extra



# ============================================================
# [CORE IMMUTABLE RULE] 국내·외신 공통 핵심요약
# 한 줄 핵심 우선, 서로 다른 중요 내용은 다음 줄에 추가하며 개수 제한 없음.
# ============================================================
def _engine_force_numbered_keypoint(title: str, extra: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    body = re.sub(r"\s+", " ", str(extra or "")).strip()
    if not body:
        return ""

    # Remove publisher-only prefixes and common article boilerplate.
    body = re.sub(r"^\s*(?:모닝스타|Reuters|로이터|연합뉴스|조선일보|매일경제)\s*", "", body, flags=re.I)
    body = re.sub(r"^\s*\([^)]{1,100}\)\s*[^:]{1,40}기자\s*[:：]\s*", "", body)

    # Prefer explicit numbered/source points.
    pts = re.findall(
        r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])\s*"
        r"(.+?)(?=\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])|$)",
        body
    )
    pts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in pts if p.strip()]

    if len(pts) < 2:
        # Split prose into factual clauses/sentences.
        parts = re.split(r"(?<=[.!?。！？])\s+|(?<=\s)•\s*|(?<=\s)▶️\s*", body)
        parts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in parts if p.strip()]
        # Drop title-equivalent and meta-only fragments.
        nt = re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()
        filtered = []
        for p in parts:
            np = re.sub(r"[^0-9A-Za-z가-힣]", "", p).lower()
            if not p or np == nt:
                continue
            if any(x in p.lower() for x in ["원문 보기", "view", "kb", "html"]):
                continue
            filtered.append(p)
        pts = filtered

    # Guarantee the requested 1·2·3 display when meaningful content exists.
    pts = pts[:3]
    if not pts:
        return ""

    return "\n".join(f"{i}. {p}" for i, p in enumerate(pts, 1))

# ============================================================
# [CORE IMMUTABLE RULE] 외신 번역 게이트
# Google-US 및 영문 비중이 높은 뉴스는 송출 전에 한국어로 변환.
# 번역 실패 시 영문 제목을 Telegram으로 내보내지 않는다.
# ============================================================
_TRANSLATION_CACHE = {}
# [원인] Google 무료 번역 엔드포인트는 짧은 시간에 여러 건을 연달아 요청하면
# 429(Too Many Requests)를 반환한다. 기존엔 429가 뜨는 즉시 포기하고 그 뉴스를
# 통째로 송출차단했는데, RSS 한 사이클에 미국 뉴스가 여러 건 몰리면(예: 10건)
# 사실상 전부 연쇄로 차단되는 구조적 문제가 있었다. 요청 사이 최소 간격을 두고,
# 429/일시적 오류는 짧게 재시도하도록 고친다.
_TRANSLATE_MIN_INTERVAL_SEC = 2.2
_TRANSLATE_LAST_CALL_TS = [0.0]
_TRANSLATE_LOCK = threading.Lock()

# [번역 재시도 큐] 429 등으로 이번 주기에 번역이 끝내 실패한 외신은 그냥 버리지 않고
# 여기 큐에 남겨 다음 주기(들)에 다시 시도한다. Google 번역 429는 대개 수십 초~분 단위로
# 풀리는 일시적 레이트리밋이라, 몇 분 뒤 재시도하면 성공하는 경우가 많다.
# 최대 재시도 후에도 실패하면 포기하고 큐에서 제거한다(그 뉴스는 송출/과거DB 모두 제외됨:
# 원문이 한국어 분류 키워드와 매칭되지 않아 분류 자체가 어렵기 때문).
_engine_translate_retry_queue = {}
_engine_translate_retry_lock = threading.Lock()
_ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS = 5

def _engine_is_mostly_english(text: str) -> bool:
    s = str(text or "")
    letters = re.findall(r"[A-Za-z가-힣]", s)
    if not letters:
        return False
    en = len(re.findall(r"[A-Za-z]", s))
    ko = len(re.findall(r"[가-힣]", s))
    return en >= 12 and en > ko * 1.25

def _engine_strip_foreign_publisher_suffix(title: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    # RSS title에 붙는 매체명/도메인 꼬리표 제거.
    t = re.sub(r"\s+[-–—|]\s*(?:AD HOC NEWS|Simplywall\.st|simplywall\.st)\s*$", "", t, flags=re.I)
    return t.strip()

def _engine_translate_to_korean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    cached = _TRANSLATION_CACHE.get(text)
    if cached:
        return cached

    # 이미 충분한 한국어라면 번역하지 않는다.
    if not _engine_is_mostly_english(text):
        _TRANSLATION_CACHE[text] = text
        return text

    for attempt in range(3):
        # [요청 간격 강제] 마지막 호출 이후 최소 간격이 지나지 않았으면 대기한다.
        # 이걸 안 하면 같은 사이클에서 뉴스 여러 건이 몰릴 때 Google이 429로 막는다.
        with _TRANSLATE_LOCK:
            wait = _TRANSLATE_MIN_INTERVAL_SEC - (time.time() - _TRANSLATE_LAST_CALL_TS[0])
            if wait > 0:
                time.sleep(wait)
            _TRANSLATE_LAST_CALL_TS[0] = time.time()
        try:
            from urllib.parse import quote
            url = (
                "https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=auto&tl=ko&dt=t&q=" + quote(text)
            )
            r = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=min(ENGINE_HTTP_TIMEOUT, 8),
            )
            if r.status_code == 429 or r.status_code >= 500:
                # [429/일시적 오류] 즉시 포기하지 않고 짧게 대기 후 재시도한다
                # (1차 1초, 2차 2초 백오프). 마지막 시도까지 실패하면 아래에서 빈 문자열 반환.
                if attempt < 2:
                    _engine_log("warning", "[번역 재시도] 외신 | status=%s | %d번째 재시도 예정", r.status_code, attempt + 2)
                    time.sleep(2.0 * (attempt + 1))
                    continue
                _engine_log("warning", "[번역 실패] 외신 | status=%s (재시도 소진)", r.status_code)
                break
            if r.ok:
                data = r.json()
                translated = "".join(
                    str(x[0]) for x in (data[0] or []) if isinstance(x, list) and x and x[0]
                ).strip()
                if translated and not _engine_is_mostly_english(translated):
                    _TRANSLATION_CACHE[text] = translated
                    return translated
            break
        except Exception as e:
            if attempt < 2:
                _engine_log("warning", "[번역 재시도] 외신 | 원인=%s | %d번째 재시도 예정", str(e)[:120], attempt + 2)
                time.sleep(1.0 * (attempt + 1))
                continue
            _engine_log("warning", "[번역 실패] 외신 | %s", str(e)[:120])
            break

    # 영문 원문을 그대로 송출하지 않기 위해 실패는 빈 문자열로 처리한다.
    return ""


# ============================================================
# 지수 포인트 변동 → 등락률(%) 자동 환산
# "다우지수가 518포인트 상승" 처럼 포인트 단위만 표기되면 비교 기준이 없어
# 변동폭 체감이 어렵다. 알려진 주요 지수명 뒤에 포인트 변동 표현이 나오면
# 실시간 시세로 등락률을 조회해 "(약 X.XX%)"를 자동으로 덧붙인다.
# 시세 조회에 실패하면(네트워크 오류 등) 원문을 그대로 두고 조용히 넘어간다.
# ============================================================
INDEX_POINT_TO_PCT_SYMBOLS = {
    "다우존스": "^DJI", "다우지수": "^DJI", "다우": "^DJI",
    "나스닥종합": "^IXIC", "나스닥지수": "^IXIC", "나스닥": "^IXIC",
    "s&p500": "^GSPC", "에스앤피500": "^GSPC", "s&p": "^GSPC",
    "코스피지수": "^KS11", "코스피": "^KS11",
    "코스닥지수": "^KQ11", "코스닥": "^KQ11",
}

_INDEX_POINT_PATTERN = re.compile(
    r'(다우존스|다우지수|다우|나스닥종합|나스닥지수|나스닥|S&P\s?500|코스피지수|코스피|코스닥지수|코스닥)'
    r'[^.]{0,20}?([\d,]+(?:\.\d+)?)\s*(?:포인트|p|pt)\s*(상승|하락|급등|급락|올랐|내렸|올라|내려)',
    re.IGNORECASE
)

_INDEX_PCT_CACHE = {}
INDEX_PCT_CACHE_TTL = 120  # 초 - 같은 지수를 반복 조회하지 않도록 짧게 캐시


def _engine_index_quote_cached(symbol):
    now = time.time()
    cached = _INDEX_PCT_CACHE.get(symbol)
    if cached and (now - cached[0]) < INDEX_PCT_CACHE_TTL:
        return cached[1]
    q = _yahoo_chart_quote(symbol)
    _INDEX_PCT_CACHE[symbol] = (now, q)
    return q


def _engine_annotate_index_points_with_pct(title, extra):
    """포인트 단위 지수 변동 표현 뒤에 실시간 등락률(%)을 덧붙인다."""
    def _sub(m):
        idx_name = m.group(1)
        symbol = INDEX_POINT_TO_PCT_SYMBOLS.get(idx_name.lower().replace(" ", ""))
        if not symbol:
            return m.group(0)
        try:
            q = _engine_index_quote_cached(symbol)
        except Exception as e:
            _engine_log("warning", "[포인트→%% 환산] 시세 조회 실패 | %s | 원인=%s", symbol, str(e)[:100])
            return m.group(0)
        if not q or q.get("change_pct") is None:
            return m.group(0)
        return f"{m.group(0)} (약 {abs(q['change_pct']):.2f}%)"

    def _annotate(text):
        if not text:
            return text
        return _INDEX_POINT_PATTERN.sub(_sub, text)

    return _annotate(title), _annotate(extra)


def _engine_queue_translation_retry(source, title, link, published, extra):
    key = str(link or "").strip() or f"{source}|{title}"
    with _engine_translate_retry_lock:
        entry = _engine_translate_retry_queue.get(key)
        if entry:
            entry["attempts"] += 1
            entry["published"] = published or entry.get("published", "")
        else:
            entry = {"source": source, "title": title, "link": link,
                      "published": published, "extra": extra, "attempts": 1}
            _engine_translate_retry_queue[key] = entry
        if entry["attempts"] >= _ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS:
            del _engine_translate_retry_queue[key]
            _engine_log("warning", "[번역 영구실패] 재시도 %d회 초과로 최종 제외 | %s",
                        _ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS, title[:80])


def _engine_clear_translation_retry(link, title, source):
    key = str(link or "").strip() or f"{source}|{title}"
    with _engine_translate_retry_lock:
        _engine_translate_retry_queue.pop(key, None)


def _engine_retry_translation_queue():
    """매 주기, 지난번 번역 실패로 보류된 외신을 다시 시도한다.
    [원칙] 이 재시도도 결국 _engine_process_item()을 그대로 타므로, 번역이
    이번엔 성공하면 분류→과거DB 누적(절대 원칙)→(시간창 안이면) 실시간 송출까지
    정상적으로 이어진다."""
    with _engine_translate_retry_lock:
        pending = list(_engine_translate_retry_queue.values())
    if not pending:
        return
    _engine_log("info", "[번역 재시도 큐] 대기=%d건 재시도", len(pending))
    for entry in pending:
        try:
            _engine_process_item(entry["source"], entry["title"], entry["link"],
                                  entry.get("published", ""), entry.get("extra", ""))
        except Exception as e:
            log_error("번역 재시도 큐 처리", e, title=str(entry.get("title", ""))[:120])


def _engine_translate_foreign_item(source: str, title: str, extra: str):
    title = _engine_strip_foreign_publisher_suffix(title)
    extra = str(extra or "").strip()

    needs_translation = (
        str(source) == "Google-US"
        or _engine_is_mostly_english(title)
        or _engine_is_mostly_english(extra)
    )
    if not needs_translation:
        title, extra = _engine_annotate_index_points_with_pct(title, extra)
        return title, extra, True

    ko_title = _engine_translate_to_korean(title)
    if not ko_title:
        _engine_log("warning", "[외신 송출차단] 한국어 번역 실패 | %s", title[:100])
        return title, extra, False

    ko_extra = extra
    if extra and _engine_is_mostly_english(extra):
        translated_extra = _engine_translate_to_korean(extra)
        if translated_extra:
            ko_extra = translated_extra

    ko_title, ko_extra = _engine_annotate_index_points_with_pct(ko_title, ko_extra)
    return ko_title, ko_extra, True


# ============================================================
# 원문 실제 부제목(소제목) 조회
# og:description / twitter:description / meta description 순으로
# 원문 페이지에서 실제 부제목을 가져온다. 실패해도 조용히 빈 값으로
# 넘어가며(전체 송출을 지연/차단하지 않음), 결과는 링크 기준으로 캐시한다.
# ============================================================
_SUBTITLE_CACHE = {}
SUBTITLE_FETCH_TIMEOUT = min(ENGINE_HTTP_TIMEOUT, 5)

def _engine_fetch_subtitle(link: str) -> str:
    link = str(link or "").strip()
    if not link.startswith("http"):
        return ""
    if link in _SUBTITLE_CACHE:
        return _SUBTITLE_CACHE[link]
    subtitle = ""
    try:
        r = requests.get(
            link,
            headers={"User-Agent": USER_AGENT},
            timeout=SUBTITLE_FETCH_TIMEOUT,
            allow_redirects=True,
        )
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            for attrs in (
                {"property": "og:description"},
                {"name": "twitter:description"},
                {"name": "description"},
            ):
                tag = soup.find("meta", attrs=attrs)
                content = tag.get("content") if tag else ""
                content = _engine_clean(content)
                # 제목과 동일하거나 너무 짧으면 실제 부제목으로 보지 않는다.
                if content and len(content) >= 8:
                    subtitle = content
                    break
    except Exception as e:
        _engine_log("debug", "[부제목 조회 실패] %s | %s", link[:80], str(e)[:100])
        subtitle = ""
    subtitle = subtitle[:120]
    _SUBTITLE_CACHE[link] = subtitle
    return subtitle


# ============================================================
# 🔎 핵심요약 라인 조립
# ①②③... 번호가 매겨진 항목이 2개 이상이면 줄바꿈+들여쓰기로 나열하고,
# 항목이 1개(번호 없음 포함)면 기존처럼 한 줄로 출력한다.
# 원문에서 실제 부제목을 가져온 경우, 마지막 줄 끝에 " / 부제목"으로 병기한다.
# ============================================================
_KEYPOINT_MARKER_RE = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩]|(?<!\d)\d+[.)])\s*")

def _engine_format_keypoint_lines(keypoint: str, subtitle: str = "") -> list:
    """규칙기반(비-AI) 핵심요약을 '🔎 요약' 헤더 + '     ✔ ...' 체크마크 형식으로 조립.
    AI 분석이 꺼져있을 때도 동일한 보기 형식을 쓰기 위함."""
    text = str(keypoint or "").strip()
    if not text:
        return []

    markers = list(_KEYPOINT_MARKER_RE.finditer(text))
    segments = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = re.sub(r"🔎\s*", "", text[start:end]).strip(" .,-")
        if body:
            segments.append(body)

    if not segments:
        # 번호 마커가 없으면 원문 전체를 한 항목으로 취급.
        whole = re.sub(r"🔎\s*", "", text).strip(" .,-")
        if whole:
            segments = [whole]

    if not segments:
        return []

    subtitle = str(subtitle or "").strip()

    out_lines = ["🔎 요약"]
    for i, body in enumerate(segments):
        line = f"     ✔ {html.escape(body)}"
        if i == len(segments) - 1 and subtitle:
            line += f"   /  {html.escape(subtitle)}"
        out_lines.append(line)
    return out_lines


def _apply_domestic_highlight(text: str, domestic_list: list) -> str:
    for c in domestic_list:
        text = re.sub(rf"(?<!⚡️)({re.escape(c)})", r"⚡️\1", text)
    return text


def _engine_clean_telegram_meta(text: str) -> str:
    """Telegram 전달 메타정보를 제거하고 기사 본문만 남긴다."""
    t = _engine_clean(text or "")
    # Forwarded from [채널] / [작성자] 같은 전달 헤더 제거
    t = re.sub(r'Forwarded from\s*\[[^\]]+\]\s*', ' ', t, flags=re.I)
    t = re.sub(r'^(?:루팡|전달|공유)\s*', '', t, flags=re.I)
    t = re.sub(r'\s*\[메리츠[^\]]*\]\s*', ' ', t, flags=re.I)
    t = re.sub(r'\s*\[[^\]]*(?:증권|리서치|전략|애널리스트|Tech|반도체|디스플레이)[^\]]*\]\s*', ' ', t, flags=re.I)
    # [안전장치] DOM 파싱이 실패해 조회수/반응(reaction)/시간이 텍스트에 섞여 들어온 경우 제거.
    # (근본 수정은 스크래핑 단계에서 message_text 노드만 쓰도록 했지만, 여기서도 2중 방어한다.)
    t = re.sub(r'(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*\d+\s*)+', ' ', t)
    t = re.sub(r'\b\d+(?:\.\d+)?\s*[Kk]?\s*views?\b', ' ', t, flags=re.I)
    # 조회수 다음에 붙는 게시 시각(예: "23:56")이 본문 맨 앞에 그대로 남는 경우 제거.
    t = re.sub(r'^\s*\d{1,2}:\d{2}\s+', '', t)
    # 기자 바이라인/데이트라인 제거: "OOO 기자 = ", "(서울=뉴시스)" 등
    t = re.sub(r'[가-힣]{2,4}\s*(?:기자|특파원|앵커)\s*=\s*', ' ', t)
    t = re.sub(r'\([가-힣]{1,10}\s*=\s*[가-힣A-Za-z0-9]{1,20}\)\s*', ' ', t)
    # 국내 주요 매체명이 채널명 뒤에 그대로 반복되는 경우 제거 (예: "재야의 고수들 뉴시스 ...")
    t = re.sub(
        r'^(?:뉴시스|연합뉴스|이데일리|조선비즈|한국경제|매일경제|머니투데이|파이낸셜뉴스|'
        r'아시아경제|헤럴드경제|서울경제|뉴스1|newsis|edaily)\s+',
        '', t, flags=re.I,
    )
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _engine_extract_title(title: str, extra: str) -> str:
    """전달문/채널명이 섞인 제목에서 실제 기사 제목을 추출한다."""
    raw = _engine_clean_telegram_meta(title)
    raw = re.sub(r'^\s*(?:\[[^\]]+\]\s*)+', '', raw).strip()
    # 제목 뒤에 붙은 동일한 출처/본문 반복 제거
    m = re.search(r'(?P<t>.+?\s+\(\d{6}\)\s+[^-\n]{2,120})(?:\s+-\s+|\s+[-–—]\s+)', raw)
    if m:
        raw = m.group('t').strip()
    if re.search(r'Forwarded from|루팡', raw, re.I) or len(re.sub(r'[^0-9A-Za-z가-힣]', '', raw)) < 8:
        body = _engine_clean_telegram_meta(extra)
        # 첫 기사형 문장을 제목 후보로 사용
        for part in re.split(r'\s{2,}|\n+', body):
            part = part.strip(' -—|')
            if len(re.sub(r'[^0-9A-Za-z가-힣]', '', part)) >= 10:
                raw = part[:180]
                break
    return raw[:180].strip()


def _engine_news_insight(title: str, body: str, source: str = "") -> dict:
    """[DEPRECATED] 더 이상 MASTER 입력이나 Formatter 표시에 사용되지 않는다.
    제목/요약/상용화단계/시장전망/관련주 판단은 반드시 master_condition_manager의
    MasterConditionManager(65조건) -> Validator -> FINAL LOCK 결과만 사용한다.
    (조건1 원문확보 / 조건51 Formatter무판단 / 조건53 재호출금지)
    이 함수는 하위호환을 위해서만 남겨둔다. 새 코드에서 호출하지 말 것.
    """
    t = _engine_clean_telegram_meta(body)
    title = _engine_extract_title(title, t)
    # 제목 반복/출처 반복 제거
    t = re.sub(re.escape(title), ' ', t, count=1, flags=re.I) if title else t
    t = re.sub(r'\s+', ' ', t).strip()
    sentences = [x.strip(' -•') for x in re.split(r'(?<=[.!?。！？])\s+|\s+•\s+|\s+▶️\s+', t) if x.strip()]
    sentences = [x for x in sentences if len(re.sub(r'[^0-9A-Za-z가-힣]', '', x)) >= 12]
    event_terms = ['수주','계약','공급','투자','증설','양산','출시','상용화','승인','허가','임상','기술이전','기술수출','실적','매출','영업이익','배당','자사주','주주환원','정책','관세','금리','수요','가격','생산','판매','구매','도입','발표','FCF']
    change_terms = ['확대','증가','감소','강화','약화','전환','개선','악화','본격','가속','확정','신설','도입','재개','중단','상승','하락']
    scored=[]
    for i,x in enumerate(sentences):
        score=sum(5 for k in event_terms if k in x)+sum(3 for k in change_terms if k in x)+(4 if re.search(r'\d|%|억|조|원|달러',x) else 0)+min(len(x),180)/100
        scored.append((score,i,x))
    scored.sort(reverse=True)
    picked=[]
    for _,_,x in scored:
        if any(_engine_similar(x,y) for y in picked): continue
        picked.append(x)
        if len(picked)>=3: break
    # 원문이 짧으면 제목이 아닌 실제 본문 한 줄을 사용
    if not picked and sentences: picked=sentences[:1]

    low=(title+' '+t).lower()
    commercial=[]
    stage_map=[
        ('양산·판매/공급','양산|대량생산|판매개시|판매 개시|공급 확대'),
        ('수주·계약','수주|공급계약|계약 체결|본계약|판매계약'),
        ('상용화·구매','상용화|상업화|구매|실제 도입|현장 도입'),
        ('검증·승인','승인|허가|인증|테스트 완료|검증'),
        ('개발·투자','개발|연구|투자|증설|시설투자'),
    ]
    for label,pat in stage_map:
        if re.search(pat, low, re.I): commercial.append(label)
    stage=commercial[0] if commercial else ''

    outlook=[]
    if any(k in low for k in ['자사주','주주환원','배당','fcf']):
        outlook.append('주주환원 강화가 주가의 실적 외 지지 요인으로 작용할 가능성')
    elif any(k in low for k in ['수주','공급계약','계약 체결','판매계약']):
        outlook.append('계약·수주가 실제 매출과 수주잔고로 이어지는지 확인하는 구간')
    elif any(k in low for k in ['양산','상용화','실제 도입','구매']):
        outlook.append('기술·테마 단계에서 실제 매출과 생산으로 넘어가는지 여부가 핵심')
    elif any(k in low for k in ['증설','투자','생산']):
        outlook.append('투자·생산 확대가 공급능력과 관련 밸류체인 수요 증가로 이어질 가능성')
    elif any(k in low for k in ['승인','허가','임상']):
        outlook.append('규제·임상 진전 이후 실제 상업화와 매출 전환 여부가 핵심')
    else:
        outlook.append('후속 발표와 실제 실적 반영 여부가 시장 영향의 핵심 확인 포인트')
    if stage:
        outlook.append(f'현재 뉴스는 {stage} 신호가 확인돼 단순 기대보다 실행 단계의 진전 여부가 중요')
    if re.search(r'\d+\s*(?:억|조|원|%)', low):
        outlook.append('제시된 수치의 실제 집행 규모와 지속성이 주가 반응을 좌우할 가능성')
    return {'title':title,'key_points':picked,'stage':stage,'outlook':outlook[:3]}


def _engine_future_schedule(text: str) -> str:
    """오늘 이전/당일 발생 사실은 일정으로 내보내지 않고 미래 이벤트만 반환."""
    s=_engine_schedule(text)
    if not s: return ''
    now=_now_kst().date()
    m=re.search(r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})|(\d{1,2})월\s*(\d{1,2})일',s)
    if m:
        try:
            if m.group(1): d=datetime(int(m.group(1)),int(m.group(2)),int(m.group(3))).date()
            else: d=datetime(now.year,int(m.group(4)),int(m.group(5))).date()
            if d <= now: return ''
        except Exception: return ''
    # '다음주/다음달/예정/계획'만 있는 경우는 미래 표현으로 인정
    if re.search(r'다음주|다음달|내달|하반기|예정|계획',s): return s
    return ''


MASTER_CONFIRMATION_IMAGE = os.environ.get("MASTER_CONFIRMATION_IMAGE", "master_confirmation.png")


_FEATURED_STOCK_HEADLINE_RE = re.compile(
    r"^\s*(?:\[?특징주\]?[:\s]*|코스피\s*특징주[:\s]*|코스닥\s*특징주[:\s]*)?"
    r"(?P<company>[가-힣A-Za-z0-9&]{2,20})\s*,\s*"
    r"(?P<reason>.+?)\s*['\"“]?(?P<reaction>상한가|하한가|급등|급락|강세|약세|신고가|신저가)['\"”]?\s*$"
)


def _engine_has_jongsung(ch: str) -> bool:
    """한글 음절의 받침 유무. 조사(이/가, 을/를)를 문법에 맞게 고르기 위해 사용."""
    if not ch:
        return False
    code = ord(ch) - 0xAC00
    if 0 <= code <= 11171:
        return code % 28 != 0
    return False


def _engine_josa(word: str, with_batchim: str, without_batchim: str) -> str:
    word = str(word or "").strip()
    if not word:
        return without_batchim
    return with_batchim if _engine_has_jongsung(word[-1]) else without_batchim


def _engine_parse_featured_stock_headline(title):
    """'[특징주] 회사, 사유 상한가' 형태의 제목에서 종목명·사유·반응을 뽑아낸다.
    이런 헤드라인은 뉴스 본문이 사실상 제목뿐이라, 파싱 없이는
    (1) 제목 자체가 다루는 종목이 관련주 목록에서 빠지고
    (2) 요약이 제목을 그대로 복사한 의미없는 한 줄로 끝나는 문제가 생긴다.
    """
    m = _FEATURED_STOCK_HEADLINE_RE.search(str(title or "").strip())
    if not m:
        return None
    company = m.group("company").strip(" '\"“”")
    reason = m.group("reason").strip(" ,'\"“”")
    # 사유 끝에 붙은 조사(에/으로/로)는 문장 합성 시 중복되므로 미리 떼어낸다.
    reason = re.sub(r"(에|으로|로)$", "", reason).strip()
    reaction = m.group("reaction").strip()
    if len(company) < 2 or len(reason) < 4:
        return None
    return {"company": company, "reason": reason, "reaction": reaction}


def _engine_master_usable(result):
    """[공용 판정] MASTER 결과가 FINAL LOCK(locked=True)까지 못 갔더라도, 실제로
    쓸 만한 내용(제목 재구성/핵심요약)을 만들어냈으면 '사용 가능'으로 본다.
    포맷터/배지/성과추적이 전부 이 기준으로 통일해야, 사소한 검증 오류 하나
    때문에 화면 표시와 누적 기록이 서로 다른 기준으로 갈리는 일이 없다.
    """
    return bool(result) and bool(result.get('title') or result.get('key_points'))


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


def _engine_master_result(item):
    """뉴스 1건을 MASTER -> Validator -> FINAL LOCK으로 확정한다.
    [조건1/조건10 강제] MASTER는 반드시 원 제목 + 원문 본문을 직접 입력받는다.
    레거시 _engine_news_insight() 결과를 MASTER 입력으로 재사용하지 않는다.
    (MASTER는 title/body만으로 자체적으로 제목 재구성·핵심요약·근거를 계산한다.)
    """
    try:
        rows = _engine_domestic_watchlist(item)
        candidates = []
        for row in rows or []:
            name = str(row.get("name", "")).strip()
            candidates.append({
                "name": name,
                "reason": str(row.get("reason", "")).strip(),
                "score": float(row.get("score", 0) or 0),
                "direct": bool(row.get("direct")),
                "theme_link": False,
                "domestic_listed": True,
                # [수정/누적 데이터 연동] 과거 급등 이력 DB 기반 보조점수를 연결한다.
                # 기존에는 이 키가 어디서도 채워지지 않아 _score()의 history_score
                # 가산 로직이 항상 0으로만 계산됐다.
                "history_score": _engine_company_history_score(name),
            })
        raw_title = str(item.get("title", "")).strip()
        raw_body = str(item.get("extra", "")).strip()

        # [특징주 자기종목 보정] "[특징주] 회사, 사유 '반응'" 헤드라인이고, 본문이 제목과
        # 사실상 동일해 추가 정보가 없는 경우: 제목 안의 사유를 실제 문장으로 풀어서
        # 본문에 채워 넣고, 헤드라인의 주인공 종목을 관련주 후보 1순위로 강제 등록한다.
        featured = _engine_parse_featured_stock_headline(raw_title)
        if featured:
            body_is_thin = (not raw_body) or (_engine_clean(raw_body) == _engine_clean(raw_title)) \
                or (len(raw_body) < len(raw_title) + 8)
            if body_is_thin:
                comp_josa = _engine_josa(featured['company'], '이', '가')
                react_josa = _engine_josa(featured['reaction'], '을', '를')
                synth = f"{featured['company']}{comp_josa} {featured['reason']}에 {featured['reaction']}{react_josa} 기록했다."
                raw_body = synth
            candidates.insert(0, {
                "name": featured["company"],
                "reason": f"헤드라인상 특징주 본인 종목({featured['reaction']} 사유: {featured['reason']})",
                "score": 500.0,
                "direct": True,
                "theme_link": False,
                "domestic_listed": True,
                "history_score": _engine_company_history_score(featured["company"]),
            })

        result = master_finalize_news(
            title=raw_title,
            body=raw_body,
            source=str(item.get("source", "")),
            link=str(item.get("link", "")),
            candidates=candidates,
            schedule=_engine_future_schedule(raw_body),
        )
        # 과거 실제 사례가 있을 때만 '강한 뉴스' 배지를 허용한다.
        hist = _engine_historical_match(item)
        if result and hist:
            result["historical_evidence"] = True
            result["historical_match_ratio"] = round(float(hist[0]), 3)
        if result.get("locked"):
            _engine_log("info", "[FINAL LOCK 통과] %s", str(result.get("title") or item.get("title") or "")[:220])
        elif result.get("validation_errors"):
            # [수정] 검증 오류가 있어도 결과 자체는 버리지 않고 그대로 반환한다.
            # 원인 추적을 위해 어떤 조건이 걸렸는지만 로그로 남긴다.
            _engine_log(
                "warning", "[MASTER 검증 경고] %s | 오류=%s",
                str(result.get("title") or item.get("title") or "")[:220],
                " / ".join(result.get("validation_errors") or []),
            )
        return result
    except Exception as e:
        _engine_log("error", "[MASTER] 실패 | source=%s | 원인=%s", item.get("source", ""), str(e)[:180])
        return None


def _engine_master_badge(result):
    """관련 종목 라벨만 출력한다. 제목에는 아이콘을 붙이지 않는다."""
    # [수정] locked(=검증 완전 통과)만 허용하면, 사소한 검증 오류로 locked=False가 된
    # 경우 이미 확정된 관련종목 배지까지 사라진다. related가 실제로 있으면 표시한다.
    if not result or not (result.get("related") or []):
        return ""
    related = result.get("related") or []
    names = " · ".join(html.escape(str(r.get("name", ""))) for r in related if r.get("name"))
    if not names:
        return ""
    direct = any(bool(r.get("direct")) for r in related)
    value = str(result.get("news_value") or "").strip()
    commercial = bool(result.get("commercial_stage") or result.get("commercial_evidence"))
    labels = []
    if direct:
        labels.append("🎯 직접 연결 종목")
    else:
        labels.append("🎯 관련 종목")
    if commercial and str(result.get("commercial_evidence") or "").strip():
        labels.append("💰 돈되는 뉴스")
    if value == "높음" and (result.get("historical_evidence") or result.get("news_value_evidence")):
        labels.append("🔥 강한 뉴스")
    return " | ".join(labels) + "\n" + names


def _engine_master_image_path(result):
    """구버전 이미지 출력 호환용. 현재 최우선 출력 정책에서는 이미지를 생성하지 않는다."""
    return ""
    # legacy implementation intentionally unreachable
    if not result or not result.get("locked"):
        return ""
    related = result.get("related") or []
    leader = result.get("leader") or {}
    if not related or not leader.get("name"):
        return ""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        out = MASTER_CONFIRMATION_IMAGE
        if not os.path.isabs(out):
            out = os.path.join(base, out)
        os.makedirs(os.path.dirname(out) or base, exist_ok=True)
        img = Image.new("RGB", (1500, 260), (5, 17, 25))
        draw = ImageDraw.Draw(img)
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        font_big = ImageFont.truetype(font_path, 54)
        font_small = ImageFont.truetype(font_path, 42)
        # Green confirmation frame
        draw.rounded_rectangle((18, 18, 1482, 242), radius=28, outline=(65, 235, 45), width=5, fill=(7, 25, 18))
        # Target + green indicator
        draw.ellipse((45, 75, 125, 155), fill=(55, 210, 45), outline=(180, 255, 150), width=4)
        draw.ellipse((66, 96, 104, 134), fill=(5, 17, 25))
        text = f"[MASTER 확정] 관련주={len(related)} | 대장주={leader.get('name')} | stage={result.get('stage') or '없음'}"
        # Fit text to width.
        font = font_big
        while draw.textbbox((0,0), text, font=font)[2] > 1310 and font.size > 28:
            font = ImageFont.truetype(font_path, font.size - 2)
        draw.text((145, 82), text, font=font, fill=(85, 255, 45))
        img.save(out, format="PNG", optimize=True)
        return out
    except Exception as e:
        _engine_log("warning", "[MASTER] 이미지 생성 실패 | 원인=%s", str(e)[:160])
        return ""


def _engine_send_telegram_photo(photo_path, caption=""):
    if not BOT_TOKEN or not CHAT_ID:
        _engine_log("error", "[실패] Telegram 사진전송 | BOT_TOKEN/CHAT_ID 없음")
        return False
    if not photo_path or not os.path.exists(photo_path):
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as photo:
            r = requests.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"},
                files={"photo": photo},
                timeout=ENGINE_HTTP_TIMEOUT,
            )
        api_result = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if r.ok and api_result.get("ok", True):
            _engine_log("info", "[성공] Telegram MASTER 이미지 전송")
            return True
        _engine_log("error", "[실패] Telegram MASTER 이미지 전송 | 원인=%s", api_result.get("description") or r.reason)
    except Exception as e:
        _engine_log("error", "[실패] Telegram MASTER 이미지 전송 | 원인=%s", str(e)[:160])
    return False


_PHARMA_KEYWORDS_RE = re.compile(
    r"제약|바이오|신약|임상\s*[1-31-3]?상|FDA|식약처|백신|항체|치료제|의약품|바이오시밀러|파이프라인",
    re.I,
)


def _engine_is_pharma_news(title, extra_text=""):
    """제약/바이오 뉴스인지 판단해 제목 앞에 💊 마커를 붙일지 결정한다."""
    return bool(_PHARMA_KEYWORDS_RE.search(f"{title} {extra_text}"))


def _engine_line_is_duplicate(candidate, shown_texts, threshold=0.6):
    """짧은 문장 단위 중복 검사. 🔎[핵심]에 이미 쓰인 문장과 사실상 같은 내용을
    🧠[분석_전망]에서 또 보여주는 것을 막기 위해 쓴다(공백 무시 완전 포함 관계 +
    difflib 유사도 기준 둘 다 확인)."""
    cand_n = re.sub(r'\s+', '', str(candidate)).strip()
    if not cand_n:
        return True
    for shown in shown_texts:
        shown_n = re.sub(r'\s+', '', str(shown)).strip()
        if not shown_n:
            continue
        if cand_n in shown_n or shown_n in cand_n:
            return True
        if difflib.SequenceMatcher(None, cand_n[:200], shown_n[:200]).ratio() >= threshold:
            return True
    return False


def _engine_market_state_sentence(market_state):
    """market_state 값을 헤딩식 라벨(현재 시장: ...)이 아니라 자연스러운
    서술형 문장으로 바꾼다."""
    state = str(market_state or '').strip()
    if not state:
        return ''
    if state == '시장 휴무로 미반영':
        return '현재 시장이 휴무라 이 소식은 아직 실시간으로 반영되지 않았다.'
    if state == '시장 마감 후 뉴스':
        return '시장 마감 이후 나온 소식이라 다음 거래일 반영 여부를 지켜봐야 한다.'
    return f'현재 시장 상황은 {state}이다.'


def _engine_format_message(item):
    """최종 Telegram 메시지.
    최우선 사용자 출력 규칙: 짧고 사실/데이터 중심이며 중복 장식은 금지한다.
    Formatter는 판단하지 않고 MASTER FINAL LOCK 결과만 표시한다.
    """
    source_raw = str(item.get('source','')).strip()
    source_display = '🇺🇸' if source_raw == 'Google-US' else source_raw
    time_text = str(item.get('time_text','')).strip()
    raw_title = str(item.get('title','')).strip()
    master_result = item.get('_master_result') or {}

    # [수정] 기존에는 master_result.get('locked')(=검증 완전 통과)일 때만 MASTER
    # 결과를 사용했다. 그 결과 사소한 검증 오류 하나로 locked=False가 되면 이미
    # 계산된 제목/핵심/용어설명/관련종목까지 전부 버려지고 원본 제목만 나갔다.
    # 이제 locked 여부와 무관하게, MASTER가 실제로 뭔가 만들어낸 경우(제목 재구성
    # 결과나 핵심요약이 존재하는 경우)에는 그 내용을 그대로 사용한다.
    master_usable = _engine_master_usable(master_result)
    if master_usable:
        title = master_result.get('title') or _engine_strip_foreign_publisher_suffix(raw_title)
        key_points = list(master_result.get('key_points') or [])[:3]
        stage = str(master_result.get('stage') or '').strip()
        outlook = list(master_result.get('outlook') or [])
        related = list(master_result.get('related') or [])[:3]
        schedule = str(master_result.get('schedule') or '').strip()
        analysis = str(master_result.get('analysis') or '').strip()
        freshness = str(master_result.get('freshness') or '').strip()
        if not freshness:
            freshness, _ = _engine_freshness(item)
    else:
        title = _engine_strip_foreign_publisher_suffix(raw_title)
        key_points, stage, outlook, related, schedule, analysis = [], '', [], [], '', ''
        freshness, _ = _engine_freshness(item)

    # 화면 표식은 사용자 지정 위치에만 사용한다.
    companies = item.get('companies', []) or []
    domestic = _engine_domestic_companies(companies)
    is_pharma = _engine_is_pharma_news(title, ' '.join(key_points))
    is_listed = bool(domestic)

    # 일반 뉴스 제목엔 📌, 제약뉴스 제목엔 💊를 접두사로 붙인다.
    # 상장종목은 접두사 없이 제목 아래에 👀 관련주 배지로 별도 표시한다.
    header = f'<b>📰 [{html.escape(source_display)}] {html.escape(freshness or "신규")}</b>'
    if time_text:
        header += f'  🕐 {html.escape(time_text)}'
    if is_listed:
        title_prefix = ''
    elif is_pharma:
        title_prefix = '💊 '
    else:
        title_prefix = '📌 '
    lines = [header, f'<b>{title_prefix}{html.escape(title)}</b>']

    market_state = str(item.get('market_state') or '').strip()
    # [수정] 예전엔 이 문장이 "🧠 분석_전망"의 유일한 내용일 때도 그대로
    # 들어가서, MASTER가 실제 분석을 못 만든 뉴스마다 매번 똑같은 문장이
    # "분석"인 척 반복 노출됐다(사용자 신고: "똑같은 문구의 같은 대답").
    # 이제 헤더 옆에 짧은 상태 태그로만 붙이고, 🧠 분석_전망에는 실제
    # analysis/outlook 내용이 있을 때만 보조 문장으로 덧붙인다.
    _market_tag = {
        '시장 휴무로 미반영': '💤 휴무 미반영',
        '시장 마감 후 뉴스': '⏳ 마감후',
    }.get(market_state)
    if _market_tag:
        header += f'  {_market_tag}'
        lines[0] = header

    # ============================================================
    # 👀/🎯 [관련주] 통합
    # ------------------------------------------------------------
    # MASTER가 '유기적으로 실제 사업·실적에 영향'을 준다고 직접 확정한 종목
    # (related[].direct=True)이 있으면 🎯 [관련주]로 표시하고, 그 정도의
    # 직접 확정 없이 본문/제목에서 단순히 확인만 된 상장종목이면 👀 [관련주]로
    # 표시한다. 둘 다 없으면 최소한 어떤 테마인지 🏷 [테마]로 보여준다.
    # 같은 종목을 두 배지에서 중복 표시하지 않는다.
    # ============================================================
    direct = [r for r in related if r.get('direct')] if related else []
    direct_names = [str(r.get('name', '')).strip() for r in direct[:3] if r.get('name')]
    if direct_names:
        lines.append(f'🎯 <b>관련주</b> : {html.escape(" · ".join(direct_names))}')
    elif is_listed:
        names = ' · '.join(str(x) for x in domestic[:3])
        lines.append(f'👀 <b>관련주</b> : {html.escape(names)}')
    else:
        # [1원칙] 직접 연결된 관련주가 없다면 최소한 어떤 테마인지는 뽑아서 보여준다.
        # 관련주 없음 자체를 빈 결과로 남기지 않는다.
        theme_guess = _engine_theme(_engine_clean(f"{raw_title} {item.get('extra','')}"))
        if theme_guess:
            lines.append(f'🏷 <b>테마</b> : {html.escape(theme_guess)}')
        # [수정] "삼성", "SK", "LG" 같은 그룹명만 언급되고 구체적 상장계열사가
        # 특정되지 않는 경우, 예전엔 그냥 조용히 사라졌다(AMBIGUOUS_COMPANY_TERMS는
        # 정의만 되고 미사용 상태였음). 특정 종목을 단정하지 않고 "그룹명이 언급됐다"는
        # 사실만 정확히 알려서, 무엇을 놓쳤는지는 최소한 보이게 한다.
        group_hits = _engine_ambiguous_group_mentions(_engine_clean(f"{raw_title} {item.get('extra','')}"))
        if group_hits and not theme_guess:
            lines.append(f'🏷 <b>그룹 언급</b> : {html.escape(" · ".join(group_hits))} (계열사 미특정)')

    # 신규/후속/재탕은 header의 상태 하나로만 표시한다. 같은 뜻을 다시 설명하지 않는다.

    # 🔎[핵심]에 실제로 쓰인 문장들을 기록해 두고, 🧠[분석_전망]에서
    # 같은 내용을 그대로 반복하지 않도록 뒤에서 이 목록과 대조한다.
    shown_texts = []
    if key_points:
        lines.append('🔎 <b>핵심</b>')
        for kp in key_points:
            clean = re.sub(r'^[▶️•✔️\s]+', '', str(kp)).strip()
            if clean and not _engine_line_is_duplicate(clean, shown_texts):
                lines.append('     ✔ ' + html.escape(clean[:180]))
                shown_texts.append(clean)

    # ============================================================
    # 🧠 [분석_전망]
    # ------------------------------------------------------------
    # 본문 사실 기반 분석(analysis)과 향후 전망(outlook)을 한 섹션으로 합쳐,
    # 🔎[핵심]과 동일하게 문장 단위 서술형 불릿으로 보여준다. 이미 핵심에
    # 나온 문장과 사실상 같은 내용은 여기서 다시 반복하지 않는다. 시장이
    # 현재 휴장/마감 상태라 실시간으로 반영되지 않았다면 market_state를
    # 자연스러운 문장으로 풀어 마지막에 덧붙인다.
    # ============================================================
    analysis_lines = []
    for candidate in ([analysis] if analysis else []) + [str(x).strip() for x in outlook]:
        candidate = candidate.strip()
        if candidate and not _engine_line_is_duplicate(candidate, shown_texts):
            analysis_lines.append(candidate)
            shown_texts.append(candidate)
    market_sentence = _engine_market_state_sentence(market_state)
    # [수정] 실제 analysis/outlook 내용이 하나도 없는데 이 문장 혼자만 들어가면
    # "매 뉴스마다 똑같은 답"으로 보인다. 이제 실제 내용이 있을 때만 보조로 붙이고,
    # 없으면 헤더의 상태 태그(💤/⏳)로만 표시하고 🧠 분석_전망 섹션 자체를 생략한다.
    if market_sentence and analysis_lines and not _engine_line_is_duplicate(market_sentence, shown_texts):
        analysis_lines.append(market_sentence)
    if analysis_lines:
        lines.append('🧠 <b>분석_전망</b>')
        for al in analysis_lines:
            lines.append('     ✔ ' + html.escape(al[:220]))

    badge_text = str(_engine_master_badge(master_result) or '')
    # 내용/데이터가 없는 빈 라벨은 절대 표시하지 않는다.
    # [수정] '💰 돈되는 뉴스' → '💰 진행 과정'으로 라벨을 바꾸고 구분자를 ':' 로 통일한다.
    if '돈되는 뉴스' in badge_text and master_result.get('commercial_evidence'):
        lines.append('👀 <b>진행 과정</b> : ' + html.escape(str(master_result.get('commercial_evidence'))[:180]))
    if '강한 뉴스' in badge_text and (master_result.get('news_value') == '높음' or master_result.get('historical_evidence')):
        lines.append('🔥 <b>강한 뉴스</b>')

    # ============================================================
    # 🧠 [데이터 값]
    # ------------------------------------------------------------
    # 이 종목이 과거에 몇 번 등장했고(HISTORICAL_SURGE_DB), 그때 실제
    # 등락률은 어땠는지(OUTCOME_TRACKING_DB), 과거 등장 시점의 시장상황과
    # 지금 시장상황이 다른지를 누적값 기준으로 한 섹션에 모아 보여준다.
    # 쌓인 데이터가 없으면 섹션 자체를 생략한다(형식적 기록 없음).
    # ============================================================
    lead_name = ''
    if related:
        lead_name = direct_names[0] if direct_names else str(related[0].get('name', '')).strip()
    if not lead_name and domestic:
        # MASTER가 관련주를 별도로 확정하지 못했어도, 본문에서 직접 추출된
        # 상장종목(👀관련주 배지)이 있으면 그 종목 기준으로 과거 데이터를 조회한다.
        lead_name = str(domestic[0]).strip()
    # [데이터 누적형 분석] 현재 뉴스 → 현재 시장 → 과거 유사시장 → 실제 과거성과를
    # 순서대로 비교해서 보여준다. 데이터가 없는 항목은 절대 만들어내지 않고 생략한다.
    if lead_name:
        hist = _engine_company_history_detail(lead_name)
        outc = _engine_company_outcome_stats(lead_name)
        data_lines = []

        if hist:
            compare_parts = [f"과거 유사 재료 이력 {hist['count']}건"]
            if market_state:
                compare_parts.append(f"현재 시장: {market_state}")
            if hist.get('state_counts'):
                same_state_count = hist['state_counts'].get(market_state, 0) if market_state else 0
                past_state, _cnt = hist['state_counts'].most_common(1)[0]
                if market_state and same_state_count:
                    compare_parts.append(f"그중 동일 시장상황({market_state}) {same_state_count}건")
                elif market_state and past_state and past_state != market_state:
                    compare_parts.append(f"과거엔 주로 '{past_state}'였고 이번엔 '{market_state}'")
            data_lines.append(' · '.join(compare_parts))

        if outc:
            sign = '+' if outc['avg'] >= 0 else ''
            data_lines.append(
                f"표본 {outc['count']}건 · 상승비율 {outc['success_rate']:.0f}% · "
                f"평균 등락률 {sign}{outc['avg']:.2f}%"
            )
            # 판단: 표본이 충분할 때만 강함/관심/주의를 매긴다.
            # 표본이 적으면 데이터를 근거로 단정하지 않고 '데이터 부족'으로만 표시한다.
            if outc['count'] >= 5:
                if outc['success_rate'] >= 60 and outc['avg'] > 0:
                    verdict = '강함'
                elif outc['success_rate'] >= 40:
                    verdict = '관심'
                else:
                    verdict = '주의'
            else:
                verdict = f"관심 (표본 {outc['count']}건, 판단하기엔 부족)"
            data_lines.append(f"판단 : {verdict}")

        if data_lines:
            lines.append('🧠 <b>데이터 값</b>')
            for dl in data_lines:
                lines.append('     ✔ ' + html.escape(dl))

    # ------------------------------------------------------------
    # 📊 [실적 정보] - 번역 전 원문에서 추출한 beat/miss, 매출, EPS.
    # 관련주 매칭(lead_name) 성공 여부와 무관하게, 실적 수치가 실제로
    # 추출된 경우에만 표시한다(형식적 기록 없음).
    # ------------------------------------------------------------
    earnings_info = item.get('earnings_info')
    if earnings_info and earnings_info[0]:
        _, beat_or_miss, revenue, eps = earnings_info
        earn_parts = []
        if beat_or_miss == 'beat':
            earn_parts.append('컨센서스 상회(어닝서프라이즈)')
        elif beat_or_miss == 'miss':
            earn_parts.append('컨센서스 하회(어닝쇼크)')
        if revenue:
            earn_parts.append(f"매출 {revenue}")
        if eps:
            earn_parts.append(f"EPS {eps}")
        if earn_parts:
            lines.append('📊 <b>실적 정보</b>')
            lines.append('     ✔ ' + html.escape(' · '.join(earn_parts)))

    # ============================================================
    # 💡 [용어]
    # ------------------------------------------------------------
    # 경제/전문 용어 설명만 사실 기반으로 간단히 정리한다. 형식적인 항목은
    # 채워 넣지 않고, 실제 설명이 있는 용어만 표시한다.
    # ============================================================
    terms = (master_result or {}).get('term_explanations') or []
    if terms:
        shown = []
        for t in terms[:2]:
            term = str(t.get('term','')).strip()
            desc = str(t.get('description','')).strip()
            if term and desc:
                shown.append(f'{term}: {desc}')
        if shown:
            lines.append('💡 <b>용어</b>')
            lines.append(html.escape(' · '.join(shown)[:420]))

    if schedule:
        lines.append('📅 ' + html.escape(schedule[:180]))
    if item.get('link'):
        lines.append(f'<a href="{html.escape(str(item["link"]),quote=True)}">🔗 원문</a>')
    return '\n\n'.join(x for x in lines if str(x).strip())


def _engine_flush_pending():
    """대기 뉴스는 유사기사라도 묶어서 요약하지 않고 각 기사를 그대로 판단한다.
    단, 유사도 DUPLICATE_BLOCK_SIMILARITY(기본 80%) 이상인 '사실상 동일 뉴스'가
    최근에 이미 송출됐고 새로운 확정 정보가 없다면 도배로 보고 송출 자체를 막는다.
    (_engine_freshness()의 [신규]/[업그레이드]/[재탕] 라벨은 통과한 기사 표시용으로 유지.)
    동일 URL은 같은 폴링에서만 1회 처리하여 1분 주기 무한도배만 막는다.
    """
    global _engine_pending
    if not _engine_pending:
        return 0
    candidates = list(_engine_pending)
    candidates.sort(key=_engine_score, reverse=True)
    sent = 0
    dup_blocked = 0
    cycle_keys = set()
    for item in candidates[:ENGINE_MAX_SEND_PER_CYCLE]:
        key = item["key"]
        if key in cycle_keys:
            continue
        cycle_keys.add(key)
        # [원칙] 카테고리가 없으면 여기서도 다시 한번 차단한다(이중 안전장치).
        if not str(item.get("category") or "").strip():
            _engine_log("info", "[제외] 카테고리 없음(송출 직전) | %s", str(item.get("title", ""))[:80])
            continue
        if not _engine_telegram_spam_allowed(item):
            continue
        # 기존 상태파일에 이미 저장된 URL(동일 링크)은 재전송하지 않는다.
        if key in _engine_seen:
            continue
        # [도배 차단] 링크가 다르더라도 제목+본문 유사도 80%+ 인 '사실상 동일 뉴스'가
        # 최근에 이미 송출됐다면(그리고 새로운 확정 정보가 없다면) 여기서 차단한다.
        is_dup, dup_prev = _engine_is_duplicate_spam(item)
        if is_dup:
            dup_blocked += 1
            prev_title = str((dup_prev or {}).get("title", ""))[:80] if isinstance(dup_prev, dict) else ""
            _engine_log("info", "[제외] 유사도 80%%+ 도배 차단 | %s | 선행=%s", item.get("title", "")[:80], prev_title)
            _engine_mark_seen(key)
            continue
        master_result = _engine_master_result(item)
        item["_master_result"] = master_result
        message = _engine_format_message(item)
        master_badge = _engine_master_badge(master_result)
        image_sent = False
        # 뉴스 본문은 텍스트 카드만 전송한다. 기존 MASTER 🎯 이미지 카드는 사용하지 않는다.
        text_sent = _engine_send_telegram(message)
        if text_sent:
            _engine_mark_seen(key)
            full_text = item["title"] + " " + item["extra"]
            fingerprint = {
                "text": full_text, "source": item["source"],
                "time_text": item.get("time_text", ""),
                "published": item.get("published", ""),
                "title": item["title"], "market_state": item.get("market_state", ""),
                "ts": _now_kst().isoformat(),
            }
            _engine_sent_fingerprints.append(fingerprint)
            if len(_engine_sent_fingerprints) > 3000:
                del _engine_sent_fingerprints[:-3000]
            _engine_atomic_append_jsonl(SENT_FINGERPRINT_DB, fingerprint)
            _engine_telegram_mark_sent(item)
            _engine_record_global_briefing(item)
            _engine_record_historical_case(item)
            _engine_record_outcome_tracking(item, master_result)
            sent += 1
            _engine_log("info", "[Telegram 전송 성공] %s", str(item.get("title") or "")[:220])
    _engine_log("info", "[송출결과] 후보=%d | 묶음차단=0 | 도배차단=%d | 전송=%d", len(_engine_pending), dup_blocked, sent)
    _engine_pending = []
    return sent


def _engine_is_relevant(title):
    t = title.lower()
    kws = set()
    for x in UNIQUE_TARGET | UNIQUE_GIANTS | UNIQUE_CELEBS:
        if x and x.lower() in t:
            kws.add(x)
    for x in MONEY_STRONG_WORDS:
        if x.lower() in t:
            kws.add(x)
    return list(kws)[:8]


def _engine_is_within_recent_window(published, window_minutes=60):
    """현재 KST 기준 최근 window_minutes분 이내 뉴스만 실시간 송출 대상으로 허용한다.
    과거 뉴스는 분석/비교 DB에서 활용할 수 있지만 현재 뉴스 송출에서는 제외한다.
    [테스트 모드] NEWS_BOT_TEST_MODE=1 이면 window_minutes를 NEWS_BOT_TEST_WINDOW_MIN까지
    강제로 늘려서, 실시간 뉴스가 없는 시간대에도 과거 기사로 파이프라인을 검증할 수 있다.
    """
    if NEWS_BOT_TEST_MODE:
        window_minutes = max(int(window_minutes), NEWS_BOT_TEST_WINDOW_MIN)
    if not published:
        return False
    dt = _engine_parse_datetime(published)
    if not dt:
        return False
    now = _now_kst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    else:
        dt = dt.astimezone(now.tzinfo)
    age_seconds = (now - dt).total_seconds()
    return 0 <= age_seconds <= window_minutes * 60


def _engine_process_item(source, title, link, published="", extra=""):
    title = _engine_clean(title); extra = _engine_clean(extra); link = str(link or "").strip()
    if not title:
        return False

    # 외신은 여기서 단 한 번만 번역한다.
    # 이후 🔎/테마/관련주/출력은 동일한 한국어 분석 원문을 사용한다.
    _orig_title_for_retry = title
    title, extra, translation_ok = _engine_translate_foreign_item(source, title, extra)
    if not translation_ok:
        # [수정] 예전엔 번역 실패(주로 429) 시 그 자리에서 뉴스를 완전히 버렸다.
        # 도메인/과거DB 절대 원칙(카테고리만 확정되면 무조건 누적)이 적용되려면
        # 애초에 분류 단계까지 가야 하는데, 번역 실패는 분류보다 앞에서 막아버려서
        # 외신은 이 원칙의 사각지대였다. 이제 즉시 폐기 대신 재시도 큐에 남겨
        # 다음 주기(들)에 번역을 다시 시도하고, 성공하면 정상적으로
        # 분류→과거DB 누적→(시간창 이내면) 실시간 송출까지 이어지게 한다.
        _engine_queue_translation_retry(source, _orig_title_for_retry, link, published, extra)
        return False
    _engine_clear_translation_retry(link, _orig_title_for_retry, source)

    # [수정] 실적(어닝) 관련 수치(beat/miss, 매출액 등)는 번역 과정에서 부정확해지거나
    # 손실되기 쉬우므로, 번역 전 원문(영문/한글 모두 가능)에서 직접 추출해 둔다.
    # (_extract_earnings_info는 정의만 되어 있고 그동안 호출되는 곳이 없던 죽은 코드였음)
    try:
        earnings_info = _extract_earnings_info(_orig_title_for_retry)
    except Exception:
        earnings_info = (False, None, None, None)

    # 원문 전체를 보존한다. 요약문으로 extra를 덮어쓰지 않는다.

    # 사용자가 원치 않는 [그로쓰리서치] 속보/단독/특징주 채널은 원천 제외.
    growth_block = ("그로쓰리서치" in str(source)) or ("rocket_news1" in link) or ("growth_semi" in link) or ("growthbio" in link) or ("growthresearch" in link)
    if growth_block:
        _engine_log("info", "[제외] 그로쓰리서치 채널 차단 | %s | %s", source, title[:80])
        return False

    # [수정] 기존에는 "최근 60분 이내 발행" 시간 게이트를 분류(classify)보다도 먼저
    # 통과해야 했고, 그 결과 텔레그램으로 실제 전송된 뉴스만 과거DB(HISTORICAL_SURGE_DB)에
    # 쌓이는 구조였다. 시간 게이트는 원래 "실시간 송출" 여부만 결정해야 하는데,
    # 데이터 누적(시장비교/과거성과 분석의 기반)까지 함께 막아버려서 과거DB가 계속
    # 비어 있었다. 이제 분류를 먼저 수행하고, 카테고리가 확정되면 시간 게이트와
    # 무관하게 곧바로 과거DB에 누적한 뒤, 실시간 송출 여부만 시간 게이트로 판단한다.
    ok, category, companies, k1, k2, market_hits = _engine_classify(source, title, extra)
    market_state = _engine_market_state(source, published)
    if ok and str(category or "").strip():
        try:
            _engine_record_historical_case({
                "title": title, "extra": extra, "link": link, "published": published,
                "companies": companies, "market_hits": market_hits, "market_state": market_state,
            })
        except Exception as e:
            _engine_log("warning", "[과거DB 누적 실패] %s | %s", str(e)[:160], title[:80])

    # 모든 뉴스 소스 공통: 현재 KST 기준 최근 60분 이내 발행 뉴스만 실시간 송출 대상.
    # (과거 뉴스는 위에서 이미 과거DB에 누적됐고, 여기서는 신규 뉴스로 재송출하지 않는다.)
    if not _engine_is_within_recent_window(published, 60):
        _engine_log("info", "[제외-송출] ⏱️ 최근 1시간 밖의 뉴스(과거DB엔 누적됨) | source=%s | %s", source, title[:80])
        return False
    gate_ok, gate_reason = _engine_external_time_gate(source, published, title, extra, market_state, market_hits)
    if not gate_ok:
        _engine_log("info", "[제외] ⏱️ %s | %s", gate_reason, title[:80])
        return False
    if market_state == "시장시간 확인불가":
        _engine_log("warning", "[로직] 시장시간 확인 필요 | source=%s | %s", source, title[:80])
    # 송출 대상이 아니어도 미래의 중요 일정은 별도 DB에 누적한다.
    # 일정 추출 함수에서 특징주/급등/상한가/주요 이벤트 여부를 다시 엄격히 검증한다.
    try:
        _schedule_add_news_item(source, title, extra, link, published, companies, market_hits)
    except Exception as e:
        _engine_log('warning', '[일정DB 누적 실패] %s', str(e)[:160])
    key = link or f"{source}|{title}"
    with _engine_lock:
        if key in _engine_seen:
            return False
    # [원칙] 카테고리가 없으면(분류 실패) 절대 노출하지 않는다.
    if not ok or not str(category or "").strip():
        reason = "카테고리 없음" if not str(category or "").strip() else (
            "상장기업·주가재료 없음" if source.startswith(("텔레그램/", "유튜브/")) else "기업·주가재료 조건 불충족"
        )
        _engine_log("info", "[제외] %s | %s | %s", source, reason, title[:80])
        return False
    time_text = ""
    dt = _engine_parse_datetime(published)
    if dt:
        time_text = dt.strftime("%H:%M")
    _engine_pending.append({"source":source,"title":title,"link":link,"published":published,"extra":extra,"key":key,"category":category,"companies":companies,"k1":k1,"k2":k2,"market_hits":market_hits,"time_text":time_text,"market_state":market_state,"earnings_info":earnings_info})
    # 뉴스 1건을 수집 주기 끝까지 대기시키지 않는다. 등록 즉시 MASTER→포맷→Telegram 송출한다.
    try:
        _engine_flush_pending()
    except Exception as e:
        log_error("뉴스 즉시 MASTER/송출", e, source=source, title=title[:120])
    try:
        dt_mem = _engine_parse_datetime(published) or _now_kst()
        with _US_BRIEFING_LOCK:
            _US_BRIEFING_NEWS_MEMORY.append({"published_dt": dt_mem, "title": title, "text": f"{title} {extra}", "source": source})
            if len(_US_BRIEFING_NEWS_MEMORY) > 500:
                del _US_BRIEFING_NEWS_MEMORY[:-350]
    except Exception:
        pass
    _engine_log("info", "[후보] %s | 기업=%s | 재료=%s | %s", category, ",".join(companies[:3]) or "없음", ",".join(market_hits[:3]) or "없음", market_state)
    return True


def _engine_entry_published(entry):
    """RSS 발행시각을 최대한 안정적으로 복원한다. 문자열이 없어도 feedparser 구조화 날짜를 사용한다."""
    for key in ("published", "updated", "created", "pubDate", "date"):
        value = entry.get(key)
        if value:
            return value
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.datetime(*value[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                continue
    return ""

def _engine_fetch_rss(url, source):
    started = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT, allow_redirects=True)
        if not r.ok:
            _engine_log("error", "[실패] RSS | %s | 원인=%s", source, r.reason)
            return []
        result = feedparser.parse(r.content)
        if getattr(result, "bozo", False):
            _engine_log("warning", "[RSS 경고] %s | 일부 파싱 문제", source)
        entries = getattr(result, "entries", []) or []
        _engine_log("info", "[RSS] %s | 수집=%d건", source, len(entries))
        return entries
    except Exception as e:
        log_error("RSS 수집", e, source=source, url=url)
        return []


def _engine_run_google_and_domestic():
    total = 0
    if ENABLE_DOMESTIC_NEWS:
        for url in DOMESTIC_RSS_URLS:
            source = DOMESTIC_RSS_SOURCE_NAMES.get(url, "국내RSS")
            entries = _engine_fetch_rss(url, source)
            for e in entries[:50]:
                if _engine_process_item(source, e.get("title", ""), e.get("link", ""), _engine_entry_published(e), e.get("summary", "")):
                    total += 1
    else:
        _engine_log("warning", "[국내뉴스] ENABLE_DOMESTIC_NEWS=OFF")
    if ENABLE_US_NEWS:
        for url in US_RSS_URLS:
            entries = _engine_fetch_rss(url, "Google-US")
            for e in entries[:50]:
                if _engine_process_item("Google-US", e.get("title", ""), e.get("link", ""), _engine_entry_published(e), e.get("summary", "")):
                    total += 1
    _engine_log("info", "[Google/RSS 결과] 신규 전송=%d", total)
    if ENABLE_US_NEWS and total == 0:
        _engine_log("warning", "[Google 진단] RSS 수집은 되었지만 송출후보 0건이면 when:1h/최근60분/주가재료 조건을 확인")


_NAVER_RUNTIME_MODE = None
_NAVER_AUTH_FAILURE_LOGGED = set()

def _naver_credential_candidates():
    """
    NAVER 인증 방식을 자동 선택한다.

    1) NAVER_APIHUB_CLIENT_ID/SECRET가 있으면 NAVER API HUB를 먼저 사용한다.
    2) HUB가 401이고 NAVER_CLIENT_ID/SECRET가 별도로 있으면 구형 Search API로 재시도한다.

    핵심 수정: 구형 NAVER_CLIENT_*를 HUB 헤더에 억지로 넣지 않는다.
    이 혼용이 HUB에서 401을 만드는 대표적인 원인이다.
    """
    candidates = []
    if NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET:
        candidates.append((
            "hub",
            {
                "X-NCP-APIGW-API-KEY-ID": NAVER_APIHUB_CLIENT_ID,
                "X-NCP-APIGW-API-KEY": NAVER_APIHUB_CLIENT_SECRET,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            NAVER_APIHUB_BASE_URL + "/search/v1/news",
        ))
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        candidates.append((
            "legacy",
            {
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            NAVER_LEGACY_BASE_URL,
        ))
    return candidates


def _naver_credentials():
    """하위 호환용: 실제 사용 가능한 첫 인증쌍을 반환하되 서로 다른 쌍을 섞지 않는다."""
    candidates = _naver_credential_candidates()
    if not candidates:
        return "", ""
    mode, headers, _ = candidates[0]
    if mode == "hub":
        return NAVER_APIHUB_CLIENT_ID, NAVER_APIHUB_CLIENT_SECRET
    return NAVER_CLIENT_ID, NAVER_CLIENT_SECRET


def _naver_request_headers(mode=None):
    """요청 모드에 맞는 NAVER 인증 헤더/엔드포인트를 반환한다."""
    candidates = _naver_credential_candidates()
    if not candidates:
        return None, None, "missing-credentials"
    if mode:
        for candidate_mode, headers, endpoint in candidates:
            if candidate_mode == mode:
                return headers, endpoint, candidate_mode
        return None, None, "missing-credentials"
    candidate_mode, headers, endpoint = candidates[0]
    return headers, endpoint, candidate_mode


def _naver_mark_runtime_mode(mode):
    global _NAVER_RUNTIME_MODE
    _NAVER_RUNTIME_MODE = mode


def _naver_params(query, display):
    params = {"query": query, "display": display, "start": 1, "sort": "date"}
    # HUB는 format=json을 명시해도 되고, legacy는 기존 형식을 그대로 사용한다.
    return params


def _naver_api_status_log(status, mode):
    if status == 401:
        if mode == "hub":
            _engine_log("error", "[네이버 인증 실패] mode=HUB | HUB Client ID/Secret 또는 Application의 Search API 권한을 확인하세요.")
        else:
            _engine_log("error", "[네이버 인증 실패] mode=legacy | NAVER_CLIENT_ID/SECRET 또는 기존 Search API 권한을 확인하세요.")
    elif status == 403:
        _engine_log("error", "[네이버 호출 거부] mode=%s | HTTPS/요청경로/API 권한을 확인하세요.", mode)
    elif status == 429:
        _engine_log("error", "[네이버 호출한도] mode=%s | 일일 호출한도에 도달했습니다.", mode)
    else:
        _engine_log("error", "[네이버 오류] mode=%s | HTTP=%s", mode, status)


def _naver_request(mode, query, display):
    headers, endpoint, actual_mode = _naver_request_headers(mode)
    if not headers:
        return None, actual_mode
    params = _naver_params(query, display)
    if actual_mode == "hub":
        params["format"] = "json"
    response = requests.get(endpoint, headers=headers, params=params, timeout=ENGINE_HTTP_TIMEOUT)
    return response, actual_mode


def _engine_run_naver():
    if not ENABLE_NAVER_NEWS:
        _engine_log("warning", "[네이버] ENABLE_NAVER_NEWS=OFF")
        return
    candidates = _naver_credential_candidates()
    if not candidates:
        _engine_log("error", "[네이버 실패] 인증정보가 없습니다. HUB는 NAVER_APIHUB_CLIENT_ID/SECRET, legacy는 NAVER_CLIENT_ID/SECRET를 설정하세요.")
        return

    queries = list(dict.fromkeys(NAVER_SEARCH_QUERIES))
    batch_size = min(12, len(queries))
    cycle = getattr(_engine_run_naver, "cycle", 0)
    start = (cycle * batch_size) % max(1, len(queries))
    selected = [queries[(start+i) % len(queries)] for i in range(batch_size)] if queries else []
    _engine_run_naver.cycle = cycle + 1
    _engine_log("info", "[네이버] 검색 시작 전체검색어=%d | 이번주기=%d | offset=%d | 후보인증=%s", len(queries), len(selected), start, "/".join(m for m,_,_ in candidates))

    total = 0
    api_ok = True
    for q in selected:
        item_success = False
        last_status = None
        for mode, _, _ in candidates:
            try:
                r, actual_mode = _naver_request(mode, q, 50)
                if r is None:
                    continue
                if not r.ok:
                    last_status = r.status_code
                    _naver_api_status_log(r.status_code, actual_mode)
                    # 인증 실패면 다음 인증 방식으로만 1회 전환한다.
                    if r.status_code == 401:
                        continue
                    break
                _naver_mark_runtime_mode(actual_mode)
                items = _naver_extract_items(r)
                new_count = 0
                for item in items:
                    if _engine_process_item("네이버뉴스", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), item.get("description", "")):
                        new_count += 1
                        total += 1
                _engine_log("debug", "[네이버] mode=%s | %s | 검색=%d건 | 후보=%d", actual_mode, q, len(items), new_count)
                item_success = True
                break
            except Exception as e:
                log_error("네이버 뉴스 검색", e, query=q, mode=mode)
                break
        if not item_success and last_status == 401:
            api_ok = False

    _engine_log("info", "[네이버] 이번주기=%d개 검색 | 전송후보=%d | API=%s | runtime=%s", len(selected), total, "정상" if api_ok else "오류", _NAVER_RUNTIME_MODE or "없음")
    if api_ok and total == 0:
        _engine_log("warning", "[네이버 진단] API는 정상이나 송출후보 0건 | 최근60분/주가재료/중복 조건을 점검")


_NAVER_COMBO_INTERVAL = 300
_NAVER_COMBO_LAST_RUN = 0.0

def _engine_run_keyword_combinations():
    global _NAVER_COMBO_LAST_RUN
    now_ts = time.time()
    if now_ts - _NAVER_COMBO_LAST_RUN < _NAVER_COMBO_INTERVAL:
        return
    _NAVER_COMBO_LAST_RUN = now_ts
    candidates = _naver_credential_candidates()
    if not candidates:
        _engine_log("warning", "[키워드 조합] 네이버 API 인증정보가 없어 조합검색을 건너뜁니다.")
        return
    companies = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS))
    themes = ["HBM", "반도체", "AI", "로봇", "방산", "원전", "조선", "바이오", "이차전지", "ESS"]
    cycle = getattr(_engine_run_keyword_combinations, "cycle", 0)
    combos = [(c, themes[(cycle+i) % len(themes)]) for i, c in enumerate(companies[:10])]
    _engine_run_keyword_combinations.cycle = cycle + 1
    _engine_log("info", "[키워드 조합 시작] 이번주기=%d건 | 인증후보=%s", len(combos), "/".join(m for m,_,_ in candidates))

    for company, theme in combos:
        q = f'"{company}" {theme}'
        success = False
        for mode, _, _ in candidates:
            try:
                r, actual_mode = _naver_request(mode, q, 10)
                if r is None:
                    continue
                if not r.ok:
                    _naver_api_status_log(r.status_code, actual_mode)
                    if r.status_code == 401:
                        continue
                    break
                _naver_mark_runtime_mode(actual_mode)
                items = _naver_extract_items(r)
                new_count = 0
                for item in items:
                    if _engine_process_item("키워드조합", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), f"{q} {item.get('description', '')}"):
                        new_count += 1
                _engine_log("info", "[키워드 조합] mode=%s | %s | 결과=%d | 신규=%d", actual_mode, q, len(items), new_count)
                success = True
                break
            except Exception as e:
                log_error("키워드 조합 검색", e, query=q, mode=mode)
                break
        if not success:
            _engine_log("error", "[실패] 키워드조합 | %s | 모든 NAVER 인증경로 실패", q)

def _engine_run_dart():
    if not ENABLE_DART:
        _engine_log("warning", "[DART] ENABLE_DART=OFF")
        return
    if not DART_API_KEY:
        _engine_log("error", "[DART 실패] DART_API_KEY가 없습니다.")
        return
    try:
        today = _now_kst().strftime("%Y%m%d")
        url = "https://opendart.fss.or.kr/api/list.json"
        r = requests.get(url, params={"crtfc_key": DART_API_KEY, "bgn_de": today, "end_de": today, "page_no": 1, "page_count": 100}, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("error", "[DART 실패] HTTP=%s | reason=%s", r.status_code, r.reason)
            return
        data = r.json()
        if data.get("status") not in ("000", None):
            if data.get("status") == "013":
                _engine_log("info", "[DART] 오늘 공시 없음")
            else:
                _engine_log("error", "[DART 오류] status=%s | message=%s", data.get("status"), data.get("message"))
            return
        rows = data.get("list", []) or []
        _engine_log("info", "[DART] 오늘 공시=%d건", len(rows))
        sent = 0
        for row in rows:
            report = row.get("report_nm", "")
            if not any(k in report for k in DART_STRONG_REPORT_KEYWORDS):
                continue
            corp = row.get("corp_name", "")
            title = f"{corp} | {report}"
            link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no','')}"
            _schedule_add_dart_row(report, corp, link, row.get("rcept_dt", ""))
            if _engine_process_item("DART", title, link, row.get("rcept_dt", "")):
                sent += 1
        _engine_log("info", "[DART] 후보=%d건", sent)
    except Exception as e:
        log_error("DART 검사", e)


_ENGINE_BACKFILL_RUNNING = False
_ENGINE_BACKFILL_LOCK = threading.Lock()


def _engine_backfill_dart_range(bgn_de, end_de):
    """DART list.json은 corp_code 미지정 전체조회 시 조회기간(bgn_de~end_de)에
    최대 약 3개월 제한이 있어, 이 함수는 [bgn_de, end_de] 한 구간(<=90일)만 처리한다.
    페이지네이션으로 해당 구간의 전체 공시를 끝까지 순회한다."""
    recorded = 0
    page_no = 1
    while True:
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={"crtfc_key": DART_API_KEY, "bgn_de": bgn_de, "end_de": end_de,
                        "page_no": page_no, "page_count": 100},
                timeout=ENGINE_HTTP_TIMEOUT,
            )
        except Exception as e:
            log_error("DART 백필 요청", e, bgn_de=bgn_de, end_de=end_de, page_no=page_no)
            break
        if not r.ok:
            _engine_log("error", "[DART 백필 실패] HTTP=%s | %s~%s | page=%s", r.status_code, bgn_de, end_de, page_no)
            break
        data = r.json()
        status = data.get("status")
        if status == "013":
            break  # 해당 구간 공시 없음
        if status not in ("000", None):
            _engine_log("error", "[DART 백필 오류] status=%s | message=%s | %s~%s", status, data.get("message"), bgn_de, end_de)
            break
        rows = data.get("list", []) or []
        for row in rows:
            report = row.get("report_nm", "")
            if not any(k in report for k in DART_STRONG_REPORT_KEYWORDS):
                continue
            corp = row.get("corp_name", "")
            title = f"{corp} | {report}"
            link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no','')}"
            rcept_dt = row.get("rcept_dt", "")
            # 실시간 송출 파이프라인(_engine_process_item)을 타지 않고, 분류만 거쳐
            # 곧바로 과거DB에 적재한다(현재 시각과 무관하므로 60분 시간창 대상이 아님).
            ok, category, companies, k1, k2, market_hits = _engine_classify("DART", title, "")
            if not ok or not str(category or "").strip():
                continue
            item = {
                "title": title, "extra": "", "link": link,
                "published": rcept_dt, "companies": companies, "market_hits": market_hits,
                "market_state": "",
            }
            if _engine_record_historical_case(item):
                recorded += 1
        total_page = int(data.get("total_page") or 1)
        if page_no >= total_page:
            break
        page_no += 1
        time.sleep(0.2)  # DART API 호출 과다 방지
    return recorded


def _engine_backfill_dart_historical(days=365):
    """최근 `days`일치 DART 공시를 90일 단위로 나눠 순회하며 과거DB에 소급 적재한다.
    [주의] 네이버 뉴스검색 오픈API는 정렬(sort=date)만 지원하고 임의 과거 기간
    지정(ds/de) 자체를 지원하지 않아, 진짜 의미의 '몇 달~1년 전 뉴스 백필'은
    DART 공시처럼 기간 조회가 되는 소스에서만 가능하다. 뉴스 쪽은 지금 이 순간부터
    새로 쌓이는 실시간 수집으로 채워진다(위 시간게이트 분리 수정으로 이제 정상 적재됨).
    """
    if not DART_API_KEY:
        _engine_log("error", "[DART 백필 실패] DART_API_KEY가 없습니다.")
        return 0
    if not ENABLE_HISTORICAL_SURGE_DB:
        _engine_log("error", "[DART 백필 실패] ENABLE_HISTORICAL_SURGE_DB=OFF")
        return 0
    today = _now_kst().date()
    start = today - datetime.timedelta(days=max(1, int(days)))
    total_recorded = 0
    cursor = start
    while cursor <= today:
        chunk_end = min(today, cursor + datetime.timedelta(days=89))
        bgn_de = cursor.strftime("%Y%m%d")
        end_de = chunk_end.strftime("%Y%m%d")
        _engine_log("info", "[DART 백필] 구간 처리중 %s~%s", bgn_de, end_de)
        total_recorded += _engine_backfill_dart_range(bgn_de, end_de)
        cursor = chunk_end + datetime.timedelta(days=1)
    _engine_log("info", "[DART 백필] 완료 | 총 %d일 | 신규누적=%d건", days, total_recorded)
    return total_recorded


def _engine_run_telegram_channels():
    if not ENABLE_TELEGRAM_CHANNELS:
        _engine_log("warning", "[텔레그램] ENABLE_TELEGRAM_CHANNELS=OFF")
        return
    channels = TARGET_TELEGRAM_CHANNELS + TARGET_TELEGRAM_CHANNELS_UNFILTERED
    total = 0
    for name, url in channels:
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT)
            if not r.ok:
                _engine_log("error", "[텔레그램채널 실패] %s | HTTP=%s | reason=%s", name, r.status_code, r.reason)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.select("div.tgme_widget_message_wrap")[-10:]
            _engine_log("debug", "[텔레그램] %s | 확인=%d건", name, len(posts))
            for post in posts:
                a = post.select_one("a.tgme_widget_message_date")
                link = a.get("href", "") if a else url
                time_node = post.select_one("time")
                published = time_node.get("datetime", "") if time_node else ""
                # [본문오염방지] 조회수(views)/반응(reaction) 이모지/시간 등 메타데이터가
                # 본문 텍스트에 섞여 제목/요약으로 잘못 추출되는 것을 막는다.
                # 실제 메시지 텍스트 노드만 우선 사용하고, 못 찾을 때만 footer/reactions를
                # 제거한 사본에서 텍스트를 뽑는다(원본 post는 link/time 파싱에 그대로 사용).
                text_node = post.select_one("div.tgme_widget_message_text")
                if text_node:
                    txt = _engine_clean(text_node.get_text(" "))
                else:
                    clone = BeautifulSoup(str(post), "html.parser")
                    for junk_sel in (
                        "div.tgme_widget_message_footer",
                        "div.tgme_widget_message_reactions",
                        "div.tgme_widget_message_meta",
                        "span.tgme_widget_message_views",
                    ):
                        for junk in clone.select(junk_sel):
                            junk.decompose()
                    txt = _engine_clean(clone.get_text(" "))
                if not txt:
                    continue
                telegram_title, telegram_extra = _engine_telegram_title(txt, name)
                if not telegram_title:
                    _engine_log("info", "[제외] Telegram | 그로쓰리서치 특징주/속보 직접중계 차단 | source=%s", name)
                    continue
                # 제목만 title로 저장하고 원문은 요약 생성용 extra에만 둔다.
                if _engine_process_item(f"텔레그램/{name}", telegram_title, link, published, telegram_extra):
                    total += 1
        except Exception as e:
            log_error("텔레그램 채널 수집", e, channel=name, url=url)
    _engine_log("info", "[텔레그램] 확인 완료 | 후보=%d건", total)


_YOUTUBE_CHANNEL_ID_CACHE = {}
_YOUTUBE_CHANNEL_ID_CACHE_TS = {}


def _engine_youtube_channel_id(handle):
    """핸들/기존 ID를 실제 UC channel_id로 해석. HTML 구조 변화에 대비해 여러 단서를 사용."""
    h = str(handle or "").strip()
    if not h:
        return ""
    # 이미 UC channel ID인 경우 그대로 사용
    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", h):
        return h
    key = h.lstrip("@").strip()
    now_ts = time.time()
    cached = _YOUTUBE_CHANNEL_ID_CACHE.get(key)
    if cached and now_ts - _YOUTUBE_CHANNEL_ID_CACHE_TS.get(key, 0) < 24*3600:
        return cached

    urls = (
        f"https://www.youtube.com/@{key}",
        f"https://www.youtube.com/@{key}/videos",
        f"https://www.youtube.com/c/{key}",
        f"https://www.youtube.com/user/{key}",
    )
    patterns = [
        r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"browseId":"(UC[A-Za-z0-9_-]{20,})"',
        r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[A-Za-z0-9_-]{20,})',
        r'<link[^>]+itemprop=["\']url["\'][^>]+href=["\']https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
        r'https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
    ]
    for url in urls:
        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=ENGINE_HTTP_TIMEOUT,
                allow_redirects=True,
            )
            if not r.ok:
                continue
            body = r.text or ""
            for pat in patterns:
                m = re.search(pat, body, flags=re.I)
                if m:
                    cid = m.group(1)
                    _YOUTUBE_CHANNEL_ID_CACHE[key] = cid
                    _YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now_ts
                    return cid
            # canonical URL/og:url 보강
            soup = BeautifulSoup(body, "html.parser")
            for tag in soup.find_all(["link", "meta"]):
                val = tag.get("href") or tag.get("content") or ""
                m = re.search(r"/channel/(UC[A-Za-z0-9_-]{20,})", str(val))
                if m:
                    cid = m.group(1)
                    _YOUTUBE_CHANNEL_ID_CACHE[key] = cid
                    _YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now_ts
                    return cid
        except Exception:
            continue
    return ""


def _engine_run_youtube():
    if not ENABLE_YOUTUBE:
        _engine_log("warning", "[유튜브] ENABLE_YOUTUBE=OFF"); return
    total = 0
    ok_channels = 0
    fail_channels = 0
    for name, handle in YOUTUBE_CHANNELS:
        cid = _engine_youtube_channel_id(handle)
        if not cid:
            fail_channels += 1
            _engine_log("error", "[유튜브 실패] 채널 확인 불가 | %s", name)
            continue
        ok_channels += 1
        entries = _engine_fetch_rss(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", f"유튜브/{name}")
        for e in entries[:10]:
            title = e.get("title", "")
            desc = e.get("summary", "") or e.get("description", "")
            published = _engine_entry_published(e)
            if _engine_process_item(f"유튜브/{name}", title, e.get("link", ""), published, desc): total += 1
    _engine_log("info", "[유튜브 완료] 채널=%d/%d 성공 | 실패=%d | 신규후보=%d", ok_channels, len(YOUTUBE_CHANNELS), fail_channels, total)


# ============================================================
# ============================================================
# 🇰🇷 국내장 장중 브리핑 + 실행 자가진단
# - 09:30 첫 브리핑, 이후 30분 슬롯
# - 지수/원달러/핵심 대형주 변화가 기준을 넘으면 장중 변동 브리핑
# - Yahoo 시세 실패 시 조용히 죽지 않고 다음 1분 주기에 재시도
# ============================================================
ENABLE_DOMESTIC_INTRADAY_BRIEFING = _env_flag("ENABLE_DOMESTIC_INTRADAY_BRIEFING", True)
KRX_OPEN_BRIEF_DELAY_MIN = 30
KRX_POLL_MIN = 5
KRX_STOCK_MOVE_THRESHOLD = 2.5
KRX_INDEX_MOVE_THRESHOLD = 0.7
KRX_WATCHLIST = {
    "^KS11": ("코스피", "지수"), "^KQ11": ("코스닥", "지수"),
    "005930.KS": ("삼성전자", "반도체"), "000660.KS": ("SK하이닉스", "HBM"),
    "373220.KS": ("LG에너지솔루션", "2차전지"), "207940.KS": ("삼성바이오로직스", "바이오"),
    "005380.KS": ("현대차", "자동차"), "000270.KS": ("기아", "자동차"),
    "012450.KS": ("한화에어로스페이스", "방산"), "042660.KS": ("한화오션", "조선"),
    "035420.KS": ("NAVER", "인터넷"), "035720.KS": ("카카오", "인터넷"),
    "USDKRW=X": ("원/달러", "환율"),
}
_KRX_BRIEFING_LAST_SNAPSHOT = {}
_KRX_BRIEFING_LAST_POLL = None

def _krx_briefing_fetch_all():
    data = {}
    for symbol, meta in KRX_WATCHLIST.items():
        q = _yahoo_chart_quote(symbol)
        if q:
            q.update({"name": meta[0], "theme": meta[1]})
            data[symbol] = q
    return data

def _krx_intraday_events(snapshot):
    events=[]
    for symbol,q in snapshot.items():
        pct=q.get("change_pct")
        old=_KRX_BRIEFING_LAST_SNAPSHOT.get(symbol)
        if pct is None or not old or old.get("change_pct") is None:
            continue
        delta=pct-old["change_pct"]
        threshold=KRX_INDEX_MOVE_THRESHOLD if symbol in {"^KS11","^KQ11"} else KRX_STOCK_MOVE_THRESHOLD
        if symbol == "USDKRW=X": threshold=1.0
        if abs(delta)>=threshold: events.append((abs(delta),symbol,q,delta))
    return sorted(events, reverse=True, key=lambda x:x[0])

def _krx_briefing_message(snapshot, et, events=None, opening=False):
    events=events or []
    lines=["<b>🇰🇷 [국내장 브리핑]</b>", f"🕐 {et.strftime('%H:%M KST')}", ""]
    lines.append("<b>📊 주요 지수</b>")
    for s in ("^KS11","^KQ11"):
        q=snapshot.get(s)
        if q: lines.append(f"• {_us_display_name(s, q['name'])} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")
    lines += ["", "<b>⚡️ 주요 종목 변화</b>"]
    rows=[]
    for s,q in snapshot.items():
        if s in {"^KS11","^KQ11","USDKRW=X"}: continue
        if q.get("change_pct") is not None: rows.append(q)
    rows.sort(key=lambda x:abs(x.get("change_pct") or 0), reverse=True)
    shown=0
    for q in rows[:8]:
        pct=q.get("change_pct")
        if abs(pct or 0)<1.0: continue
        lines.append(f"• ⚡️ {q['name']} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}")
        shown+=1
    if not shown: lines.append("• 주요 종목 큰 변동 없음")
    fx=snapshot.get("USDKRW=X")
    if fx: lines += ["", f"<b>💱 원/달러</b> · {_us_format_pct(fx.get('change_pct'))}"]
    if events:
        lines += ["", "<b>🚨 장중 구조 변화</b>"]
        for _,_,q,delta in events[:5]:
            lines.append(f"• ⚡️ {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q.get('change_pct'))}")
    return "\n".join(lines)

def _engine_krx_market_monitor():
    global _KRX_BRIEFING_LAST_SNAPSHOT, _KRX_BRIEFING_LAST_POLL
    if not ENABLE_DOMESTIC_INTRADAY_BRIEFING: return
    now=_now_kst()
    if now.weekday()>=5 or now.strftime('%Y-%m-%d') in KRX_HOLIDAYS_2026: return
    if not (datetime.time(9,0) <= now.time() < datetime.time(15,31)): return
    if _KRX_BRIEFING_LAST_POLL is not None and (now-_KRX_BRIEFING_LAST_POLL).total_seconds()<KRX_POLL_MIN*60: return
    _KRX_BRIEFING_LAST_POLL=now
    snapshot=_krx_briefing_fetch_all()
    if not snapshot:
        _engine_log("warning","[국내장브리핑] 시세 조회 실패 | 다음 주기에 자동 재시도")
        return
    minutes=(now.hour*60+now.minute)-(9*60)
    if minutes<KRX_OPEN_BRIEF_DELAY_MIN:
        _KRX_BRIEFING_LAST_SNAPSHOT=snapshot; return
    slot=minutes//30
    key=f"{now.date().isoformat()}-{slot}"
    if getattr(_engine_krx_market_monitor,"_last_slot_key",None)==key:
        _KRX_BRIEFING_LAST_SNAPSHOT=snapshot; return
    events=_krx_intraday_events(snapshot)
    # 첫 30분은 정기 브리핑, 이후에는 변화가 있으면 즉시/슬롯 브리핑
    if slot==1: msg=_krx_briefing_message(snapshot,now,opening=True)
    elif events: msg=_krx_briefing_message(snapshot,now,events=events)
    else: msg=_krx_briefing_message(snapshot,now) if slot%1==0 else ""
    if msg and _engine_send_telegram(msg):
        _engine_krx_market_monitor._last_slot_key=key
        _engine_log("info","[국내장브리핑] 송출 완료 | slot=%s | 변동=%d",key,len(events))
    _KRX_BRIEFING_LAST_SNAPSHOT=snapshot

# 🇺🇸 미국장 30분 브리핑 + 장중 변동 감시
# ------------------------------------------------------------
# 원칙
# 1) 정규장 개장(09:30 ET) 후 30분이 지나면 1회 브리핑.
# 2) 이후 급등/급락·테마 강세·개별종목 급변·유가·환율 등
#    시장 구조가 바뀔 때만 장중 브리핑.
# 3) 기존 뉴스의 국내 관련주 선별 로직은 건드리지 않는다.
# 4) 글로벌 기업은 국내 상장기업으로 오인 연결하지 않는다.
# 5) "👍 강한 재료 · 급락" 같은 방향/강도 혼합 문구를 사용하지 않는다.
#    방향은 📈 급등 / 📉 급락으로, 재료 강도는 뉴스 분류에서 별도로 처리한다.
# 6) 실시간 시세가 확인되지 않으면 추정하지 않고 "시세 확인불가"로 남긴다.
# ============================================================
US_OPEN_BRIEF_DELAY_MIN = 30
US_INTRADAY_POLL_MIN = 5
US_INTRADAY_COOLDOWN_MIN = 20
US_STOCK_MOVE_THRESHOLD = 3.0
US_INDEX_MOVE_THRESHOLD = 1.0
US_MACRO_MOVE_THRESHOLD = 1.5
US_SECTOR_MOVE_THRESHOLD = 2.0

US_BRIEFING_WATCHLIST = {
    # 핵심 지수/시장
    "^IXIC": ("나스닥", "지수"),
    "^GSPC": ("S&P500", "지수"),
    "^DJI": ("다우", "지수"),
    "^RUT": ("러셀2000", "지수"),
    "^SOX": ("필라델피아반도체", "반도체"),
    "^VIX": ("VIX", "변동성"),
    "URTH": ("MSCI World", "MSCI"),
    # 매크로
    "USDKRW=X": ("원/달러", "환율"),
    "CL=F": ("WTI", "에너지"),
    "GC=F": ("금", "원자재"),
    # 섹터 ETF
    "SOXX": ("반도체 ETF", "반도체"),
    "XLK": ("기술주 ETF", "기술"),
    "XLE": ("에너지 ETF", "에너지"),
    "XLI": ("산업재 ETF", "산업재"),
    "ITA": ("방산 ETF", "방산"),
    "XBI": ("바이오 ETF", "바이오"),
    "XLF": ("금융 ETF", "금융"),
    # 개별 핵심주
    "NVDA": ("엔비디아", "AI·반도체"),
    "AMD": ("AMD", "AI·반도체"),
    "AVGO": ("브로드컴", "AI·반도체"),
    "MU": ("마이크론", "메모리·HBM"),
    "TSM": ("TSMC", "반도체"),
    "AAPL": ("애플", "빅테크"),
    "MSFT": ("마이크로소프트", "AI·클라우드"),
    "AMZN": ("아마존", "빅테크"),
    "META": ("메타", "AI·플랫폼"),
    "GOOGL": ("알파벳", "AI·플랫폼"),
    "TSLA": ("테슬라", "전기차·로봇"),
    "PLTR": ("팔란티어", "AI"),
    "ARM": ("ARM", "반도체"),
    "INTC": ("인텔", "반도체"),
}

_US_BRIEFING_LAST_RUN_DATE = None
_US_BRIEFING_LAST_OPEN_SENT = None
_US_BRIEFING_LAST_INTRADAY_SENT = None
_US_BRIEFING_LAST_SNAPSHOT = {}
_US_BRIEFING_LAST_EVENT = {}
_US_BRIEFING_LAST_POLL = None
_US_BRIEFING_NEWS_MEMORY = []
_US_BRIEFING_LOCK = threading.Lock()


def _us_market_now_et():
    if ZoneInfo is None:
        return None
    return _now_kst().replace(tzinfo=_KST).astimezone(ZoneInfo("America/New_York"))


def _us_market_is_holiday(d):
    # 2026 Nasdaq/NYSE 휴장일. 정규장 09:30 ET 기준으로만 사용한다.
    holidays = {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    }
    return d.strftime("%Y-%m-%d") in holidays


def _us_market_session_open(et=None):
    et = et or _us_market_now_et()
    if et is None:
        return False
    if et.weekday() >= 5 or _us_market_is_holiday(et.date()):
        return False
    return datetime.time(9, 30) <= et.time() < datetime.time(16, 0)


def _yahoo_chart_quote(symbol, interval="5m", range_="1d"):
    """Yahoo chart endpoint에서 현재가/전일종가/장중 데이터를 안전하게 읽는다."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = requests.get(
            url,
            params={"range": range_, "interval": interval, "includePrePost": "false"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if not r.ok:
            return None
        data = r.json().get("chart", {}).get("result", [])
        if not data:
            return None
        result = data[0]
        meta = result.get("meta", {}) or {}
        ts = result.get("timestamp", []) or []
        quote = (result.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        closes = quote.get("close", []) or []
        valid = [(t, c) for t, c in zip(ts, closes) if c is not None]
        if not valid:
            return None
        last_ts, last_price = valid[-1]
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        regular_price = meta.get("regularMarketPrice")
        price = float(regular_price or last_price)
        prev = float(previous_close) if previous_close is not None else None
        day_open = None
        opens = quote.get("open", []) or []
        for o in opens:
            if o is not None:
                day_open = float(o)
                break
        change_pct = ((price - prev) / prev * 100.0) if prev else None
        open_pct = ((price - day_open) / day_open * 100.0) if day_open else None
        return {
            "symbol": symbol,
            "price": price,
            "previous_close": prev,
            "day_open": day_open,
            "change_pct": change_pct,
            "open_pct": open_pct,
            "timestamp": last_ts,
        }
    except Exception as e:
        _engine_log("warning", "[미장시세] %s | 확인 실패=%s", symbol, str(e)[:100])
        return None


def _kr_yahoo_quote(stock_code):
    """국내 종목코드(6자리)로 Yahoo chart 시세를 조회한다.
    코스피(.KS)를 먼저 시도하고 실패하면 코스닥(.KQ)으로 재시도한다."""
    stock_code = str(stock_code or "").strip()
    if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
        return None
    for suffix in (".KS", ".KQ"):
        q = _yahoo_chart_quote(f"{stock_code}{suffix}")
        if q and q.get("price") is not None:
            return q
    return None


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


def _us_briefing_reason(name, theme):
    """최근 수집 뉴스에서 실제 언급된 원인을 찾는다. 없으면 추정하지 않는다."""
    now = _now_kst()
    candidates = []
    with _US_BRIEFING_LOCK:
        memory = list(_US_BRIEFING_NEWS_MEMORY)
    needles = [name, theme]
    alias = {
        "엔비디아": ["엔비디아", "NVIDIA", "NVDA"],
        "마이크론": ["마이크론", "Micron", "MU"],
        "브로드컴": ["브로드컴", "Broadcom", "AVGO"],
        "TSMC": ["TSMC", "Taiwan Semiconductor"],
        "AMD": ["AMD"],
        "테슬라": ["테슬라", "Tesla", "TSLA"],
        "팔란티어": ["팔란티어", "Palantir", "PLTR"],
        "알파벳": ["구글", "알파벳", "Alphabet", "Google"],
    }
    needles.extend(alias.get(name, []))
    for row in reversed(memory):
        dt = row.get("published_dt")
        if dt is not None and (now - dt).total_seconds() > 180 * 60:
            continue
        text = row.get("text", "")
        if any(n.lower() in text.lower() for n in needles if n):
            candidates.append(row)
    if not candidates:
        return ""
    return candidates[0].get("title", "")[:180]


def _us_briefing_fetch_all():
    data = {}
    for symbol, meta in US_BRIEFING_WATCHLIST.items():
        q = _yahoo_chart_quote(symbol)
        if q:
            q.update({"name": meta[0], "theme": meta[1]})
            data[symbol] = q
    return data


US_TICKER_NAME = {
    "NVDA": "엔비디아", "AMD": "AMD", "AVGO": "브로드컴", "MU": "마이크론",
    "TSM": "TSMC", "AAPL": "애플", "MSFT": "마이크로소프트", "AMZN": "아마존",
    "META": "메타", "GOOGL": "알파벳", "TSLA": "테슬라", "PLTR": "팔란티어",
    "ARM": "암 홀딩스", "INTC": "인텔",
}

def _us_display_name(symbol, name):
    base = US_TICKER_NAME.get(symbol, name)
    if symbol in US_TICKER_NAME:
        return f"{base} ({symbol})"
    return name

def _us_direction(pct):
    if pct is None:
        return ""
    return "🔺" if pct >= 0 else "▼"


def _us_format_pct(pct):
    if pct is None:
        return "시세 확인불가"
    return f"{pct:+.2f}%"


def _us_open_briefing(snapshot, et):
    indices = ["^IXIC", "^GSPC", "^DJI", "^SOX", "^VIX"]
    macro = ["USDKRW=X", "CL=F", "GC=F"]
    lines = [
        "<b>🇺🇸 [미장 브리핑]</b>",
        f"🕐 {et.strftime('%H:%M ET')}",
        "",
        "<b>📊 주요 지수</b>",
    ]
    for s in indices:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {_us_display_name(s, q['name'])} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")
    movers = []
    for s, q in snapshot.items():
        if s in indices or s in macro:
            continue
        if q.get("change_pct") is not None:
            movers.append(q)
    movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    lines += ["", "<b>🔥 강한 종목/테마</b>"]
    for q in movers[:6]:
        pct = q.get("change_pct")
        if pct is None or abs(pct) < 1.0:
            continue
        reason = _us_briefing_reason(q["name"], q["theme"])
        line = f"• {_us_display_name(s, q['name'])} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}"
        if reason:
            line += f" · 원인: {html.escape(reason)}"
        lines.append(line)
    lines += ["", "<b>🛢️ 환율·원자재</b>"]
    for s in macro:
        q = snapshot.get(s)
        if q:
            pct = q.get("change_pct")
            lines.append(f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)}")

    # 미국장 개장 30분 브리핑에도 국내 시장 대응용 ADR을 반드시 포함한다.
    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX", "LPL", "KEP", "KB", "SHG", "SKM"]
    found_adr = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found_adr = True
            pct = q.get("change_pct")
            lines.append(f"• {html.escape(q.get('name', s))} {_us_direction(pct)} {_us_format_pct(pct)}")
    if not found_adr:
        lines.append("• ADR 시세 확인불가")

    lines += ["", "<b>📊 MSCI</b>"]
    msci_quote = snapshot.get("URTH")
    if msci_quote:
        pct = msci_quote.get("change_pct")
        lines.append(f"• {html.escape(msci_quote.get('name', 'MSCI World'))} {_us_direction(pct)} {_us_format_pct(pct)}")
    else:
        lines.append("• MSCI 시세 확인불가")

    # 신규 MSCI 재료가 있으면 원문 링크까지, 없으면 확인 결과를 명시한다.
    msci = {}
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        tx = str(row.get("text", ""))
        if any(k.lower() in tx.lower() for k in ["MSCI", "리밸런싱", "지수 편입", "지수 편출"]):
            msci = row
            break
    lines += ["", "<b>📌 MSCI</b>"]
    if msci:
        lines.append(f"• {html.escape(str(msci.get('title', ''))[:220])}")
        if msci.get("link"):
            link = html.escape(str(msci["link"]), quote=True)
            lines.append(f'<a href="{link}">🔗 MSCI 관련 원문</a>')
    else:
        lines.append("• 확인된 신규 MSCI 재료 없음")

    return "\n".join(lines)


def _us_intraday_events(snapshot):
    """직전 스냅샷 대비 시장 구조가 달라진 항목만 반환."""
    global _US_BRIEFING_LAST_SNAPSHOT
    events = []
    for symbol, q in snapshot.items():
        pct = q.get("change_pct")
        if pct is None:
            continue
        old = _US_BRIEFING_LAST_SNAPSHOT.get(symbol)
        if not old:
            continue
        old_pct = old.get("change_pct")
        if old_pct is None:
            continue
        delta = pct - old_pct
        if symbol in {"^IXIC", "^GSPC", "^DJI", "^RUT", "^SOX", "^VIX"}:
            threshold = US_INDEX_MOVE_THRESHOLD
        elif symbol in {"USDKRW=X", "CL=F", "GC=F"}:
            threshold = US_MACRO_MOVE_THRESHOLD
        elif symbol in {"SOXX", "XLK", "XLE", "XLI", "ITA", "XBI", "XLF"}:
            threshold = US_SECTOR_MOVE_THRESHOLD
        else:
            threshold = US_STOCK_MOVE_THRESHOLD
        if abs(delta) >= threshold:
            events.append((abs(delta), symbol, q, delta))
    events.sort(reverse=True, key=lambda x: x[0])
    return events


def _us_intraday_briefing(snapshot, events, et):
    lines = [
        "<b>🌐 [미장 장중 브리핑]</b>",
        f"🕐 {et.strftime('%H:%M ET')}",
        "",
    ]
    sector_moves = []
    stock_moves = []
    macro_moves = []
    for _, symbol, q, delta in events[:12]:
        if symbol in {"USDKRW=X", "CL=F", "GC=F"}:
            macro_moves.append((symbol, q, delta))
        elif symbol in {"SOXX", "XLK", "XLE", "XLI", "ITA", "XBI", "XLF"}:
            sector_moves.append((symbol, q, delta))
        elif symbol.startswith("^"):
            sector_moves.append((symbol, q, delta))
        else:
            stock_moves.append((symbol, q, delta))

    if sector_moves:
        lines.append("<b>📌 시장·테마 변화</b>")
        for _, q, delta in sector_moves[:5]:
            lines.append(f"• {q['name']} {_us_direction(delta)} 단기변화 {delta:+.2f}% · 현재 {q['change_pct']:+.2f}%")
        lines.append("")
    if stock_moves:
        lines.append("<b>📈📉 개별종목 변화</b>")
        for _, symbol, q, delta in [(abs(d), s, q, d) for _, s, q, d in stock_moves[:6]]:
            reason = _us_briefing_reason(q["name"], q["theme"])
            line = f"• {q['name']} {_us_direction(delta)} 단기변화 {delta:+.2f}% · 현재 {q['change_pct']:+.2f}% · {q['theme']}"
            if reason:
                line += f" · 원인: {html.escape(reason)}"
            else:
                line += " · 원인: 확인된 뉴스 없음"
            lines.append(line)
        lines.append("")
    if macro_moves:
        lines.append("<b>🛢️ 환율·원자재 변화</b>")
        for _, q, delta in macro_moves:
            lines.append(f"• {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q['change_pct'])}")
        lines.append("")
    if not events:
        return ""
    lines.append("※ 방향(급등/급락)과 재료 강도는 별도로 표기하며, 시세만으로 국내 관련주를 강제 연결하지 않습니다.")
    return "\n".join(lines)


def _engine_us_market_monitor():
    """미국 정규장 동안 30분 슬롯마다 브리핑. 첫 슬롯은 10:00 ET."""
    global _US_BRIEFING_LAST_RUN_DATE, _US_BRIEFING_LAST_OPEN_SENT
    global _US_BRIEFING_LAST_INTRADAY_SENT, _US_BRIEFING_LAST_SNAPSHOT, _US_BRIEFING_LAST_POLL
    if not ENABLE_US_INTRADAY_BRIEFING or ZoneInfo is None:
        return
    et = _us_market_now_et()
    if et is None or not _us_market_session_open(et):
        return

    now = _now_kst()
    # 시세는 5분마다 조회하되, 브리핑은 30분 슬롯마다 정확히 1회.
    if _US_BRIEFING_LAST_POLL is not None:
        if (now - _US_BRIEFING_LAST_POLL).total_seconds() < US_INTRADAY_POLL_MIN * 60:
            return
    _US_BRIEFING_LAST_POLL = now

    snapshot = _us_briefing_fetch_all()
    if not snapshot:
        _engine_log("warning", "[미장브리핑] 실시간 시세를 가져오지 못함")
        return

    # 09:30 개장 후 30분이 지난 10:00 ET부터 30분 단위.
    minutes_from_open = int((et.hour * 60 + et.minute) - (9 * 60 + 30))
    if minutes_from_open < US_OPEN_BRIEF_DELAY_MIN:
        _US_BRIEFING_LAST_SNAPSHOT = snapshot
        return

    slot_index = minutes_from_open // 30
    slot_key = f"{et.date().isoformat()}-{slot_index}"
    if getattr(_engine_us_market_monitor, "_last_slot_key", None) == slot_key:
        _US_BRIEFING_LAST_SNAPSHOT = snapshot
        return

    # 첫 슬롯은 개장 브리핑, 그 이후는 직전 5분 스냅샷 대비 구조 변화가 있을 때만 장중 브리핑.
    if slot_index == 1:
        msg = _us_open_briefing(snapshot, et)
    else:
        events = _us_intraday_events(snapshot)
        msg = _us_intraday_briefing(snapshot, events, et)
        if not msg:
            _US_BRIEFING_LAST_SNAPSHOT = snapshot
            return
    if msg and _engine_send_telegram(msg):
        _engine_us_market_monitor._last_slot_key = slot_key
        _US_BRIEFING_LAST_OPEN_SENT = et.date() if slot_index == 1 else _US_BRIEFING_LAST_OPEN_SENT
        _US_BRIEFING_LAST_INTRADAY_SENT = now
        _engine_log("info", "[미장브리핑] %s 송출 | slot=%s", "개장30분" if slot_index == 1 else "장중변동", slot_key)
    _US_BRIEFING_LAST_SNAPSHOT = snapshot


# ============================================================
# 🇺🇸 미국장 마감 브리핑
# ============================================================
ENABLE_US_CLOSE_BRIEFING = _env_flag("ENABLE_US_CLOSE_BRIEFING", True)
US_CLOSE_BRIEF_DELAY_MIN = int(os.environ.get("US_CLOSE_BRIEF_DELAY_MIN", "5"))
_US_CLOSE_BRIEF_LAST_SENT = None

def _us_close_reason(name, theme):
    """최근 24시간 수집 뉴스에서 확인된 원인만 반환. 없으면 추정하지 않는다."""
    now = _now_kst()
    needles = [str(name or ""), str(theme or "")]
    aliases = {
        "엔비디아": ["NVIDIA", "NVDA", "엔비디아"],
        "마이크론": ["Micron", "MU", "마이크론"],
        "브로드컴": ["Broadcom", "AVGO", "브로드컴"],
        "TSMC": ["TSMC", "Taiwan Semiconductor"],
        "AMD": ["AMD"],
        "테슬라": ["Tesla", "TSLA", "테슬라"],
        "팔란티어": ["Palantir", "PLTR", "팔란티어"],
        "알파벳": ["Alphabet", "Google", "구글", "알파벳"],
    }
    needles += aliases.get(name, [])
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        dt = row.get("published_dt")
        try:
            if dt and (now - dt).total_seconds() > 24 * 3600:
                continue
        except Exception:
            pass
        tx = str(row.get("text", ""))
        if any(n and n.lower() in tx.lower() for n in needles):
            return row
    return {}

def _us_close_rank_themes(snapshot):
    """섹터 ETF와 주요 종목을 테마별로 묶어 실제 움직임을 기준으로 순위화."""
    excluded = {"^IXIC","^GSPC","^DJI","^RUT","^SOX","^VIX","USDKRW=X","CL=F","GC=F"}
    groups = {}
    for symbol, q in snapshot.items():
        if symbol in excluded or q.get("change_pct") is None:
            continue
        theme = str(q.get("theme","")).strip()
        if not theme:
            continue
        g = groups.setdefault(theme, [])
        g.append(q)
    ranked = []
    for theme, qs in groups.items():
        avg = sum(float(q.get("change_pct") or 0) for q in qs) / max(1, len(qs))
        breadth = sum(1 if (q.get("change_pct") or 0) > 1 else -1 if (q.get("change_pct") or 0) < -1 else 0 for q in qs)
        max_abs = max((abs(q.get("change_pct") or 0) for q in qs), default=0)
        score = avg + breadth * 0.35 + max_abs * 0.15
        ranked.append((score, theme, qs))
    return sorted(ranked, reverse=True, key=lambda x: x[0])

def _us_extract_past_move(row):
    """과거 사례 텍스트에 명시된 실제 상승/하락률만 추출."""
    if not row:
        return ""
    tx = str(row.get("text","")) + " " + str(row.get("title",""))
    ms = re.findall(r"(?:\+|-)?\d+(?:\.\d+)?\s*%", tx)
    return ms[0] if ms else ""

def _us_close_briefing(snapshot, et):
    lines = [
        "<b>🌐 [미장 마감 브리핑]</b>",
        f"🕐 {et.strftime('%Y-%m-%d %H:%M ET')} · 정규장 마감",
        "",
        "<b>📊 전체 시장 흐름</b>",
    ]
    for s in ["^IXIC","^GSPC","^DJI","^RUT","^SOX","^VIX"]:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")

    ranked = _us_close_rank_themes(snapshot)
    if ranked:
        lines += ["", "<b>🔥 오늘의 강한 종목군·테마</b>"]
        for _, theme, qs in ranked[:4]:
            members = sorted(qs, key=lambda q: abs(q.get("change_pct") or 0), reverse=True)[:4]
            member_text = " · ".join(f"{html.escape(_us_display_name(next((sym for sym, qq in snapshot.items() if qq is q), ""), q['name']))} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}" for q in members)
            lines.append(f"• <b>{html.escape(theme)}</b> · {member_text}")

            lead = members[0] if members else {}
            reason = _us_close_reason(lead.get("name",""), theme)
            if reason:
                rtitle = html.escape(str(reason.get("title",""))[:220])
                lines.append(f"  ↳ 움직인 이유: {rtitle}")
            else:
                lines.append("  ↳ 움직인 이유: 확인된 뉴스 없음")

            # 관련주/테마 판단은 MASTER에서만 수행한다.

            # 유사 과거 사례: 실제 수익률과 링크가 DB에 있을 때만 표시.
            if reason:
                past = _engine_historical_cache[-3000:]
                best = None
                cur = str(reason.get("title",""))
                for h in past:
                    old = str(h.get("text",""))
                    ratio = difflib.SequenceMatcher(
                        None,
                        re.sub(r"[^0-9a-zA-Z가-힣]","",cur.lower())[:220],
                        re.sub(r"[^0-9a-zA-Z가-힣]","",old.lower())[:220]
                    ).ratio()
                    if ratio >= HISTORICAL_MATCH_THRESHOLD and (best is None or ratio > best[0]):
                        best = (ratio,h)
                if best:
                    h = best[1]
                    pct = _us_extract_past_move(h)
                    htitle = html.escape(str(h.get("title","과거 유사 사례"))[:180])
                    link = html.escape(str(h.get("link","")), quote=True)
                    label = f"과거 실제 반응 {pct}" if pct else "과거 유사 사례"
                    lines.append(f"  📚 {label}")
                    if link:
                        lines.append(f'  <a href="{link}">🔗 과거 사례 원문</a>')
                    else:
                        lines.append(f"  {htitle}")

    lines += ["", "<b>🛢️ 환율·유가·금</b>"]
    for s in ["USDKRW=X","CL=F","GC=F"]:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")

    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX","LPL","KEP","KB","SHG","SKM"]
    found = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found = True
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")
    if not found:
        lines.append("• ADR 시세 확인불가")

    lines += ["", "<b>📊 MSCI</b>"]
    msci_quote = snapshot.get("URTH")
    if msci_quote:
        pct = msci_quote.get("change_pct")
        lines.append(f"• {html.escape(msci_quote.get('name', 'MSCI World'))} {_us_direction(pct)} {_us_format_pct(pct)}")
    else:
        lines.append("• MSCI 시세 확인불가")

    msci = {}
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        tx = str(row.get("text",""))
        if any(k.lower() in tx.lower() for k in ["MSCI","리밸런싱","지수 편입","지수 편출"]):
            msci = row
            break
    lines += ["", "<b>📌 MSCI</b>"]
    if msci:
        lines.append(f"• {html.escape(str(msci.get('title',''))[:220])}")
        if msci.get("link"):
            link = html.escape(str(msci["link"]), quote=True)
            lines.append(f'<a href="{link}">🔗 MSCI 관련 원문</a>')
    else:
        lines.append("• 확인된 신규 MSCI 재료 없음")

    # 강한 재료는 재료 강도만 표시. 방향(급등/급락)을 붙이지 않는다.
    strong_rows = []
    for row in reversed(rows[-300:]):
        tx = str(row.get("title","")) + " " + str(row.get("text",""))
        if any(k in tx.lower() for k in ["계약 체결","공급계약","대규모 수주","수주 확정","승인","허가","사상 최대","대규모 투자"]):
            strong_rows.append(row)
            if len(strong_rows) >= 3:
                break
    if strong_rows:
        lines += ["", "<b>👍 강한 재료</b>"]
        for row in strong_rows:
            tx = str(row.get("title",""))[:220]
            amount = re.search(r"(?:[0-9][0-9,]*(?:\.\d+)?)\s*(?:억|조|억원|조원|달러|USD|million|billion)", tx, re.I)
            suffix = f" · 금액 {amount.group(0)}" if amount else ""
            lines.append(f"• {html.escape(tx)}{html.escape(suffix)}")
            if row.get("link"):
                lines.append(f'<a href="{html.escape(str(row["link"]), quote=True)}">🔗 원문</a>')

    return "\n".join(lines)

def _engine_us_market_close_monitor():
    global _US_CLOSE_BRIEF_LAST_SENT
    if not ENABLE_US_CLOSE_BRIEFING or ZoneInfo is None:
        return
    et = _us_market_now_et()
    if et is None or et.weekday() >= 5 or _us_market_is_holiday(et.date()):
        return
    close_dt = datetime.datetime.combine(et.date(), datetime.time(16,0))
    if et.replace(tzinfo=None) < close_dt + datetime.timedelta(minutes=US_CLOSE_BRIEF_DELAY_MIN):
        return
    if _US_CLOSE_BRIEF_LAST_SENT == et.date():
        return
    snapshot = _us_briefing_fetch_all()
    if not snapshot:
        return
    msg = _us_close_briefing(snapshot, et)
    if msg and _engine_send_telegram(msg):
        _US_CLOSE_BRIEF_LAST_SENT = et.date()
        _engine_log("info", "[미장마감] 장마감 브리핑 송출 완료")


def _engine_cycle():
    global _engine_last_cycle_started, _engine_last_cycle_finished
    if _engine_paused:
        _engine_log("info", "[주기 건너뜀] 관리자 명령으로 일시정지 상태")
        return
    started = time.time()
    _engine_last_cycle_started = started
    _engine_log("info", "[주기 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        _engine_run_google_and_domestic()
    except Exception as e:
        log_error("국내/Google RSS 전체", e)
    try:
        _engine_retry_translation_queue()
    except Exception as e:
        log_error("번역 재시도 큐", e)
    try:
        _engine_run_naver()
    except Exception as e:
        log_error("네이버 전체", e)
    try:
        _engine_run_keyword_combinations()
    except Exception as e:
        log_error("키워드 조합 전체", e)
    try:
        _engine_run_dart()
    except Exception as e:
        log_error("DART 전체", e)
    try:
        _engine_run_telegram_channels()
    except Exception as e:
        log_error("텔레그램 채널 전체", e)
    try:
        _engine_run_youtube()
    except Exception as e:
        log_error("유튜브 전체", e)
    # 테스트는 부팅 시 1회만 송출한다. 일반 주기에서는 실행하지 않는다.
    try:
        _engine_krx_market_monitor()
    except Exception as e:
        log_error("국내장 장중 브리핑", e)
    try:
        _engine_us_market_monitor()
    except Exception as e:
        log_error("미장 장중 브리핑", e)
    try:
        _engine_us_market_close_monitor()
    except Exception as e:
        log_error("미장 장마감 브리핑", e)
    try:
        _engine_outcome_tracking_cycle()
    except Exception as e:
        log_error("성과 피드백 루프", e)
    _engine_last_cycle_finished = time.time()
    _engine_log("info", "[주기 완료] %.2f초 | Telegram 즉시송출 구조", time.time()-started)



# ============================================================
# Render Web Service 헬스체크
# 메인 뉴스 엔진은 계속 1분 주기로 돌고,
# 별도 스레드에서 PORT를 열어 Render의 포트 감지를 만족시킨다.
# ============================================================
def _start_render_health_server():
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        port = int(os.environ.get("PORT", "10000"))

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ("/", "/health"):
                    self.send_response(404)
                    self.end_headers()
                    return
                body = b"news_bot is running\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                _engine_log("debug", "[Render health] " + fmt, *args)

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        _engine_log("info", "[Render] PORT=%s 헬스서버 시작 완료", port)
        server.serve_forever()

    except Exception as e:
        log_error("Render 헬스서버 시작", e, port=os.environ.get("PORT", "10000"))

def _engine_main_loop():
    _engine_load_seen()
    _engine_load_extended_state()
    if ENABLE_OUTCOME_TRACKING:
        _dart_load_corp_code_map()
        _engine_load_outcome_tracking()
    _engine_log("info", "[엔진] 60초 주기 시작")
    while True:
        cycle_start = time.time()
        try:
            with _engine_cycle_lock:
                _engine_cycle()
        except Exception as e:
            log_error("메인 사이클 치명적 오류", e)
        wait = max(1, ENGINE_INTERVAL - (time.time() - cycle_start))
        _engine_watchdog_alert()
        _engine_log("debug", "[대기] %.1f초", wait)
        # 관리자 명령이 도착하면(_engine_wake_event.set()) 대기를 즉시 종료하고
        # 다음 루프에서 바로 반영한다(예: /resume 직후 곧바로 정상 사이클 재개).
        _engine_wake_event.wait(timeout=min(wait, 5))
        _engine_wake_event.clear()
        _engine_watchdog_alert()




if __name__ == "__main__":
    try:
        # Render가 Web Service의 포트를 즉시 감지할 수 있도록 먼저 서버를 띄운다.
        health_thread = threading.Thread(
            target=_start_render_health_server,
            name="render-health",
            daemon=True
        )
        health_thread.start()
        time.sleep(0.3)

        # 관리자 최우선 명령 통제소: 감시 스레드 + 즉시실행 스레드.
        # 뉴스 수집 메인 루프와 완전히 분리되어 있어, 어떤 상황에서도
        # 관리자의 마지막 명령이 지연 없이 즉시 처리된다.
        admin_listener_thread = threading.Thread(
            target=_admin_command_listener,
            name="admin-command-listener",
            daemon=True
        )
        admin_listener_thread.start()
        admin_executor_thread = threading.Thread(
            target=_admin_command_executor,
            name="admin-command-executor",
            daemon=True
        )
        admin_executor_thread.start()
        _engine_log("info", "[BOOT] 관리자 최우선 명령 통제소 가동 | ADMIN_CHAT_ID=%s | 폴링주기=%s초",
                    ADMIN_CHAT_ID, ADMIN_COMMAND_POLL_INTERVAL)

        _engine_log("info", "[시작] 뉴스 수집·분석 | 통합 보안/중복/글로벌/과거사례/일정DB 기능 활성화")
        _engine_log("info", "[BOOT] NAVER_HUB=%s | NAVER_LEGACY=%s | DART=%s | 국내RSS=%s | US뉴스=%s | TG채널=%s",
                    bool(NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET),
                    bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
                    bool(DART_API_KEY),
                    ENABLE_DOMESTIC_NEWS,
                    ENABLE_US_NEWS,
                    ENABLE_TELEGRAM_CHANNELS)
        _engine_log("info", "[BOOT] 국내장브리핑=%s | 미장30분브리핑=%s | 장중감시=%s | Naver=%s | Google=%s", ENABLE_DOMESTIC_INTRADAY_BRIEFING, ENABLE_US_INTRADAY_BRIEFING, ENABLE_US_INTRADAY_BRIEFING, ENABLE_NAVER_NEWS, ENABLE_US_NEWS)

        _engine_main_loop()
    except KeyboardInterrupt:
        _engine_log("warning", "[종료] KeyboardInterrupt")
    except Exception as e:
        log_error("프로그램 최상위 오류", e)
        raise




# === MASTER INTEGRATION ENTRY POINT ===
# 기존 뉴스 처리 함수가 확보한 title/body/candidates/schedule/evidence를
# Telegram 송출 직전에 master_finalize_news(...)에 전달한다.
# 이 지점은 기존 송출 코드를 자동으로 덮어쓰지 않도록 별도 함수로 둔다.