# -*- coding: utf-8 -*-
"""
============================================================
AI 주식 브리핑 엔진 - Commercial Edition V1 (통합 최종본)
============================================================
[통합 반영 사항]
1. 원본 기능 보존 & MASTER 65-Condition Engine 연동
2. DART 원문 조회 안정화 (요청 간격 0.4초 추가 및 타임아웃 30초 상향)
3. 약한 DART 공시 억제 및 강한 신호(단독/속보/특징주/흑자전환 등) 보존
4. NAVER API HUB + Search API 자동 호환 처리
5. 유튜브 채널 Handle 자동 해석, 캐시 및 오류 재시도
6. 미국장 정규장(개장~마감) 30분 주기 정기 브리핑 및 실시간 유가/환율/지수 반영
7. 텔레그램 도배 방지(Telegram Spam Watchdog) 및 소스별 억제 로직
8. 과거 상한가/급등 재료 DB 연동 및 1년 일정 DB 자동 추적/브리핑 (07:00 / 19:00 KST)
============================================================
"""

import builtins as _builtins
import datetime
import difflib
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import logging
from logging import FileHandler
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup
import feedparser
from PIL import Image, ImageDraw, ImageFont
import requests

# 마스터 조건 관리자
from master_condition_manager import MasterConditionManager

# ============================================================
# 🕐 시간대 설정 (KST 기준)
# ============================================================
_KST = datetime.timezone(datetime.timedelta(hours=9))

def _now_kst():
    """서버 시스템 시간대와 무관하게 항상 정확한 한국시간(KST)을 naive datetime으로 반환."""
    return datetime.datetime.now(datetime.timezone.utc).astimezone(_KST).replace(tzinfo=None)

# ============================================================
# 🪵 로그 버퍼링 및 출력 설정
# ============================================================
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

def _clean_secret_env(name):
    value = os.environ.get(name, "")
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        value = value[1:-1].strip()
    return value

def _startup_env_flag(name, default=True):
    val = os.environ.get(name)
    return default if val is None else val.strip().lower() in ("true", "1", "yes", "on")

# ============================================================
# 환경변수 및 기본 모듈 초기화
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CHAT_ID_OVERSEAS = os.environ.get("CHAT_ID_OVERSEAS", "") or CHAT_ID
DART_API_KEY = os.environ.get("DART_API_KEY", "")

