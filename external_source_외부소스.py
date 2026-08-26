# -*- coding: utf-8 -*-
"""
외부 소스 연동 모듈 (DART 공시 / 텔레그램 채널 / 유튜브).

중요:
- 이 모듈은 외부 소스의 "수집"을 담당한다.
- 최종 필터링/판단/출력은 news_engine_핵심엔진._engine_process_item()이 단일 소유한다.
- DART는 같은 공시가 수집 주기마다 반복 유입되지 않도록 수집 단계에서도
  접수번호(rcept_no) 기준의 메모리 중복 방지와 짧은 TTL 디바운스를 적용한다.
- force_send=True는 MASTER의 일반 필터를 조정할 수 있지만, 중복 방지와
  거짓말탐지/안전 검사는 우회시키면 안 된다.

번역 기능은 translation_번역.py가 전담한다.
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
from config_환경설정 import (
    ENABLE_DART,
    ENABLE_TELEGRAM_CHANNELS,
    ENABLE_YOUTUBE,
    USER_AGENT,
)

DART_API_KEY = _clean_secret_env("DART_API_KEY")
DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_CORP_CODE_CACHE_FILE = os.environ.get(
    "NEWS_BOT_DART_CORP_CACHE", "dart_corp_code_map.json"
)
DART_CORP_CODE_CACHE_DAYS = int(
    os.environ.get("NEWS_BOT_DART_CORP_CACHE_DAYS", "7")
)

# DART 반복 수집 방지.
# 같은 접수번호는 프로세스가 살아 있는 동안 한 번만 MASTER에 전달한다.
DART_SEEN_TTL = int(os.environ.get("NEWS_BOT_DART_SEEN_TTL", "86400"))
_dart_seen = {}

# "채널1(필터)+채널2(무조건)" 구성: 콤마로 구분된 공개 텔레그램 채널 사용자명(@ 없이)
TELEGRAM_CHANNEL_FILTERED = [
    c.strip().lstrip("@")
    for c in os.environ.get("TELEGRAM_CHANNEL_FILTERED", "").split(",")
    if c.strip()
]
TELEGRAM_CHANNEL_FORCE = [
    c.strip().lstrip("@")
    for c in os.environ.get("TELEGRAM_CHANNEL_FORCE", "").split(",")
    if c.strip()
]

YOUTUBE_CHANNEL_IDS = [
    c.strip()
    for c in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",")
    if c.strip()
]

_dart_corp_code_map = {}
_dart_corp_code_loaded = False


# ============================================================
# DART corpCode 매핑 (회사명 → 종목코드)
# ============================================================
def _dart_load_corp_code_map(force=False):
    """DART CORPCODE.xml을 내려받아 {회사명: 종목코드} 매핑을 만든다.
    상장사(stock_code 존재)만 저장하며 로컬 캐시를 사용한다.
    """
    global _dart_corp_code_map, _dart_corp_code_loaded

    if _dart_corp_code_loaded and not force:
        return

    if not DART_API_KEY:
        _engine_log("warning", "[DART] DART_API_KEY 없음 | corpCode 매핑을 건너뜁니다.")
        _dart_corp_code_loaded = True
        return

    if not force and os.path.exists(DART_CORP_CODE_CACHE_FILE):
        try:
            with open(DART_CORP_CODE_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f) or {}

            if (
                time.time() - float(cached.get("ts", 0))
                < DART_CORP_CODE_CACHE_DAYS * 86400
            ):
                _dart_corp_code_map = cached.get("map", {}) or {}
                _dart_corp_code_loaded = True
                _engine_log(
                    "info",
                    "[DART] corpCode 캐시 로드 완료 | %d건",
                    len(_dart_corp_code_map),
                )
                return
        except Exception as e:
            log_error("DART corpCode 캐시 로드", e)

    try:
        r = requests.get(
            f"{DART_BASE_URL}/corpCode.xml",
            params={"crtfc_key": DART_API_KEY},
            timeout=ENGINE_HTTP_TIMEOUT,
        )
        if not r.ok:
            _engine_log(
                "error",
                "[DART] corpCode 다운로드 실패 | status=%s",
                r.status_code,
            )
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
        _dart_corp_code_loaded = True

        try:
            with open(DART_CORP_CODE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"ts": time.time(), "map": mapping},
                    f,
                    ensure_ascii=False,
                )
        except Exception as e:
            log_error("DART corpCode 캐시 저장", e)

        _engine_log(
            "info",
            "[DART] corpCode 매핑 갱신 완료 | %d건",
            len(mapping),
        )

    except Exception as e:
        log_error("DART corpCode 매핑 갱신", e)


def _dart_stock_code_for_name(name):
    """회사명으로 6자리 종목코드를 조회한다."""
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


def _dart_cleanup_seen(now=None):
    """오래된 DART 중복 키를 제거한다."""
    now = time.time() if now is None else now
    expired = [
        key for key, ts in _dart_seen.items()
        if now - ts >= DART_SEEN_TTL
    ]
    for key in expired:
        _dart_seen.pop(key, None)


def _dart_is_duplicate(rcept_no, corp="", report=""):
    """같은 DART 공시가 같은 프로세스에서 반복 전달되는 것을 차단한다.

    접수번호가 있으면 접수번호를 최우선 식별자로 사용한다.
    접수번호가 없는 비정상 응답에 대해서는 회사명+보고서명 조합을 사용한다.
    """
    now = time.time()
    _dart_cleanup_seen(now)

    rcept_no = str(rcept_no or "").strip()
    corp = str(corp or "").strip()
    report = str(report or "").strip()

    key = f"rcept:{rcept_no}" if rcept_no else f"fallback:{corp}|{report}"

    if key in _dart_seen:
        return True

    _dart_seen[key] = now
    return False


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
        r = requests.get(
            f"{DART_BASE_URL}/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "bgn_de": today,
                "end_de": today,
                "page_no": 1,
                "page_count": 100,
                "sort": "date",
                "sort_mth": "desc",
            },
            timeout=ENGINE_HTTP_TIMEOUT,
        )
        data = r.json() if r.ok else {}
        status = data.get("status")

        if status == "013":
            _engine_log("debug", "[DART] 오늘자 신규 공시 없음")
            return

        if status != "000":
            _engine_log(
                "warning",
                "[DART] 목록 조회 실패 | status=%s | msg=%s",
                status,
                data.get("message"),
            )
            return

        items = data.get("list", []) or []

    except Exception as e:
        log_error("DART 공시 목록 조회", e)
        return

    total = 0
    duplicate = 0

    for it in items:
        corp = it.get("corp_name", "")
        report = it.get("report_nm", "")
        rcept_no = it.get("rcept_no", "")

        # DART는 접수번호가 사실상 공시 고유 ID이므로
        # 같은 공시가 다음 수집 주기에 다시 내려와도 MASTER에 재전달하지 않는다.
        if _dart_is_duplicate(rcept_no, corp, report):
            duplicate += 1
            continue

        link = (
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            if rcept_no
            else ""
        )

        title = f"[공시] {corp} - {report}"

        # DART list.json은 접수 '일' 중심이라 published를 비워
        # MASTER의 최근성 판정이 잘못 작동하지 않게 한다.
        if _engine_process_item(
            "DART",
            title,
            link,
            "",
            report,
        ):
            total += 1

    _engine_log(
        "info",
        "[DART] 이번주기 조회=%d건 | 신규=%d | 중복차단=%d",
        len(items),
        total,
        duplicate,
    )


def _engine_backfill_dart_historical(days=365):
    """과거 DART 공시를 소급 조회해 역사 캐시/일정DB에 적재한다.

    백필은 실시간 MASTER 전송을 하지 않는다.
    """
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
            r = requests.get(
                f"{DART_BASE_URL}/list.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "bgn_de": cursor.strftime("%Y%m%d"),
                    "end_de": end.strftime("%Y%m%d"),
                    "page_no": 1,
                    "page_count": 100,
                },
                timeout=ENGINE_HTTP_TIMEOUT,
            )
            data = r.json() if r.ok else {}
            items = data.get("list", []) if data.get("status") == "000" else []

        except Exception as e:
            log_error(
                "DART 백필 조회",
                e,
                start=cursor.isoformat(),
                end=end.isoformat(),
            )
            items = []

        for it in items:
            corp = it.get("corp_name", "")
            report = it.get("report_nm", "")
            rcept_dt = it.get("rcept_dt", "")
            rcept_no = it.get("rcept_no", "")

            link = (
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                if rcept_no
                else ""
            )

            _engine_historical_cache.append(
                {
                    "text": f"{corp} {report}",
                    "title": f"{corp} {report}",
                    "link": link,
                    "published_dt": None,
                    "source": "DART",
                }
            )

            if _schedule_add_dart_row:
                try:
                    _schedule_add_dart_row(report, corp, link, rcept_dt)
                except Exception:
                    pass

            recorded += 1

        cursor = end + datetime.timedelta(days=1)
        time.sleep(0.2)

    if len(_engine_historical_cache) > 20000:
        del _engine_historical_cache[: len(_engine_historical_cache) - 20000]

    _engine_log(
        "info",
        "[DART 백필] 완료 | 기간=%d일 | 누적=%d건",
        days,
        recorded,
    )
    return recorded


# ============================================================
# 텔레그램 채널 수집
# ============================================================
def _telegram_channel_fetch_preview(channel):
    try:
        r = requests.get(
            f"https://t.me/s/{channel}",
            headers={"User-Agent": USER_AGENT},
            timeout=ENGINE_HTTP_TIMEOUT,
        )

        if not r.ok:
            _engine_log(
                "warning",
                "[텔레그램채널] %s | status=%s",
                channel,
                r.status_code,
            )
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

            posts.append(
                {
                    "title": title,
                    "text": text,
                    "link": link,
                    "published": published,
                }
            )

        return posts

    except Exception as e:
        _engine_log(
            "warning",
            "[텔레그램채널] %s | 조회 실패=%s",
            channel,
            str(e)[:120],
        )
        return []


def _engine_run_telegram_channels():
    if not ENABLE_TELEGRAM_CHANNELS:
        _engine_log("warning", "[텔레그램채널] ENABLE_TELEGRAM_CHANNELS=OFF")
        return

    if not TELEGRAM_CHANNEL_FILTERED and not TELEGRAM_CHANNEL_FORCE:
        _engine_log(
            "warning",
            "[텔레그램채널] TELEGRAM_CHANNEL_FILTERED/"
            "TELEGRAM_CHANNEL_FORCE 환경변수가 설정되지 않았습니다.",
        )
        return

    from news_engine_핵심엔진 import _engine_process_item

    total = 0

    for channel in TELEGRAM_CHANNEL_FILTERED:
        for post in _telegram_channel_fetch_preview(channel):
            if _engine_process_item(
                f"텔레그램/{channel}",
                post["title"],
                post["link"],
                post["published"],
                post["text"],
            ):
                total += 1

    for channel in TELEGRAM_CHANNEL_FORCE:
        for post in _telegram_channel_fetch_preview(channel):
            # force_send는 일반 관련주/시황성 필터의 정책만 조정한다.
            # 중복 방지/거짓말탐지/기본 검증까지 우회해서는 안 된다.
            if _engine_process_item(
                f"텔레그램강제/{channel}",
                post["title"],
                post["link"],
                post["published"],
                post["text"],
                force_send=True,
            ):
                total += 1

    _engine_log(
        "info",
        "[텔레그램채널] 이번주기 신규=%d",
        total,
    )


# ============================================================
# 유튜브 수집 (채널 RSS 피드)
# ============================================================
def _engine_run_youtube():
    if not ENABLE_YOUTUBE:
        _engine_log("warning", "[유튜브] ENABLE_YOUTUBE=OFF")
        return

    if not YOUTUBE_CHANNEL_IDS:
        _engine_log(
            "warning",
            "[유튜브] YOUTUBE_CHANNEL_IDS 환경변수가 설정되지 않았습니다.",
        )
        return

    from news_engine_핵심엔진 import (
        _engine_fetch_rss,
        _engine_entry_published,
        _engine_process_item,
    )

    total = 0
    checked = 0

    for channel_id in YOUTUBE_CHANNEL_IDS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        entries = _engine_fetch_rss(url, "유튜브")

        for e in entries[:15]:
            checked += 1

            if _engine_process_item(
                "유튜브",
                e.get("title", ""),
                e.get("link", ""),
                _engine_entry_published(e),
                e.get("summary", ""),
            ):
                total += 1

    _engine_log(
        "info",
        "[유튜브] 채널=%d개 | 확인=%d건 | 신규=%d",
        len(YOUTUBE_CHANNEL_IDS),
        checked,
        total,
    )
