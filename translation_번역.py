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

# ==== module: translation (auto-split from original main.py) ====

from common_공용유틸 import ENGINE_HTTP_TIMEOUT, _engine_log, log_error
from config_환경설정 import USER_AGENT


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
_TRANSLATE_MIN_INTERVAL_SEC = 4.5  # [수정] 2.2s → 4.5s. 사전 필터로 호출량 자체를 줄였지만,
# 남은 호출도 무료 번역 엔드포인트의 429를 덜 맞도록 간격을 더 넓힌다.
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

    # [버그 수정] 기존에는 for attempt in range(1) + "if attempt < 0: continue" 조합 때문에
    # attempt가 항상 0이라 이 조건이 절대 참이 될 수 없었다. 즉 주석과 달리 429/5xx가
    # 뜨면 실제로는 단 한 번도 재시도하지 않고 바로 포기하고 있었다. 이제 최대 3회
    # 시도하며, 429/5xx는 지수 백오프(1초 → 2초)로 재시도한다.
    max_attempts = 3
    for attempt in range(max_attempts):
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
                # (1차 1초, 2차 2초 백오프). 마지막 시도까지 실패하면 재시도 큐로 넘긴다.
                if attempt < max_attempts - 1:
                    backoff = 1.0 * (2 ** attempt)
                    _engine_log("warning", "[번역 재시도] 외신 | status=%s | %.1f초 후 %d번째 재시도",
                                r.status_code, backoff, attempt + 2)
                    time.sleep(backoff)
                    continue
                _engine_log("warning", "[번역 실패] 외신 | status=%s | 이번 주기는 스킵하고 재시도 큐로 이동", r.status_code)
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
            if attempt < max_attempts - 1:
                _engine_log("warning", "[번역 재시도] 외신 | 원인=%s | %d번째 재시도 예정", str(e)[:120], attempt + 2)
                time.sleep(1.0 * (attempt + 1))
                continue
            _engine_log("warning", "[번역 실패] 외신 | %s", str(e)[:120])
            break

    # 영문 원문을 그대로 송출하지 않기 위해 실패는 빈 문자열로 처리한다.
    return ""


def _engine_queue_translation_retry(source, title, link, published, extra):
    key = str(link or "").strip() or f"{source}|{title}"
    with _engine_translate_retry_lock:
        entry = _engine_translate_retry_queue.get(key)
        if entry:
            entry["attempts"] += 1
            entry["published"] = published or entry.get("published", "")
            entry["extra"] = extra or entry.get("extra", "")
            entry["next_retry_at"] = time.time() + min(300.0, 60.0 * entry["attempts"])
        else:
            entry = {"source": source, "title": title, "link": link,
                      "published": published, "extra": extra, "attempts": 1, "next_retry_at": time.time() + 60.0}
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
    from news_engine_핵심엔진 import _engine_process_item
    now = time.time()
    with _engine_translate_retry_lock:
        pending = [e for e in _engine_translate_retry_queue.values()
                   if float(e.get("next_retry_at", 0) or 0) <= now]
    if not pending:
        return
    # [조정] 기존엔 한 사이클(60초)에 최대 2건만 처리해, 한 번에 6건이 몰리면
    # 나머지 4건이 몇 분씩 밀리다 최대 재시도(5회) 초과로 영구 폐기되는 경우가
    # 있었다. 번역 자체에 이미 요청 간격(4.5초)이 있어 한 사이클 안에서도
    # 5건 정도는 안전하게 처리 가능하므로 5건으로 늘린다.
    pending = pending[:5]
    _engine_log("info", "[번역 재시도 큐] 대기=%d건 | 이번 주기 최대 5건 처리", len(pending))
    for entry in pending:
        try:
            _engine_process_item(entry["source"], entry["title"], entry["link"],
                                  entry.get("published", ""), entry.get("extra", ""))
        except Exception as e:
            log_error("번역 재시도 큐 처리", e, title=str(entry.get("title", ""))[:120])


def _engine_translate_foreign_item(source: str, title: str, extra: str):
    from overseas_해외수집 import _engine_annotate_index_points_with_pct
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