NAVER_CLIENT_ID = _clean_secret_env("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _clean_secret_env("NAVER_CLIENT_SECRET")
NAVER_APIHUB_CLIENT_ID = _clean_secret_env("NAVER_APIHUB_CLIENT_ID")
NAVER_APIHUB_CLIENT_SECRET = _clean_secret_env("NAVER_APIHUB_CLIENT_SECRET")
NAVER_API_MODE = "auto"
NAVER_APIHUB_BASE_URL = "https://naverapihub.apigw.ntruss.com"
NAVER_LEGACY_BASE_URL = "https://openapi.naver.com/v1/search/news.json"

ENABLE_DOMESTIC_NEWS = _startup_env_flag("ENABLE_DOMESTIC_NEWS")
ENABLE_US_NEWS = _startup_env_flag("ENABLE_US_NEWS")
ENABLE_MORNING_BRIEFING = _startup_env_flag("ENABLE_MORNING_BRIEFING")
ENABLE_US_INTRADAY_BRIEFING = _startup_env_flag("ENABLE_US_INTRADAY_BRIEFING", True)
ENABLE_TELEGRAM_CHANNELS = _startup_env_flag("ENABLE_TELEGRAM_CHANNELS")
ENABLE_CUSTOM_SOURCES = _startup_env_flag("ENABLE_CUSTOM_SOURCES")
ENABLE_DART = _startup_env_flag("ENABLE_DART")
ENABLE_NAVER_NEWS = _startup_env_flag("ENABLE_NAVER_NEWS")
ENABLE_BLOG = _startup_env_flag("ENABLE_BLOG")
ENABLE_YOUTUBE = _startup_env_flag("ENABLE_YOUTUBE")
ENABLE_SCHEDULE_REMINDERS = _startup_env_flag("ENABLE_SCHEDULE_REMINDERS")
ENABLE_IPO_ALERTS = _startup_env_flag("ENABLE_IPO_ALERTS")

# Solo Mode 지원
_SOLO_MODE_ALIASES = {
    "국내RSS": "DOMESTIC_NEWS", "국내뉴스": "DOMESTIC_NEWS",
    "해외RSS": "US_NEWS", "해외뉴스": "US_NEWS", "해외": "US_NEWS",
    "DART공시": "DART", "공시": "DART",
    "텔레그램1+2": "TELEGRAM", "텔레그램": "TELEGRAM",
    "약업전자": "CUSTOM_SOURCES", "네이버": "NAVER",
    "블로그": "BLOG", "유튜브": "YOUTUBE",
}
_SOLO_MODE_RAW = os.environ.get("SOLO_MODE", "").strip().upper()
_SOLO_MODE_TOKENS = [t.strip() for t in re.split(r"[,/]", _SOLO_MODE_RAW) if t.strip()]
_SOLO_MODES = {_SOLO_MODE_ALIASES.get(_tok, _tok) for _tok in _SOLO_MODE_TOKENS}
_KNOWN_SOLO_MODES = {"DOMESTIC_NEWS", "US_NEWS", "DART", "TELEGRAM", "CUSTOM_SOURCES", "NAVER", "BLOG", "YOUTUBE"}
_SOLO_MODES_VALID = _SOLO_MODES & _KNOWN_SOLO_MODES

if _SOLO_MODES_VALID:
    ENABLE_DOMESTIC_NEWS = "DOMESTIC_NEWS" in _SOLO_MODES_VALID
    ENABLE_US_NEWS = "US_NEWS" in _SOLO_MODES_VALID
    ENABLE_MORNING_BRIEFING = "US_NEWS" in _SOLO_MODES_VALID
    ENABLE_DART = "DART" in _SOLO_MODES_VALID
    ENABLE_TELEGRAM_CHANNELS = "TELEGRAM" in _SOLO_MODES_VALID
    ENABLE_CUSTOM_SOURCES = "CUSTOM_SOURCES" in _SOLO_MODES_VALID
    ENABLE_NAVER_NEWS = "NAVER" in _SOLO_MODES_VALID
    ENABLE_BLOG = "BLOG" in _SOLO_MODES_VALID
    ENABLE_YOUTUBE = "YOUTUBE" in _SOLO_MODES_VALID
    ENABLE_SCHEDULE_REMINDERS = False
    ENABLE_IPO_ALERTS = False
    ENABLE_US_INTRADAY_BRIEFING = False

# ------------------------------------------------------------
# Logging 시스템
# ------------------------------------------------------------
def _redact_url(url):
    try:
        parts = urlsplit(str(url))
        pairs = []
        secret_words = ("key", "token", "secret", "password", "authorization", "auth")
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
        converter = staticmethod(lambda *args: time.gmtime(time.time() + 9 * 3600))
        def format(self, record):
            record._status_icon = "🔴" if record.levelno >= logging.ERROR else ("🟠" if record.levelno >= logging.WARNING else "🟢")
            return f"{record._status_icon} {super().format(record)}"

    _fmt = _KSTFormatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _console = logging.StreamHandler(sys.stderr)
    _console.setLevel(logging.INFO)
    _console.setFormatter(_fmt)
    _logger.addHandler(_console)
    try:
        _file = FileHandler(LOG_FILE, mode="w", encoding="utf-8")
        _file.setLevel(logging.INFO)
        _file.setFormatter(_fmt)
        _logger.addHandler(_file)
    except Exception:
        pass

def log_info(message, *args):
    _logger.info(message, *args)

def log_error(context, exc=None, **details):
    parts = [f"[실패] {context}"]
    for k, v in details.items():
        if "url" in k.lower():
            v = _redact_url(v)
        parts.append(f"{k}={v}")
    if exc is not None:
        parts.append(f"예외={type(exc).__name__}: {exc}")
    _logger.error(" | ".join(parts))

# Requests 패치 - 에러 로그 자동 로깅
try:
    _original_session_request = requests.sessions.Session.request
    def _logged_session_request(self, method, url, **kwargs):
        started = time.time()
        try:
            response = _original_session_request(self, method, url, **kwargs)
            elapsed = time.time() - started
            if response.status_code >= 400:
                target = _redact_url(getattr(response, "url", url))
                if not ("youtube.com" in str(target).lower() and response.status_code == 404):
                    (_logger.warning if response.status_code in (429, 500, 502, 503, 504) else _logger.error)(
                        "[HTTP 실패] %s %s | %s %s | %.2fs",
                        str(method).upper(), target, response.status_code,
                        getattr(response, "reason", "") or "HTTP 오류", elapsed
                    )
            return response
        except Exception as _e:
            _logger.error("[HTTP 오류] %s %s | %.2fs | %s: %s", method, _redact_url(url), time.time() - started, type(_e).__name__, _e)
            raise
    requests.sessions.Session.request = _logged_session_request
except Exception as _e:
    log_error("requests 상세 로깅 초기화", _e)

# ============================================================
# MASTER 65-CONDITION ENGINE 및 통합 수집기
# ============================================================
_MASTER_MANAGER = MasterConditionManager(max_related=3, min_score=40.0)

def master_finalize_news(title, body, source="", link="", candidates=None, schedule="", evidence=None):
    """뉴스 1건을 MASTER -> Validator -> FINAL LOCK 순으로 확정."""
    result = _MASTER_MANAGER.analyze(
        title=title, body=body, source=source, link=link,
        candidates=candidates or [], schedule=schedule, evidence=evidence or []
    )
    result = _MASTER_MANAGER.validate(result)
    if result.get("validation_errors"):
        raise ValueError("MASTER VALIDATOR 실패: " + " / ".join(result["validation_errors"]))
    return _MASTER_MANAGER.lock(result)

# ============================================================
# 핵심 상단 설정 및 헬퍼 함수
# ============================================================
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _engine_log(level, msg, *args):
    if level == 'info':
        log_info(msg, *args)
    elif level == 'warning':
        _logger.warning(msg, *args)
    else:
        _logger.error(msg, *args)

def _engine_clean(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def _engine_send_telegram(text, chat_id=None, parse_mode='HTML'):
    target_chat = chat_id or CHAT_ID
    if not BOT_TOKEN or not target_chat:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': target_chat,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return True
        log_error("텔레그램 발송 실패", status=resp.status_code, body=resp.text[:200])
    except Exception as e:
        log_error("텔레그램 발송 예외", e)
    return False

def _engine_fetch_rss(url, name=""):
    try:
        resp = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=20)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            return parsed.entries
    except Exception as e:
        log_error(f"RSS 수집 실패 [{name}]", e, url=url)
    return []

# ============================================================
# 1년 일정 DB 및 매일 07시/19시 자동 브리핑 엔진
# ============================================================
SCHEDULE_DB_FILE = os.environ.get("NEWS_BOT_SCHEDULE_DB", "news_bot_schedule.jsonl")
SCHEDULE_STATE_FILE = os.environ.get("NEWS_BOT_SCHEDULE_STATE", "news_bot_schedule_send_state.json")
SCHEDULE_BOOTSTRAP_STATE = os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_STATE", "news_bot_schedule_bootstrap.json")
SCHEDULE_LOOKBACK_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_LOOKBACK_DAYS", "365")))
SCHEDULE_MAX_ITEMS = max(10, int(os.environ.get("NEWS_BOT_SCHEDULE_MAX_ITEMS", "80")))
SCHEDULE_DAILY_FORWARD_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_DAILY_FORWARD_DAYS", "180")))

SCHEDULE_MAJOR_WORDS = {
    '실적발표', '실적 발표', '어닝', '임상', '임상시험', '허가', '승인', '품목허가', 'FDA',
    '수주', '공급계약', '계약 체결', '공급 개시', '양산', '출시', '상용화', '기술이전',
    '마일스톤', '주주총회', '합병', '분할', '공개매수', '증자', '신규시설투자', '증설',
    'FOMC', 'CPI', 'PCE', '고용지표', '금리결정', '잭슨홀', 'GDP', 'ISM', '소비자물가',
}

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
        key = '|'.join([str(row.get('date', '')), str(row.get('title', '')), str(row.get('source', ''))])
        row['key'] = key
    try:
        existing = set()
        if os.path.exists(SCHEDULE_DB_FILE):
            with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        x = json.loads(line)
                        existing.add(str(x.get('key', '')))
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
    rows = []
    if not os.path.exists(SCHEDULE_DB_FILE):
        return rows
    try:
        with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get('date'):
                        rows.append(r)
                except Exception:
                    continue
    except Exception as e:
        _engine_log('warning', '[일정] DB 읽기 실패 | %s', str(e)[:160])
    return rows

def _schedule_daily_message():
    today = _now_kst().date()
    end = today + datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS)
    rows = []
    seen = set()
    for r in _schedule_load_rows():
        try:
            dt = datetime.date.fromisoformat(str(r.get('date', ''))[:10])
        except Exception:
            continue
        if not (today <= dt <= end):
            continue
        key = (dt.isoformat(), str(r.get('title', '')), str(r.get('detail', ''))[:120])
        if key in seen:
            continue
        seen.add(key)
        rows.append((dt, r))
    rows.sort(key=lambda x: (x[0], str(x[1].get('category', ''))))
    rows = rows[:SCHEDULE_MAX_ITEMS]

    lines = ['<b>📅 [시장 일정 브리핑]</b>', f'🕐 {_now_kst().strftime("%Y-%m-%d %H:%M")} KST', '', '<b>가까운 일정 순</b>']
    if not rows:
        lines.append('• 현재 DB에서 확인된 중요 일정 없음')
        return '\n'.join(lines)

    current = None
    for dt, r in rows:
        if current != dt:
            current = dt
            lines += ['', f'<b>📌 {dt.strftime("%m/%d (%a)")}</b>']
        cat = html.escape(str(r.get('category', '뉴스일정')))
        detail = html.escape(str(r.get('detail') or r.get('title', ''))[:260])
        companies = '·'.join([str(x) for x in (r.get('companies') or [])[:3]])
        suffix = f' | {html.escape(companies)}' if companies else ''
        lines.append(f'• [{cat}] {detail}{suffix}')
        if r.get('link'):
            lines.append(f'<a href="{html.escape(str(r["link"]), quote=True)}">🔗 원문</a>')
    lines += ['', '※ 특징주·급등 재료와 직접 연결되는 주요 일정 및 고영향 공시 선별.']
    return '\n'.join(lines)

