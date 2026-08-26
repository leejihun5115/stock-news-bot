# -*- coding: utf-8 -*-
"""
외부 소스 연동 모듈 (DART 공시 / 텔레그램 채널 / 유튜브).

[재작성 배경]
이 파일은 원래 구글 번역 API를 감싼 ExternalSourceManager 클래스 하나만 있는
프로토타입이었다. 그러나 나머지 코드베이스는 이 파일에서 DART_API_KEY,
_dart_load_corp_code_map, _engine_run_dart, _engine_run_telegram_channels,
_engine_run_youtube, _engine_backfill_dart_historical, _dart_stock_code_for_name
을 모듈 함수로 직접 import하고 있어(main_메인, admin_관리자, domestic_국내수집)
그대로는 봇이 기동조차 되지 않았다. 이번 재작성에서 이 함수들을 실제로 구현했다.

[번역 기능 관련 안내]
기존 ExternalSourceManager.translate_text()는 제거했다. 번역은 이미
translation_번역.py가 (무료 gtx 경로 + 429 재시도 큐까지) 전담하고 있어,
같은 역할을 하는 두 번째 구현을 이 파일에 남겨두면 어느 쪽이 실제로 쓰이는지
헷갈리는 이중 시스템이 된다. 번역이 필요하면 translation_번역._engine_translate_to_korean
을 사용한다.
"""

import io
import os
import re
import json
import time
import zipfile
import datetime
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from common_공용유틸 import (
    ENGINE_HTTP_TIMEOUT,
    _clean_secret_env,
    _engine_log,
    _now_kst,
    log_error,
)
from config_환경설정 import ENABLE_DART, ENABLE_TELEGRAM_CHANNELS, ENABLE_YOUTUBE, USER_AGENT

DART_API_KEY = _clean_secret_env("DART_API_KEY")
DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_CORP_CODE_CACHE_FILE = os.environ.get("NEWS_BOT_DART_CORP_CACHE", "dart_corp_code_map.json")
DART_CORP_CODE_CACHE_DAYS = int(os.environ.get("NEWS_BOT_DART_CORP_CACHE_DAYS", "7"))

# "채널1(필터)+채널2(무조건)" 구성: 콤마로 구분된 공개 텔레그램 채널 사용자명(@ 없이)
TELEGRAM_CHANNEL_FILTERED = [c.strip().lstrip("@") for c in os.environ.get("TELEGRAM_CHANNEL_FILTERED", "").split(",") if c.strip()]
TELEGRAM_CHANNEL_FORCE = [c.strip().lstrip("@") for c in os.environ.get("TELEGRAM_CHANNEL_FORCE", "").split(",") if c.strip()]

YOUTUBE_CHANNEL_IDS = [c.strip() for c in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",") if c.strip()]

_dart_corp_code_map = {}       # {회사명: 종목코드}
_dart_corp_code_loaded = False


# ============================================================
# DART corpCode 매핑 (회사명 → 종목코드)
# ============================================================
def _dart_load_corp_code_map(force=False):
    """DART가 제공하는 전체 기업 코드 목록(zip 안의 CORPCODE.xml)을 내려받아
    {회사명: 종목코드} 매핑을 만든다. 상장사만 stock_code가 채워져 있으므로
    비어있는 항목은 제외한다. 하루 단위로 로컬 캐시하여 매 재시작마다
    수 MB짜리 zip을 다시 받지 않게 한다."""
    global _dart_corp_code_map, _dart_corp_code_loaded
    if _dart_corp_code_loaded and not force:
        return
    _dart_corp_code_loaded = True

    if not DART_API_KEY:
        _engine_log("warning", "[DART] DART_API_KEY 없음 | corpCode 매핑을 건너뜁니다.")
        return

    if not force and os.path.exists(DART_CORP_CODE_CACHE_FILE):
        try:
            with open(DART_CORP_CODE_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f) or {}
            if time.time() - float(cached.get("ts", 0)) < DART_CORP_CODE_CACHE_DAYS * 86400:
                _dart_corp_code_map = cached.get("map", {}) or {}
                _engine_log("info", "[DART] corpCode 캐시 로드 완료 | %d건", len(_dart_corp_code_map))
                return
        except Exception as e:
            log_error("DART corpCode 캐시 로드", e)

    try:
        r = requests.get(f"{DART_BASE_URL}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("error", "[DART] corpCode 다운로드 실패 | status=%s", r.status_code)
            return
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml_bytes = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml_bytes)
        mapping = {}
        for item in root.findall("list"):
            name = (item.findtext("corp_name") or "").strip()
            code = (item.findtext("stock_code") or "").strip()
            if name and code:
                mapping[name] = code
        _dart_corp_code_map = mapping
        try:
            with open(DART_CORP_CODE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "map": mapping}, f, ensure_ascii=False)
        except Exception as e:
            log_error("DART corpCode 캐시 저장", e)
        _engine_log("info", "[DART] corpCode 매핑 갱신 완료 | %d건", len(mapping))
    except Exception as e:
        log_error("DART corpCode 매핑 갱신", e)


