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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    if not ENABLE_NAVER_NEWS:
        # [버그 수정] _engine_run_naver()는 ENABLE_NAVER_NEWS=OFF면 즉시 리턴하는데
        # 이 함수는 그 체크가 없어서, 네이버 뉴스 기능 자체가 꺼져 있어도(예: 네이버
        # 개발자센터 검색 오픈API 서비스 종료로 인한 기본 OFF) 키워드조합만 5분마다
        # 계속 (만료됐거나 더 이상 유효하지 않은) NAVER 인증정보로 요청을 보내
        # "모든 NAVER 인증경로 실패" 에러 로그를 반복 생산하고 있었다.
        _engine_log("debug", "[키워드 조합] ENABLE_NAVER_NEWS=OFF | 스킵")
        return
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
# [확장] 테마별 대장주 순위(거래대금 1위)를 매기려면 테마당 최소 3개 이상의
# 종목이 있어야 의미가 있다. 기존 10개 고정 종목에서 8개 테마 x 3~4개로 확장했다.
KRX_WATCHLIST = {
    "^KS11": ("코스피", "지수"), "^KQ11": ("코스닥", "지수"),
    # 반도체
    "005930.KS": ("삼성전자", "반도체"), "000660.KS": ("SK하이닉스", "반도체"),
    "042700.KS": ("한미반도체", "반도체"), "000990.KS": ("DB하이텍", "반도체"),
    # 2차전지
    "373220.KS": ("LG에너지솔루션", "2차전지"), "006400.KS": ("삼성SDI", "2차전지"),
    "247540.KQ": ("에코프로비엠", "2차전지"), "003670.KS": ("포스코퓨처엠", "2차전지"),
    # 바이오
    "207940.KS": ("삼성바이오로직스", "바이오"), "068270.KS": ("셀트리온", "바이오"),
    "302440.KS": ("SK바이오사이언스", "바이오"), "000100.KS": ("유한양행", "바이오"),
    # 조선
    "042660.KS": ("한화오션", "조선"), "329180.KS": ("HD현대중공업", "조선"),
    "010140.KS": ("삼성중공업", "조선"), "009540.KS": ("HD한국조선해양", "조선"),
    # 방산
    "012450.KS": ("한화에어로스페이스", "방산"), "079550.KS": ("LIG넥스원", "방산"),
    "064350.KS": ("현대로템", "방산"), "272210.KS": ("한화시스템", "방산"),
    # 자동차
    "005380.KS": ("현대차", "자동차"), "000270.KS": ("기아", "자동차"),
    "012330.KS": ("현대모비스", "자동차"), "204320.KS": ("HL만도", "자동차"),
    # 인터넷/플랫폼
    "035420.KS": ("NAVER", "인터넷"), "035720.KS": ("카카오", "인터넷"),
    "323410.KS": ("카카오뱅크", "인터넷"), "259960.KS": ("크래프톤", "인터넷"),
    # AI/로봇
    "454910.KS": ("두산로보틱스", "AI로봇"), "277810.KQ": ("레인보우로보틱스", "AI로봇"),
    "090360.KQ": ("로보스타", "AI로봇"),
    # 원전
    "034020.KS": ("두산에너빌리티", "원전"), "051600.KS": ("한전KPS", "원전"),
    "052690.KS": ("한전기술", "원전"),
    # 금융지주
    "105560.KS": ("KB금융", "금융지주"), "055550.KS": ("신한지주", "금융지주"),
    "086790.KS": ("하나금융지주", "금융지주"), "316140.KS": ("우리금융지주", "금융지주"),
    "USDKRW=X": ("원/달러", "환율"),
}
_KRX_BRIEFING_LAST_SNAPSHOT = {}
_KRX_BRIEFING_LAST_POLL = None