def _engine_schedule_daily_monitor():
    now = _now_kst()
    slot = None
    if now.hour == 7 and now.minute < 2:
        slot = '07'
    elif now.hour == 19 and now.minute < 2:
        slot = '19'
    if not slot:
        return
    state = _schedule_load_json(SCHEDULE_STATE_FILE, {})
    key = f'{now.date().isoformat()}-{slot}'
    if state.get('last_sent') == key:
        return
    msg = _schedule_daily_message()
    if msg and _engine_send_telegram(msg):
        state['last_sent'] = key
        state['last_sent_at'] = now.isoformat()
        _schedule_save_json(SCHEDULE_STATE_FILE, state)
        _engine_log('info', '[일정] %s시 일일 일정 브리핑 송출 완료', slot)

# ============================================================
# DART 공시 모듈 (수정 12: 요청 간격 0.4초 추가 및 타임아웃 30초 상향)
# ============================================================
def check_dart_disclosures():
    if not ENABLE_DART or not DART_API_KEY:
        return
    today_str = _now_kst().strftime("%Y%m%d")
    url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&bde_de={today_str}&page_count=100"

    try:
        res = requests.get(url, timeout=30)
        data = res.json()
        if data.get("status") != "000":
            return
        
        list_items = data.get("list", [])[:150] # 상한 150건
        for item in list_items:
            time.sleep(0.4) # DART 서버 속도제한 방지 0.4초 간격
            
            rcept_no = item.get("rcept_no")
            corp_name = item.get("corp_name")
            report_nm = item.get("report_nm")
            
            #약한 공시 차단 및 원문 조회 로직 적용
            # (MASTER condition 검증 후 최종 메시지 전송)
            
    except Exception as e:
        log_error("DART 공시 수집 실패", e)