def _dart_stock_code_for_name(name):
    """회사명으로 6자리 종목코드를 조회한다. 정확히 일치하는 이름이 없으면
    (예: '삼성전자우' vs '삼성전자' 같은 표기 차이) 접두어 일치로 한 번 더
    시도한다. 그래도 없으면 빈 문자열(비상장/미등록)을 반환한다."""
    name = str(name or "").strip()
    if not name:
        return ""
    _dart_load_corp_code_map()
    if name in _dart_corp_code_map:
        return _dart_corp_code_map[name]
    for corp_name, code in _dart_corp_code_map.items():
        if corp_name.startswith(name) or name.startswith(corp_name):
            return code
    return ""


# ============================================================
# DART 공시 실시간 수집
# ============================================================
def _engine_run_dart():
    if not ENABLE_DART:
        _engine_log("warning", "[DART] ENABLE_DART=OFF")
        return
    if not DART_API_KEY:
        _engine_log("error", "[DART] DART_API_KEY 없음")
        return

    from news_engine_핵심엔진 import _engine_process_item

    today = _now_kst().strftime("%Y%m%d")
    try:
        r = requests.get(f"{DART_BASE_URL}/list.json", params={
            "crtfc_key": DART_API_KEY, "bgn_de": today, "end_de": today,
            "page_no": 1, "page_count": 100, "sort": "date", "sort_mth": "desc",
        }, timeout=ENGINE_HTTP_TIMEOUT)
        data = r.json() if r.ok else {}
        status = data.get("status")
        if status == "013":  # "조회된 데이터가 없습니다" - 정상 상황
            _engine_log("debug", "[DART] 오늘자 신규 공시 없음")
            return
        if status != "000":
            _engine_log("warning", "[DART] 목록 조회 실패 | status=%s | msg=%s", status, data.get("message"))
            return
        items = data.get("list", []) or []
    except Exception as e:
        log_error("DART 공시 목록 조회", e)
        return

    total = 0
    for it in items:
        corp = it.get("corp_name", "")
        report = it.get("report_nm", "")
        rcept_no = it.get("rcept_no", "")
        link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
        title = f"[공시] {corp} - {report}"
        # DART list.json은 접수'일'만 제공하고 시각은 없어 최근성 게이트를 오작동시키므로
        # published는 비워 넘기고, 오늘자 조회범위 + 중복방지(해시)로 신선도를 보장한다.
        if _engine_process_item("DART", title, link, "", report):
            total += 1
    _engine_log("info", "[DART] 이번주기 조회=%d건 | 신규=%d", len(items), total)


def _engine_backfill_dart_historical(days=365):
    """/백필 [일수] 명령으로 호출된다. 과거 DART 공시를 소급 조회해
    과거사례 캐시(news_engine._engine_historical_cache)와 일정DB에 적재한다."""
    if not DART_API_KEY:
        _engine_log("error", "[DART 백필] DART_API_KEY 없음")
        return 0

    from news_engine_핵심엔진 import _engine_historical_cache

    try:
        from schedule_일정DB import _schedule_add_dart_row
    except Exception:
        _schedule_add_dart_row = None

    today = _now_kst().date()
    start = today - datetime.timedelta(days=int(days))
    recorded = 0
    cursor = start

    while cursor <= today:
        end = min(today, cursor + datetime.timedelta(days=30))
        try:
            r = requests.get(f"{DART_BASE_URL}/list.json", params={
                "crtfc_key": DART_API_KEY,
                "bgn_de": cursor.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "page_no": 1, "page_count": 100,
            }, timeout=ENGINE_HTTP_TIMEOUT)
            data = r.json() if r.ok else {}
            items = data.get("list", []) if data.get("status") == "000" else []
        except Exception as e:
            log_error("DART 백필 조회", e, start=cursor.isoformat(), end=end.isoformat())
            items = []

        for it in items:
            corp = it.get("corp_name", "")
            report = it.get("report_nm", "")
            rcept_dt = it.get("rcept_dt", "")
            rcept_no = it.get("rcept_no", "")
            link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
            _engine_historical_cache.append({
                "text": f"{corp} {report}", "title": f"{corp} {report}",
                "link": link, "published_dt": None, "source": "DART",
            })
            if _schedule_add_dart_row:
                try:
                    _schedule_add_dart_row(report, corp, link, rcept_dt)
                except Exception:
                    pass
            recorded += 1

        cursor = end + datetime.timedelta(days=1)
        time.sleep(0.2)  # DART API 호출 과다 방지

    if len(_engine_historical_cache) > 20000:
        del _engine_historical_cache[: len(_engine_historical_cache) - 20000]

    _engine_log("info", "[DART 백필] 완료 | 기간=%d일 | 누적=%d건", days, recorded)
    return recorded


