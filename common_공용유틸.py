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

# ==== module: common (auto-split from original main.py) ====


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

def _clean_secret_env(name):
    # Render 환경변수에 실수로 따옴표/앞뒤 공백이 붙어도 인증값 자체는 깨끗하게 사용한다.
    value = os.environ.get(name, "")
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        value = value[1:-1].strip()
    return value


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
# NAVER_CLIENT_ID / NAVER_CLIENT_SECRET는 위에서 이미 정규화한 값을 그대로 사용한다.

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "❌ BOT_TOKEN / CHAT_ID가 비어 있습니다.\n"
        "    환경변수(BOT_TOKEN, CHAT_ID)에 값을 설정해주세요."
    )

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

ENGINE_HTTP_TIMEOUT = 20


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


def _engine_clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(str(text or ""), "html.parser").get_text(" ")).strip()


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