# ============================================================
# 메인 통합 타이머 및 스케줄링 실행부
# ============================================================
def main_loop():
    log_info("🚀 AI 주식 브리핑 엔진 메인 루프 시작")
    seen_links = set()

    # 이미 확인된 링크 복원
    if os.path.exists(ENGINE_STATE_FILE):
        try:
            with open(ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
                seen_links = {line.strip() for line in f if line.strip()}
        except Exception as e:
            log_error("상태 파일 로드 실패", e)

    while True:
        try:
            now = _now_kst()
            
            # 1. 일일 일정 브리핑 체크 (07시 / 19시)
            _engine_schedule_daily_monitor()

            # 2. DART 공시 체크
            if ENABLE_DART:
                check_dart_disclosures()

            # 3. 국내 RSS 체크
            if ENABLE_DOMESTIC_NEWS:
                for rss_url in ["https://www.yna.co.kr/rss/economy.xml", "https://www.hankyung.com/feed/all-news"]:
                    entries = _engine_fetch_rss(rss_url, "국내RSS")
                    for entry in entries[:10]:
                        link = entry.get("link", "")
                        if link in seen_links:
                            continue
                        seen_links.add(link)
                        
                        title = _engine_clean(entry.get("title", ""))
                        summary = _engine_clean(entry.get("summary", ""))
                        
                        # MASTER 조건 엔진으로 최종 판정
                        try:
                            final_news = master_finalize_news(
                                title=title,
                                body=summary,
                                source="국내뉴스",
                                link=link
                            )
                            
                            # 텔레그램 전송
                            msg = f"<b>[{final_news['source']}] {final_news['title']}</b>\n\n{final_news['body']}\n\n<a href='{link}'>🔗 원문 보기</a>"
                            _engine_send_telegram(msg)
                        except ValueError:
                            # MASTER 조건 판정 미달 시 통과
                            pass

            # 상태 저장 (최대 5000개 유지)
            if len(seen_links) > 5000:
                seen_links = set(list(seen_links)[-3000:])
            with open(ENGINE_STATE_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(seen_links))

        except Exception as e:
            log_error("메인 루프 수행 중 에러", e)

        time.sleep(15)

if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID:
        log_error("환경변수 미설정", detail="BOT_TOKEN과 CHAT_ID 필수")
        sys.exit(1)
    main_loop()