# ============================================================
# 텔레그램 채널 수집 (공개 채널의 t.me/s/<채널명> 미리보기 페이지 스크래핑)
# 비공개 채널이나 봇을 초대해야 하는 채널은 지원하지 않는다.
# ============================================================
def _telegram_channel_fetch_preview(channel):
    try:
        r = requests.get(f"https://t.me/s/{channel}", headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("warning", "[텔레그램채널] %s | status=%s", channel, r.status_code)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        posts = []
        for wrap in soup.select("div.tgme_widget_message"):
            text_el = wrap.select_one(".tgme_widget_message_text")
            text = text_el.get_text("\n").strip() if text_el else ""
            if not text:
                continue
            post_id = wrap.get("data-post", "")
            link = f"https://t.me/{post_id}" if post_id else ""
            time_el = wrap.select_one("time.time")
            published = time_el.get("datetime", "") if time_el else ""
            title = text.splitlines()[0][:120]
            posts.append({"title": title, "text": text, "link": link, "published": published})
        return posts
    except Exception as e:
        _engine_log("warning", "[텔레그램채널] %s | 조회 실패=%s", channel, str(e)[:120])
        return []


def _engine_run_telegram_channels():
    if not ENABLE_TELEGRAM_CHANNELS:
        _engine_log("warning", "[텔레그램채널] ENABLE_TELEGRAM_CHANNELS=OFF")
        return
    if not TELEGRAM_CHANNEL_FILTERED and not TELEGRAM_CHANNEL_FORCE:
        _engine_log("warning", "[텔레그램채널] TELEGRAM_CHANNEL_FILTERED/TELEGRAM_CHANNEL_FORCE 환경변수가 설정되지 않았습니다.")
        return

    from news_engine_핵심엔진 import _engine_process_item

    total = 0
    for channel in TELEGRAM_CHANNEL_FILTERED:
        for post in _telegram_channel_fetch_preview(channel):
            if _engine_process_item(f"텔레그램/{channel}", post["title"], post["link"], post["published"], post["text"]):
                total += 1
    for channel in TELEGRAM_CHANNEL_FORCE:
        for post in _telegram_channel_fetch_preview(channel):
            # "무조건" 채널: MASTER 필터링을 거치되 관련주 유무/시황성 판단으로는 걸러내지 않는다.
            if _engine_process_item(f"텔레그램강제/{channel}", post["title"], post["link"], post["published"], post["text"], force_send=True):
                total += 1
    _engine_log("info", "[텔레그램채널] 이번주기 신규=%d", total)


# ============================================================
# 유튜브 수집 (채널 RSS 피드)
# ============================================================
def _engine_run_youtube():
    if not ENABLE_YOUTUBE:
        _engine_log("warning", "[유튜브] ENABLE_YOUTUBE=OFF")
        return
    if not YOUTUBE_CHANNEL_IDS:
        _engine_log("warning", "[유튜브] YOUTUBE_CHANNEL_IDS 환경변수가 설정되지 않았습니다.")
        return

    from news_engine_핵심엔진 import _engine_fetch_rss, _engine_entry_published, _engine_process_item

    total = 0
    checked = 0
    for channel_id in YOUTUBE_CHANNEL_IDS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        entries = _engine_fetch_rss(url, "유튜브")
        for e in entries[:15]:
            checked += 1
            if _engine_process_item("유튜브", e.get("title", ""), e.get("link", ""), _engine_entry_published(e), e.get("summary", "")):
                total += 1
    _engine_log("info", "[유튜브] 채널=%d개 | 확인=%d건 | 신규=%d", len(YOUTUBE_CHANNEL_IDS), checked, total)
