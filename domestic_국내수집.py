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

# ==== module: domestic (auto-split from original main.py) ====

from common_공용유틸 import ENGINE_HTTP_TIMEOUT, _clean_secret_env, _engine_clean, _engine_log, _engine_send_telegram, _now_kst, log_error
from config_환경설정 import ENABLE_DOMESTIC_INTRADAY_BRIEFING, ENABLE_DOMESTIC_NEWS, ENABLE_NAVER_NEWS, ENABLE_US_NEWS, KRX_HOLIDAYS_2026, USER_AGENT
from news_engine_핵심엔진 import GLOBAL_AND_DOMESTIC_GIANTS, _engine_entry_published, _engine_fetch_rss, _engine_process_item
from overseas_해외수집 import US_RSS_URLS, _us_direction, _us_display_name, _us_format_pct, _yahoo_chart_quote
from sources_external_외부연동 import _dart_stock_code_for_name


# ⚠️ 중요: NAVER_CLIENT_*는 구형 Developer Center Search API용,
# NAVER_APIHUB_CLIENT_*는 NAVER API HUB용이다. 서로 섞어서 보내지 않는다.
NAVER_CLIENT_ID = _clean_secret_env("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _clean_secret_env("NAVER_CLIENT_SECRET")
NAVER_APIHUB_CLIENT_ID = _clean_secret_env("NAVER_APIHUB_CLIENT_ID")
NAVER_APIHUB_CLIENT_SECRET = _clean_secret_env("NAVER_APIHUB_CLIENT_SECRET")
NAVER_API_MODE = "auto"
NAVER_APIHUB_BASE_URL = "https://naverapihub.apigw.ntruss.com"
NAVER_LEGACY_BASE_URL = "https://openapi.naver.com/v1/search/news.json"

RSS_CHECK_INTERVAL = 15          
NAVER_CHECK_INTERVAL = 300       

NAVER_EXTRA_THEME_QUERIES = [
    "반도체", "HBM", "이차전지", "AI 반도체", "로봇", "방산", "원전",
    "조선", "바이오", "양자컴퓨팅", "우주항공",
]

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

NAVER_SEARCH_QUERIES = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS + NAVER_EXTRA_THEME_QUERIES + [
    "특징주", "속보 주식", "주식 속보", "급등 급락 주식", "상한가 주식", "단독 주식",
    "수주 공급계약 임상 승인 실적", "삼성전자 SK하이닉스 특징주", "반도체 특징주", "바이오 특징주"
]))


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


def _naver_extract_items(response):
    """[버그 수정] 분할 전 원본에서 이 함수가 어디에도 정의돼 있지 않아,
    네이버 API 호출이 성공(r.ok=True)해도 즉시 NameError로 except에 잡혀
    검색 결과가 한 건도 처리되지 못하고 있었다(로그만 남고 뉴스는 0건 누적).
    네이버 뉴스 검색 API 응답은 JSON {"items": [...]} 형태이며, 아래 호출부가
    쓰는 title/originallink/link/pubDate/description 필드와 정확히 일치하므로
    이 형태로 파싱한다."""
    try:
        return response.json().get("items", []) or []
    except Exception as e:
        log_error("네이버 응답 파싱", e)
        return []


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
