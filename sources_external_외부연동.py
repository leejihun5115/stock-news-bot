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

# ==== module: sources_external (auto-split from original main.py) ====

from common_공용유틸 import ENGINE_HTTP_TIMEOUT, _engine_clean, _engine_log, _now_kst, log_error
from config_환경설정 import ENABLE_DART, ENABLE_HISTORICAL_SURGE_DB, ENABLE_TELEGRAM_CHANNELS, ENABLE_YOUTUBE, USER_AGENT
from news_engine_핵심엔진 import GLOBAL_AND_DOMESTIC_GIANTS, _engine_classify, _engine_entry_published, _engine_fetch_rss, _engine_process_item, _engine_record_historical_case, _engine_telegram_title
from schedule_일정DB import _schedule_add_dart_row

DART_API_KEY = os.environ.get("DART_API_KEY", "")

DART_API_KEY = os.environ.get("DART_API_KEY", "")
CUSTOM_SOURCE_INTERVAL = 300     
TELEGRAM_CHANNEL_INTERVAL = 60   
TELEGRAM_UNFILTERED_INTERVAL = 60  
DART_CHECK_INTERVAL = 60         
BLOG_CHECK_INTERVAL = 1800       
YOUTUBE_CHECK_INTERVAL = 1800    

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

DART_WATCH_COMPANIES = set(GLOBAL_AND_DOMESTIC_GIANTS)
DART_RUMOR_KEYWORDS = ["조회공시", "풍문", "보도", "해명", "설명요구"]

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

_DART_CONTRACT_REPORT_HINTS = ("단일판매", "공급계약")


def _dart_fetch_contract_detail(rcept_no):
    """[신규 2026-08-24] '단일판매·공급계약체결' 등 계약 공시의 원문을 받아
    계약금액/매출액 대비 비율/계약상대방/계약기간을 추출한다.
    DART list.json(공시 목록)에는 이 수치들이 없고, 원문 문서에만 있다.
    사용자 요청: "🔥 강한 뉴스"라는 빈 배지 대신, 계약 규모가 실제 매출의
    몇%인지 등 판단 근거가 될 실제 수치를 보여달라는 요청에 따라 추가.
    실패해도(429, 포맷 변경 등) 예외를 던지지 않고 빈 문자열을 반환해
    본 파이프라인 전체가 이 때문에 멈추지 않게 한다.
    """
    if not rcept_no or not DART_API_KEY:
        return ""
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/document.xml",
            params={"crtfc_key": DART_API_KEY, "rcept_no": rcept_no},
            timeout=ENGINE_HTTP_TIMEOUT,
        )
        if not r.ok:
            return ""
        text = ""
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for name in zf.namelist():
                    raw = zf.read(name)
                    try:
                        text += raw.decode("euc-kr", errors="ignore")
                    except Exception:
                        text += raw.decode("utf-8", errors="ignore")
        except zipfile.BadZipFile:
            # 일부 공시는 zip이 아니라 원문 그대로 오는 경우가 있어 그대로 시도한다.
            text = r.content.decode("utf-8", errors="ignore")
        if not text:
            return ""
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = html.unescape(plain)
        plain = re.sub(r"\s+", " ", plain).strip()

        def _find(pattern):
            m = re.search(pattern, plain)
            return m.group(1).strip() if m else ""

        amount = _find(r"계약금액\s*[:：]?\s*([0-9][0-9,\.]*\s*(?:원|백만원|억원)?)")
        pct = _find(r"(?:매출액|자산총액)\s*대비\s*\(?%?\)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*%")
        counterpart = _find(r"계약상대\s*[:：]?\s*([^\s]{2,40})")
        period = _find(r"계약기간\s*[:：]?\s*([0-9]{4}[-./][0-9]{2}[-./][0-9]{2}\s*[~\-]\s*[0-9]{4}[-./][0-9]{2}[-./][0-9]{2})")

        parts = []
        if amount:
            parts.append(f"계약금액 {amount}")
        if pct:
            parts.append(f"최근 매출액 대비 {pct}%")
        if counterpart:
            parts.append(f"계약상대방 {counterpart}")
        if period:
            parts.append(f"계약기간 {period}")
        return " · ".join(parts)
    except Exception as e:
        _engine_log("warning", "[DART 원문 조회 실패] rcept_no=%s | %s", rcept_no, str(e)[:160])
        return ""


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
            # [신규] 계약(공급계약) 공시는 원문에서 계약금액/매출액대비 비율을
            # 추출해 extra에 실어 보낸다. 그 외 리포트는 기존과 동일하게 extra 없음.
            contract_extra = ""
            if any(h in report for h in _DART_CONTRACT_REPORT_HINTS):
                contract_extra = _dart_fetch_contract_detail(row.get("rcept_no", ""))
            _schedule_add_dart_row(report, corp, link, row.get("rcept_dt", ""))
            if _engine_process_item("DART", title, link, row.get("rcept_dt", ""), contract_extra):
                sent += 1
        _engine_log("info", "[DART] 후보=%d건", sent)
    except Exception as e:
        log_error("DART 검사", e)


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