# ============================================================
# [거래대금 보완 — 네이버 모바일 시세 API]
# Yahoo chart 엔드포인트는 거래대금을 주지 않아 "테마별 거래대금 1위(대장주)"를
# 판정할 방법이 없었다. 네이버 모바일 시세 목록 API(코스피/코스닥 상위 종목을
# 페이지 단위로 한 번에 반환)에서 종목별 거래대금(aa)을 가져와 보완한다.
# 이 API는 시가총액 상위 순으로 반환되므로, 감시종목이 상위권 밖이면 여기 없을
# 수 있다 — 그 경우 거래대금 없이 등락률만 표시하고 추정하지 않는다.
# [주의] 배포 환경에서 실제 응답 스키마를 한 번 확인해 필요시 파싱 경로를
# 조정할 것 — 네트워크가 차단된 환경에서 작성해 실응답으로 검증하지 못했다.
# ============================================================
NAVER_MOBILE_SISE_LIST_URL = "https://m.stock.naver.com/api/json/sise/siseListJson.nhn"


def _krx_naver_bulk_fetch_one(sosok, timeout):
    """sosok 1개(코스피 또는 코스닥)의 벌크 시세를 조회한다. 병렬 호출용으로
    분리된 단일 요청 함수 — 실패 시 빈 dict를 반환하고 예외를 던지지 않는다."""
    out = {}
    try:
        r = requests.get(
            NAVER_MOBILE_SISE_LIST_URL,
            params={"menu": "market_sum", "sosok": sosok, "pageSize": 200, "page": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        if not r.ok:
            return out
        data = r.json()
        rows = (
            (data.get("result") or {}).get("itemList")
            or data.get("itemList")
            or (data if isinstance(data, list) else [])
            or []
        )
        for row in rows:
            code = str(row.get("cd", "")).strip()
            if not code:
                continue
            out[code] = {
                "name": row.get("nm", ""),
                "price": row.get("nv"),
                "change_pct": row.get("cr"),
                "trade_value": row.get("aa"),  # 거래대금(백만원 단위로 추정)
            }
    except Exception as e:
        _engine_log("warning", "[국내장브리핑] 네이버 거래대금 벌크조회 실패 | sosok=%s | 원인=%s", sosok, str(e)[:120])
    return out


# [성능 수정] 코스피/코스닥 조회를 순차 2회가 아니라 병렬 2회로 실행해 전체
# 대기시간을 요청 1건 수준으로 줄인다. 이 요청은 브리핑 전용이라 전체
# ENGINE_HTTP_TIMEOUT보다 짧게(최대 8초) 끊어, 느린 응답 1건이 이 단계 전체를
# 오래 붙잡지 않게 한다.
KRX_NAVER_BULK_TIMEOUT = min(ENGINE_HTTP_TIMEOUT, 8)


def _krx_naver_bulk_market_quotes():
    """코스피(sosok=0)/코스닥(sosok=1) 상위 종목의 가격·등락률·거래대금을
    가져온다. 실패하거나 스키마가 예상과 다르면 빈 dict를 반환하고 조용히
    넘어간다(거래대금 보완 실패가 브리핑 전체를 막지 않게 한다)."""
    out = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_krx_naver_bulk_fetch_one, sosok, KRX_NAVER_BULK_TIMEOUT) for sosok in (0, 1)]
        for fut in as_completed(futures):
            try:
                out.update(fut.result())
            except Exception as e:
                _engine_log("warning", "[국내장브리핑] 거래대금 벌크조회 스레드 오류 | 원인=%s", str(e)[:120])
    return out


# ============================================================
# [외국인/기관 수급 — 네이버 금융 투자자별 매매동향]
# 시장 전체(코스피/코스닥) 당일 외국인·기관 순매수를 스크래핑한다.
# 열 순서가 아니라 헤더 텍스트로 열을 찾아, 페이지 구조가 소폭 바뀌어도
# 안정적으로 동작하도록 한다. 실패하면 None을 반환하며 추정하지 않는다.
# [주의] 위와 동일하게 실응답 검증이 안 된 상태이므로 배포 후 1회 확인 필요.
# ============================================================
def _krx_market_investor_flow(market="KOSPI"):
    sosok = "01" if market == "KOSPI" else "02"
    bizdate = _now_kst().strftime("%Y%m%d")
    try:
        r = requests.get(
            "https://finance.naver.com/sise/investorDealTrendDay.naver",
            params={"bizdate": bizdate, "sosok": sosok, "page": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=KRX_NAVER_BULK_TIMEOUT,
        )
        if not r.ok:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.select("table")
        if not tables:
            return None
        table = tables[0]
        trs = table.select("tr")
        if len(trs) < 2:
            return None
        header_cells = [_engine_clean(c.get_text()) for c in trs[0].select("th, td")]
        for tr in trs[1:]:
            cells = [_engine_clean(td.get_text()) for td in tr.select("td")]
            if not cells or not cells[0]:
                continue
            row = dict(zip(header_cells, cells))

            def _num(keyword):
                for hk, v in row.items():
                    if keyword in hk:
                        try:
                            return float(v.replace(",", ""))
                        except Exception:
                            return None
                return None

            foreign = _num("외국인")
            organ = _num("기관")
            if foreign is not None or organ is not None:
                return {"date": cells[0], "foreign": foreign, "organ": organ}
        return None
    except Exception as e:
        _engine_log("warning", "[국내장브리핑] %s 수급 조회 실패 | 원인=%s", market, str(e)[:120])
        return None

KRX_QUOTE_FETCH_WORKERS = 12  # [성능수정] 아래 사유 참고

def _krx_briefing_fetch_all():
    """[성능 수정 — 부팅/사이클 지연 원인]
    감시종목을 10개→33개로 확장하면서 Yahoo 시세를 종목별로 순차(for문) 조회하면
    한 번의 브리핑 갱신에 네트워크 요청이 30건 이상 한 줄로 쌓여, 요청 하나하나가
    느려질 때마다 그 지연이 그대로 누적되어 이 단계 하나가 몇 분씩 걸리는 문제가
    있었다(메인 루프가 한 사이클 안에서 이 단계를 기다리므로 전체가 멈춘 것처럼
    보임). ThreadPoolExecutor로 동시에 요청해 전체 소요시간을 개별 요청 1건
    수준으로 줄인다. 개별 요청 실패는 기존과 동일하게 조용히 스킵한다."""
    data = {}
    with ThreadPoolExecutor(max_workers=KRX_QUOTE_FETCH_WORKERS) as ex:
        futures = {ex.submit(_yahoo_chart_quote, symbol): (symbol, meta) for symbol, meta in KRX_WATCHLIST.items()}
        futures[ex.submit(_yahoo_chart_quote, "CL=F")] = ("CL=F", ("WTI 유가", "원자재"))
        for fut in as_completed(futures):
            symbol, meta = futures[fut]
            try:
                q = fut.result()
            except Exception as e:
                _engine_log("warning", "[국내장브리핑] %s 시세 조회 실패 | 원인=%s", symbol, str(e)[:120])
                continue
            if q:
                q.update({"name": meta[0], "theme": meta[1]})
                data[symbol] = q

    # 거래대금(대장주 판정용)은 네이버 벌크 시세로 보완한다. 실패해도 등락률
    # 표시에는 지장이 없도록 예외를 흡수하고 조용히 스킵한다.
    try:
        bulk = _krx_naver_bulk_market_quotes()
    except Exception as e:
        bulk = {}
        _engine_log("warning", "[국내장브리핑] 거래대금 보완 조회 실패 | 원인=%s", str(e)[:120])
    for symbol, q in data.items():
        code = symbol.split(".")[0]
        b = bulk.get(code)
        if b and b.get("trade_value") is not None:
            q["trade_value"] = b["trade_value"]
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


# ============================================================
# [테마별 순위 — 시장분석 섹션용]
# 테마 합산 거래대금 기준으로 1/2/3등을 매기고, 테마 내에서는
# 거래대금이 가장 큰 종목을 "대장주"로, 등락률 절대값이 가장 큰 종목을
# "급등종목"으로 구분한다(둘이 같으면 하나만 표기).
# ============================================================
def _krx_rank_themes(snapshot):
    excluded = {"^KS11", "^KQ11", "USDKRW=X", "CL=F"}
    groups = {}
    for symbol, q in snapshot.items():
        if symbol in excluded or q.get("change_pct") is None:
            continue
        theme = str(q.get("theme", "")).strip()
        if not theme:
            continue
        groups.setdefault(theme, []).append(q)
    ranked = []
    for theme, qs in groups.items():
        total_value = sum(float(q.get("trade_value") or 0) for q in qs)
        leader_by_value = max(qs, key=lambda q: float(q.get("trade_value") or 0))
        leader_by_pct = max(qs, key=lambda q: abs(float(q.get("change_pct") or 0)))
        ranked.append({
            "theme": theme, "total_value": total_value, "members": qs,
            "leader_by_value": leader_by_value, "leader_by_pct": leader_by_pct,
        })
    ranked.sort(key=lambda x: x["total_value"], reverse=True)
    return ranked


def _krx_recent_reason(name, theme):
    """최근 처리된 뉴스(과거사례 캐시)에서 이 종목/테마와 관련된 가장 최근
    기사 제목을 찾는다. 확인된 근거가 없으면 추정하지 않고 빈 값을 반환한다."""
    try:
        from news_engine_핵심엔진 import _engine_historical_cache
    except Exception:
        return "", ""
    now = _now_kst()
    needles = [n for n in (name, theme) if n]
    for row in reversed(_engine_historical_cache[-1500:]):
        dt = row.get("published_dt")
        try:
            if dt and (now - dt).total_seconds() > 180 * 60:
                continue
        except Exception:
            pass
        text = str(row.get("text", "")) + " " + str(row.get("title", ""))
        if any(n and n in text for n in needles):
            return str(row.get("title", ""))[:180], str(row.get("link", ""))
    return "", ""


def _krx_similar_past_move(theme):
    """과거사례 캐시에서 같은 테마명이 언급된 과거 기사 중 실제 등락률(%)이
    본문에 명시된 것을 찾아 "누적 데이터 기반 참고"로 덧붙인다. 못 찾으면
    빈 문자열(추정하지 않음)."""
    try:
        from news_engine_핵심엔진 import _engine_historical_cache
    except Exception:
        return ""
    for row in reversed(_engine_historical_cache[-3000:]):
        text = str(row.get("text", "")) + " " + str(row.get("title", ""))
        if theme and theme in text:
            m = re.search(r"(?:\+|-)?\d+(?:\.\d+)?\s*%", text)
            if m:
                return f"{str(row.get('title',''))[:80]} → 당시 {m.group(0)}"
    return ""


def _krx_briefing_message(snapshot, et, events=None, opening=False):
    events = events or []
    lines = ["<b>🇰🇷 [국내장 브리핑]</b>", f"🕐 {et.strftime('%H:%M KST')}", ""]

    lines.append("<b>📊 주요 지수</b>")
    for s in ("^KS11", "^KQ11"):
        q = snapshot.get(s)
        if q:
            lines.append(f"• {_us_display_name(s, q['name'])} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")

    # [선물] 코스피200 선물의 검증된 무료 실시간 소스가 아직 연동되어 있지
    # 않다. 가짜 수치를 넣지 않고 정직하게 미연동 상태를 표시한다.
    lines.append("• 선물 · 데이터 소스 미연동(추가 예정)")

    # [성능 수정] 코스피/코스닥 수급 조회도 순차 2회 대신 병렬 2회로 실행한다.
    with ThreadPoolExecutor(max_workers=2) as _ex:
        _fut_map = {_ex.submit(_krx_market_investor_flow, m): m for m in ("KOSPI", "KOSDAQ")}
        _flow_results = {}
        for _fut in as_completed(_fut_map):
            try:
                _flow_results[_fut_map[_fut]] = _fut.result()
            except Exception as e:
                _engine_log("warning", "[국내장브리핑] 수급조회 스레드 오류 | %s | 원인=%s", _fut_map[_fut], str(e)[:120])
                _flow_results[_fut_map[_fut]] = None
    flow_fg = _flow_results.get("KOSPI")
    flow_fg_kq = _flow_results.get("KOSDAQ")
    def _sum_flow(key):
        vals = [f.get(key) for f in (flow_fg, flow_fg_kq) if f and f.get(key) is not None]
        return sum(vals) if vals else None
    foreign_total = _sum_flow("foreign")
    organ_total = _sum_flow("organ")
    if foreign_total is not None:
        lines.append(f"• 외국인 수급 · 코스피+코스닥 순매수 {foreign_total:+,.0f}억원")
    else:
        lines.append("• 외국인 수급 · 확인불가")
    if organ_total is not None:
        lines.append(f"• 기관 수급 · 코스피+코스닥 순매수 {organ_total:+,.0f}억원")
    else:
        lines.append("• 기관 수급 · 확인불가")

    fx = snapshot.get("USDKRW=X")
    lines.append(f"<b>💱 원/달러</b> · {_us_format_pct(fx.get('change_pct')) if fx else '확인불가'}")
    oil = snapshot.get("CL=F")
    lines.append(f"<b>💱 유가</b> · WTI {_us_format_pct(oil.get('change_pct')) if oil else '확인불가'}")

    # ------------------------------------------------------------
    # 📊 시장 분석: 거래대금 1/2/3등 테마 + 대장주/급등종목 + 특이종목 +
    # 누적 데이터 기반 참고 코멘트
    # ------------------------------------------------------------
    lines += ["", "<b>📊 시장 분석</b>"]
    ranked = _krx_rank_themes(snapshot)
    covered_symbols = set()
    if ranked:
        medal = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(ranked[:3]):
            lead_v = r["leader_by_value"]
            lead_p = r["leader_by_pct"]
            same = lead_v is lead_p
            lines.append(f"{medal[i] if i < 3 else '•'} <b>{r['theme']}</b> 테마")
            lines.append(f"  ↳ 대장주(거래대금 1위): {lead_v['name']} {_us_direction(lead_v.get('change_pct'))} {_us_format_pct(lead_v.get('change_pct'))}")
            if not same:
                lines.append(f"  ↳ 급등 종목(등락률 1위): {lead_p['name']} {_us_direction(lead_p.get('change_pct'))} {_us_format_pct(lead_p.get('change_pct'))}")
            covered_symbols.add(lead_v.get("name"))
            covered_symbols.add(lead_p.get("name"))

            reason_title, reason_link = _krx_recent_reason(lead_v.get("name", ""), r["theme"])
            if reason_title:
                lines.append(f"  ↳ 이유: {html.escape(reason_title)}")
            else:
                lines.append("  ↳ 이유: 확인된 관련 뉴스 없음")

            past = _krx_similar_past_move(r["theme"])
            if past:
                lines.append(f"  📚 누적 데이터 참고: {html.escape(past)}")
    else:
        lines.append("• 테마별 유의미한 거래대금 데이터 없음")

    # 테마 상위 3개에 포함되지 않은 종목 중 변동폭이 큰 "특이 종목"만 별도 언급
    notable = []
    for s, q in snapshot.items():
        if s in {"^KS11", "^KQ11", "USDKRW=X", "CL=F"}:
            continue
        pct = q.get("change_pct")
        if pct is None or q.get("name") in covered_symbols:
            continue
        if abs(pct) >= KRX_STOCK_MOVE_THRESHOLD:
            notable.append(q)
    notable.sort(key=lambda q: abs(q.get("change_pct") or 0), reverse=True)
    if notable:
        lines += ["", "<b>⭐ 특이 종목</b>"]
        for q in notable[:5]:
            pct = q.get("change_pct")
            reason_title, _ = _krx_recent_reason(q.get("name", ""), q.get("theme", ""))
            line = f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}"
            line += f" · 이유: {html.escape(reason_title)}" if reason_title else " · 이유: 확인된 관련 뉴스 없음"
            lines.append(line)

    if events:
        lines += ["", "<b>🚨 장중 구조 변화</b>"]
        for _, _, q, delta in events[:5]:
            lines.append(f"• {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q.get('change_pct'))}")

    lines += ["", "※ 수급·거래대금은 참고용 집계치이며, 누적 데이터 코멘트는 과거 유사 사례 참고용으로 방향성을 보장하지 않습니다."]
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
